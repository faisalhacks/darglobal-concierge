"""Parse saved snapshots -> data/concierge.sqlite (SPEC section 7). NO network access.

    python -m scraper.build_dataset        (or: python scraper/build_dataset.py)

Sources: Wasalt snapshots in scraper/snapshots/ (scraper/fetch.py, robots-compliant), DarGlobal pages the owner
collected in their own browser into scraper/manual/darglobal/extracts/*.json (parsed by scraper/darglobal_manual.py),
and sourced third-party facts about DarGlobal projects in scraper/manual/darglobal/thirdparty/*.json (LSE RNS mirror,
press, wire-hosted company releases; merged by scraper/darglobal_thirdparty.py).
Any new extract / third-party file is picked up on the next run with no code change.

Outputs: data/concierge.sqlite, data/fixtures/mini.sqlite, data/completeness.json, data/PII_SCAN.md,
         data/build_report.json
"""
from __future__ import annotations

import hashlib
import html as htmllib
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import quote, unquote, urlparse

from pydantic import BaseModel, field_validator
from selectolax.lexbor import LexborHTMLParser as HTMLParser

try:  # python -m scraper.build_dataset
    from . import darglobal_manual as dgm
    from . import darglobal_thirdparty as dgt
except ImportError:  # python scraper/build_dataset.py, or tests with scraper/ on sys.path
    import darglobal_manual as dgm
    import darglobal_thirdparty as dgt

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
SNAP = ROOT / "snapshots"
DATA = REPO / "data"
DATA.mkdir(exist_ok=True)
(DATA / "fixtures").mkdir(exist_ok=True)

IMG_BASE = "https://imagedelivery.net/1DNKFJPRaeUdy_j8F7HT3w/production"
CONTACT_DG = "https://darglobal.co.uk/get-in-touch"     # taken from the already-fetched sitemap snapshot
CONTACT_WASALT = "https://wasalt.sa/en/corporate"       # official corporate page, already in snapshots

SCHEMA = """
CREATE TABLE projects(
  id TEXT PRIMARY KEY, slug TEXT, name_en TEXT, name_ar TEXT, site TEXT, developer TEXT, brand_partner TEXT,
  city TEXT, country TEXT, lat REAL NULL, lng REAL NULL,
  property_types JSON, unit_types JSON,
  price_from_amount REAL NULL, price_from_currency TEXT NULL, price_to_amount REAL NULL,
  area_min_m2 REAL NULL, area_max_m2 REAL NULL,
  amenities JSON, status TEXT, handover_year INT NULL,
  description_en TEXT, description_ar TEXT, image_urls JSON,
  source_url TEXT, scraped_at TEXT, content_hash TEXT);
CREATE TABLE listings(
  id TEXT PRIMARY KEY, title TEXT, listing_type TEXT CHECK(listing_type IN ('buy','rent')),
  property_type TEXT, price_amount REAL, price_currency TEXT,
  beds INT, baths INT, area_m2 REAL, city TEXT, district TEXT,
  project_ref TEXT NULL REFERENCES projects(id),
  image_urls JSON, source_url TEXT, scraped_at TEXT, content_hash TEXT);
CREATE TABLE pages(id TEXT PRIMARY KEY, site TEXT, page_type TEXT, title TEXT, text TEXT, lang TEXT,
  source_url TEXT, scraped_at TEXT);
CREATE TABLE chunks(id TEXT PRIMARY KEY, entity_type TEXT, entity_id TEXT, site TEXT, lang TEXT, text TEXT,
  city TEXT, country TEXT, source_url TEXT, scraped_at TEXT);
CREATE TABLE dataset_meta(version TEXT, scraped_at_min TEXT, scraped_at_max TEXT, counts JSON, completeness JSON);
CREATE INDEX idx_listings_city ON listings(city);
CREATE INDEX idx_listings_type ON listings(listing_type);
CREATE INDEX idx_projects_city ON projects(city);
CREATE INDEX idx_chunks_entity ON chunks(entity_type, entity_id);
"""

# ---------------------------------------------------------------- PII
PHONE_RE = re.compile(r"(?:\+?966|00966)?[\s\-]?0?5\d(?:[\s\-]?\d){7}|(?:\+?\d[\s\-]?){9,15}\d|8001\d{6}|9200\d{5}")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
WA_RE = re.compile(r"(?:wa\.me/|whatsapp|واتس|واتساب|وتساب)", re.I)
CONTACT_LINE_RE = re.compile(r"(للتواصل|التواصل|تواصل|اتصل|الاتصال|جوال|هاتف|رقم|واتس|call\b|contact|whatsapp|phone|mobile)", re.I)
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def strip_pii(text: str | None) -> str | None:
    if not text:
        return text
    out = []
    for line in re.split(r"\n+", text):
        norm = line.translate(ARABIC_DIGITS)
        if CONTACT_LINE_RE.search(norm) and (PHONE_RE.search(norm) or EMAIL_RE.search(norm) or WA_RE.search(norm) or len(norm) < 80):
            continue  # whole contact line dropped
        norm_line = line
        if PHONE_RE.search(norm) or EMAIL_RE.search(norm) or WA_RE.search(norm):
            norm_line = PHONE_RE.sub("", norm)
            norm_line = EMAIL_RE.sub("", norm_line)
            norm_line = re.sub(r"wa\.me/\S*", "", norm_line, flags=re.I)
        out.append(norm_line)
    return "\n".join(s for s in (o.strip() for o in out) if s)


CITY_CANON = {
    "aldammam": "Dammam", "dammam": "Dammam", "makkah al mukarramah": "Makkah", "makkah": "Makkah", "mecca": "Makkah",
    "khobar": "Al Khobar", "al khobar": "Al Khobar", "alkhobar": "Al Khobar", "alttayif": "Taif", "taif": "Taif",
    "khamis mushait": "Khamis Mushayt", "khamis mushayt": "Khamis Mushayt", "madinah": "Madinah",
    "al madinah al munawwarah": "Madinah", "riyadh": "Riyadh", "jeddah": "Jeddah", "jazan": "Jazan",
}


def canon_city(c: str | None) -> str | None:
    """Normalise spelling variants of the same city (as published on the site); unknown values pass through."""
    if not c:
        return c
    return CITY_CANON.get(c.strip().lower(), c.strip())


def html_to_text(h: str | None) -> str | None:
    if not h:
        return h
    h = re.sub(r"<(br|/p|/div|/li|/h[1-6])\s*/?>", "\n", h, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", h)
    t = htmllib.unescape(t)
    t = re.sub(r"[ \t ]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return t.strip()


def is_arabic(s: str | None) -> bool:
    if not s:
        return False
    ar = len(re.findall(r"[؀-ۿ]", s))
    lat = len(re.findall(r"[A-Za-z]", s))
    return ar > lat


# ---------------------------------------------------------------- models
class Money(BaseModel):
    amount: float
    currency: str


class Project(BaseModel):
    id: str
    slug: str
    name_en: Optional[str]
    name_ar: Optional[str]
    site: Literal["DarGlobal", "Wasalt"]
    developer: Optional[str] = None
    brand_partner: Optional[str] = None
    city: Optional[str]
    country: Optional[str]
    lat: Optional[float] = None
    lng: Optional[float] = None
    property_types: list[str] = []
    unit_types: list[str] = []
    price_from_amount: Optional[float] = None
    price_from_currency: Optional[str] = None
    price_to_amount: Optional[float] = None
    area_min_m2: Optional[float] = None
    area_max_m2: Optional[float] = None
    amenities: list[str] = []
    status: Optional[str] = None
    handover_year: Optional[int] = None
    description_en: Optional[str] = None
    description_ar: Optional[str] = None
    image_urls: list[str] = []
    source_url: str
    scraped_at: str

    @field_validator("source_url")
    @classmethod
    def _url(cls, v):
        assert v.startswith("https://"), v
        return v


class Listing(BaseModel):
    id: str
    title: str
    listing_type: Literal["buy", "rent"]
    property_type: Optional[str]
    price_amount: Optional[float]
    price_currency: Optional[str]
    beds: Optional[int]
    baths: Optional[int]
    area_m2: Optional[float]
    city: Optional[str]
    district: Optional[str]
    project_ref: Optional[str] = None
    image_urls: list[str] = []
    source_url: str
    scraped_at: str


class Page(BaseModel):
    id: str
    site: Literal["DarGlobal", "Wasalt"]
    page_type: str
    title: str
    text: str
    lang: Literal["en", "ar"]
    source_url: str
    scraped_at: str


# ---------------------------------------------------------------- snapshot access
def iter_snapshots():
    for meta_p in SNAP.glob("*/*.meta.json"):
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        body_p = meta_p.with_name(meta_p.name.replace(".meta.json", ".body"))
        if not body_p.exists():
            continue
        yield meta, body_p


def next_data(body: str):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', body, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def chash(d: dict) -> str:
    d = {k: v for k, v in d.items() if k not in ("scraped_at", "content_hash")}
    return hashlib.sha256(json.dumps(d, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def num(v):
    if v is None or v == "":
        return None
    try:
        f = float(str(v).replace(",", ""))
        return f if f > 0 else None
    except ValueError:
        return None


def intnum(v):
    f = num(v)
    return int(f) if f is not None else None


def img_url(kind: str, ent_id, name: str) -> str:
    return f"{IMG_BASE}/{kind}/{ent_id}/images/{quote(name)}/width=800,quality=75,format=auto"


# ---------------------------------------------------------------- extractors
def listing_from_wasalt(p: dict, scraped_at: str) -> Listing | None:
    info = p.get("propertyInfo") or {}
    if not isinstance(info, dict) or not info or not p.get("id") or "projectInfo" in p:
        return None
    pf = info.get("propertyFor")
    if pf not in ("sale", "rent"):
        return None
    attrs = {a.get("key"): a.get("value") for a in (p.get("attributes") or []) if isinstance(a, dict)}
    if pf == "sale":
        price = num(info.get("salePrice"))
    else:
        price = num(info.get("expectedRent")) or num(info.get("salePrice"))
    area = num(attrs.get("builtUpArea")) or num(attrs.get("carpetArea")) or num(attrs.get("landArea")) or num(p.get("floorSize"))
    slug = info.get("slug")
    if not slug:
        return None
    imgs = [img_url("properties", p["id"], n) for n in ((p.get("propertyFiles") or {}).get("images") or [])[:6]]
    title = info.get("title") or info.get("propertyName")
    if pf == "rent" and info.get("rentFreq"):
        title = f"{title}"
    freq = None
    rfq = info.get("rentFreq")
    if pf == "rent" and isinstance(rfq, dict) and rfq:
        freq = next((k for k, v in rfq.items() if isinstance(v, dict) and v.get("default_freq")), next(iter(rfq)))
        if not price and isinstance(rfq.get(freq), dict):
            price = num(rfq[freq].get("amount"))
    elif pf == "rent" and isinstance(rfq, str) and rfq:
        freq = rfq
    return Listing(
        id=f"wasalt-l-{p['id']}", title=strip_pii(title) or "", listing_type="buy" if pf == "sale" else "rent",
        property_type=info.get("propertySubType"), price_amount=price,
        price_currency=(info.get("currencyType") if price else None),
        beds=intnum(attrs.get("noOfBedrooms")), baths=intnum(attrs.get("noOfBathrooms")), area_m2=area,
        city=canon_city(info.get("city")), district=info.get("district") or info.get("zone"),
        image_urls=imgs, source_url=f"https://wasalt.sa/en/property/{pf}/{slug}", scraped_at=scraped_at,
    ), freq


def project_from_wasalt(pp: dict, url: str, scraped_at: str) -> Project | None:
    cd = (pp.get("compoundDetails") or {}).get("data") or {}
    pi = cd.get("projectInfo") or {}
    if not cd.get("id") or not pi:
        return None
    pid = cd["id"]
    title = (pi.get("title") or "").strip()
    desc = strip_pii(html_to_text(pi.get("description")))
    loc = cd.get("location") or {}
    lat = lng = None
    if loc and not cd.get("isApproxLocation"):
        lat, lng = num(loc.get("lat")), num(loc.get("lon"))
    labels = [l.get("name") for l in (pi.get("labels") or []) if l.get("type") not in ("project", "sale", "rent")]
    files = cd.get("propertyFiles") or {}
    imgs = [img_url("compound", pid, n) for n in (files.get("images") or [])[:8]]
    units = ((pp.get("compoundUnitListDetails") or {}).get("properties")) or []
    ptypes, utypes, areas = set(), set(), []
    for u in units:
        ui = u.get("propertyInfo") or {}
        if ui.get("propertySubType"):
            ptypes.add(ui["propertySubType"])
        a = {x.get("key"): x.get("value") for x in (u.get("attributes") or []) if isinstance(x, dict)}
        b = intnum(a.get("noOfBedrooms"))
        if b:
            utypes.add(f"{b} BR")
        ar = num(a.get("builtUpArea")) or num(a.get("landArea"))
        if ar:
            areas.append(ar)
    amen = [a.get("name") or a.get("title") for a in ((pp.get("compoundAmenitiesDetails") or {}).get("amenities") or []) if isinstance(a, dict)]
    handover = None
    if pi.get("completionDate"):
        m = re.match(r"(\d{4})", str(pi["completionDate"]))
        handover = int(m.group(1)) if m else None
    pmin, pmax = num(pi.get("salePriceMin")), num(pi.get("salePriceMax"))
    developer = None
    for k in ("developerName", "developer", "builderName"):
        if isinstance(cd.get(k), str):
            developer = cd[k]
    return Project(
        id=f"wasalt-p-{pid}", slug=pi.get("slug") or str(pid),
        name_en=title if title and not is_arabic(title) else None,
        name_ar=title if is_arabic(title) else None,
        site="Wasalt", developer=developer, city=canon_city(pi.get("city")), country="Saudi Arabia", lat=lat, lng=lng,
        property_types=sorted(ptypes), unit_types=sorted(utypes, key=lambda s: int(s.split()[0])),
        price_from_amount=pmin, price_from_currency=pi.get("currencyType") if pmin else None, price_to_amount=pmax,
        area_min_m2=min(areas) if areas else None, area_max_m2=max(areas) if areas else None,
        amenities=[a for a in amen if a], status=", ".join(labels) or None, handover_year=handover,
        description_en=desc if desc and not is_arabic(desc) else None,
        description_ar=desc if desc and is_arabic(desc) else None,
        image_urls=imgs, source_url=url, scraped_at=scraped_at,
    ), [u.get("id") for u in units if u.get("id")], (pi.get("district"))


def visible_text(body: str) -> tuple[str, str]:
    tree = HTMLParser(body)
    title = (tree.css_first("title").text(strip=True) if tree.css_first("title") else "")
    for sel in ("script", "style", "noscript", "header", "footer", "nav", "svg", "form"):
        for n in tree.css(sel):
            n.decompose()
    root = None
    for sel in (".entry-content", "main", "article"):
        n = tree.css_first(sel)
        if n is not None and len(n.text(strip=True)) > 400:
            root = n
            break
    root = root or tree.body
    if root is None:
        return title, ""
    # keep headings as markdown-ish markers so chunking can split on them
    for lvl in range(1, 4):
        for h in root.css(f"h{lvl}"):
            h.replace_with(f"\n{'#' * lvl} {h.text(strip=True)}\n")
    txt = root.text(separator="\n")
    lines = [re.sub(r"\s+", " ", l).strip() for l in txt.split("\n")]
    lines = [l for l in lines if l and len(l) > 1]
    # drop exact duplicate lines (menus repeated)
    seen, out = set(), []
    for l in lines:
        if l in seen and not l.startswith("#"):
            continue
        seen.add(l)
        out.append(l)
    return title, "\n".join(out)


def page_type_for(url: str) -> str:
    p = urlparse(url)
    path = p.path
    if p.netloc.startswith("auction."):
        return "auctions"
    if p.netloc.startswith("blog."):
        return "guide" if path.strip("/") not in ("en", "ar") else "guides_index"
    if "/corporate" in path:
        return "about"
    if "/s/terms" in path or "privacy" in path:
        return "terms"
    if "daily-rental" in path:
        return "services"
    if path.rstrip("/") in ("/en", "/ar"):
        return "home"
    if "-for-sale-in-" in path or "-for-rent-in-" in path:
        return "city_guide"
    return "static"


# ---------------------------------------------------------------- chunking
def words(s: str) -> list[str]:
    return s.split()


def window_chunks(text: str, size_tokens: int, overlap: float = 0.0) -> list[str]:
    # ~1.3 tokens per English word; Arabic words tokenise heavier (~2), use 1.6 average
    size_w = max(50, int(size_tokens / 1.5))
    step = max(1, int(size_w * (1 - overlap)))
    out = []
    # split on headings first
    sections = re.split(r"\n(?=#{1,3} )", text)
    for sec in sections:
        w = words(sec)
        if not w:
            continue
        if len(w) <= size_w:
            out.append(" ".join(w))
            continue
        for i in range(0, len(w), step):
            piece = w[i:i + size_w]
            if len(piece) < 20 and out:
                break
            out.append(" ".join(piece))
            if i + size_w >= len(w):
                break
    return out


def fmt_money(a, c):
    if a is None:
        return "Not published"
    return f"{a:,.0f} {c or ''}".strip()


def project_fact_text(p: Project) -> tuple[str, str]:
    name = p.name_en or p.name_ar
    en = (f"Project: {name}. Site: {p.site}. City: {p.city or 'Not published'}, {p.country or ''}. "
          f"Price from: {fmt_money(p.price_from_amount, p.price_from_currency)}"
          + (f" to {fmt_money(p.price_to_amount, p.price_from_currency)}" if p.price_to_amount else "") + ". "
          f"Property types: {', '.join(p.property_types) or 'Not published'}. "
          f"Unit types: {', '.join(p.unit_types) or 'Not published'}. "
          f"Status: {p.status or 'Not published'}. "
          f"Handover year: {p.handover_year or 'Not published'}.")
    if p.area_min_m2:
        en += f" Unit areas: {p.area_min_m2:g}-{p.area_max_m2:g} m2."
    ar = (f"المشروع: {name}. الموقع: {p.site}. المدينة: {p.city or 'غير منشور'}. "
          f"السعر يبدأ من: {fmt_money(p.price_from_amount, p.price_from_currency) if p.price_from_amount else 'غير منشور'}. "
          f"أنواع العقارات: {', '.join(p.property_types) or 'غير منشور'}. الحالة: {p.status or 'غير منشور'}.")
    return en, ar


def chunk_header(name_en, name_ar, city, country, site, section) -> str:
    """Contextual header '{name_en} | {name_ar} | {city}, {country} | {site} | {section}: ' (empty parts omitted).
    The only ': ' in the header is the final one, so a consumer can strip the header up to the first ': '."""
    loc = ", ".join(x for x in (city, country) if x)
    parts = [re.sub(r"\s*:\s*", " - ", str(x)).replace("|", "/").strip() for x in (name_en, name_ar, loc, site, section) if x]
    return " | ".join(p for p in parts if p) + ": "


def dg_fact_source(p: Project, x: dict) -> str:
    """URL the DarGlobal fact chunk cites: the DarGlobal page its name/location came from (a row enriched from the RNS
    carries the RNS as source_url), or the primary third-party source for a third-party-only row."""
    return x.get("dg_source_url") or p.source_url


def dg_fact_text(p: Project, x: dict) -> tuple[str, str]:
    """Fact chunk for a DarGlobal project, built only from structured fields and published strings."""
    name = p.name_en or p.name_ar
    loc_pub = x.get("location_published") or ", ".join(v for v in (p.city, p.country) if v) or "Not published"
    country_ar = dgm.COUNTRY_AR.get(p.country or "", p.country or "البلد غير مذكور")
    tp = x.get("thirdparty")
    tp_en = (f"Further facts about {name} come from {len(tp['sources'])} third-party public source(s) "
             f"({', '.join(tp['source_tags'])}); each is in its own source chunk with its URL and date, and the list "
             f"is in the 'Public sources' chunk. ") if tp else ""
    tp_ar = "تتوفر معلومات إضافية من مصادر عامة خارجية، لكل منها رابطه وتاريخه. " if tp else ""
    if x.get("dg_source_url", p.source_url) is None and tp:   # third-party-only row: no DarGlobal entry by this name
        en = (f"Project: {name}. Developer: DarGlobal. Location (as reported by third-party sources): "
              f"{', '.join(v for v in (p.city, p.country) if v) or 'Not published'}. "
              + (f"Brand partner: {p.brand_partner}. " if p.brand_partner else "")
              + "Not listed under this name on the DarGlobal projects page collected on 2026-11-19"
              + (f"; related DarGlobal listings: {', '.join(x['related'])}. " if x.get("related") else ". ")
              + tp_en
              + (f"Status (Dar Global PLC RNS): {p.status}. " if p.status else "")
              + (f"Expected completion year (RNS): {p.handover_year}. " if p.handover_year else "")
              + "Price: not published by DarGlobal.")
        ar = (f"المشروع: {name}. المطور: دار جلوبال. الموقع حسب مصادر خارجية: {p.city or 'غير منشور'}، {country_ar}. "
              + tp_ar + "السعر: غير منشور من دار جلوبال.")
        return en, ar
    if x.get("dg_source_url", p.source_url) == dgm.INDEX_URL:
        if x.get("country_note"):
            cn = f" ({x['country_note']})"
        else:
            cn = "" if p.country else " (country not stated)"
        en = (f"Project: {name}. Developer: DarGlobal. Location (as published): {loc_pub}{cn}. "
              + (f"Brand partner: {p.brand_partner}. " if p.brand_partner else "")
              + (f"Card text: {x['card_caption']}. " if x.get("card_caption") else "")
              + "Listed on the DarGlobal projects page (darglobal.co.uk/projects); detail page not collected. "
              + tp_en
              + "Price: not published by DarGlobal.")
        ar = (f"المشروع: {name}. المطور: دار جلوبال. الموقع: {p.city or 'غير منشور'}، {country_ar}. "
              "مدرج في صفحة مشاريع دار جلوبال؛ لم تُجمع صفحة التفاصيل. " + tp_ar + "السعر: غير منشور من دار جلوبال.")
        return en, ar
    area = x.get("area_published") or ""
    if x.get("area_text_sqm"):
        area = (area + "; " if area else "") + f"text: {x['area_text_sqm']}"
    en = (f"Project: {name}. Developer: DarGlobal. "
          + (f"Brand partner: {p.brand_partner}. " if p.brand_partner else "")
          + f"Location: {loc_pub}. "
          f"Property type: {', '.join(p.property_types) or 'Not published'}. "
          f"Status: {p.status or 'Not published'}. "
          f"Units: {', '.join(p.unit_types) or 'Not published'}. "
          f"Area as published: {area or 'Not published'}"
          + (f" (unit areas {p.area_min_m2:g}-{p.area_max_m2:g} m2)" if p.area_min_m2 else "") + ". "
          + (f"Handover year: {p.handover_year} (as stated on the page). " if p.handover_year else "")
          + (f"Featuring: {x['featuring']}. " if x.get("featuring") else "")
          + "Price: not published by DarGlobal.")
    ar = (f"المشروع: {name}. المطور: دار جلوبال. الموقع: {p.city or 'غير منشور'}، {country_ar}. "
          f"نوع العقار: {', '.join(p.property_types) or 'غير منشور'}. الحالة: {p.status or 'غير منشور'}. "
          + (f"المساحات: {p.area_min_m2:g}-{p.area_max_m2:g} م². " if p.area_min_m2 else "")
          + (f"سنة التسليم: {p.handover_year}. " if p.handover_year else "")
          + "السعر: غير منشور من دار جلوبال.")
    return en, ar


def listing_fact_text(l: Listing, rent_freq: str | None) -> str:
    price = fmt_money(l.price_amount, l.price_currency)
    if l.listing_type == "rent" and l.price_amount and rent_freq:
        price += f" per {rent_freq.replace('ly', '').replace('dai', 'day')} (as listed: {rent_freq})"
    return (f"Listing: {l.title}. Site: Wasalt. For: {'sale' if l.listing_type == 'buy' else 'rent'}. "
            f"Type: {l.property_type or 'Not published'}. Price: {price}. "
            f"Bedrooms: {l.beds if l.beds is not None else 'Not published'}. "
            f"Bathrooms: {l.baths if l.baths is not None else 'Not published'}. "
            f"Area: {f'{l.area_m2:g} m2' if l.area_m2 else 'Not published'}. "
            f"Location: {', '.join(x for x in [l.district, l.city] if x) or 'Not published'}, Saudi Arabia.")


# ---------------------------------------------------------------- build
def build():
    projects: dict[str, Project] = {}
    listings: dict[str, Listing] = {}
    rent_freq: dict[str, str] = {}
    pages: dict[str, Page] = {}
    unit_to_project: dict[str, str] = {}
    gaps, srp_counts = [], {}
    text_seen = set()

    snaps = sorted(iter_snapshots(), key=lambda x: x[0]["url"])
    for meta, body_p in snaps:
        url, final = meta["url"], meta.get("final_url") or meta["url"]
        host = urlparse(url).netloc
        if meta["status"] != 200:
            gaps.append(f"HTTP {meta['status']} {url}")
            continue
        if "html" not in (meta.get("content_type") or ""):
            continue
        if "/search" in urlparse(final).path:
            gaps.append(f"redirected to internal search (inactive project?), not parsed: {url}")
            continue
        body = body_p.read_text(encoding="utf-8", errors="ignore")
        sa = meta["fetched_at"]
        if "darglobal" in host:
            if "_Incapsula_Resource" in body:
                gaps.append(f"DarGlobal bot challenge (not parsed) {url}")
            continue
        nd = next_data(body)
        pp = (nd or {}).get("props", {}).get("pageProps", {}) if nd else {}
        page = (nd or {}).get("page")
        if page == "/project/[slug]/[projectId]":
            r = project_from_wasalt(pp, final, sa)
            if r:
                proj, unit_ids, _ = r
                projects[proj.id] = proj
                for uid in unit_ids:
                    unit_to_project[str(uid)] = proj.id
                for u in ((pp.get("compoundUnitListDetails") or {}).get("properties")) or []:
                    lr = listing_from_wasalt(u, sa)
                    if lr:
                        l, rf = lr
                        l.project_ref = proj.id
                        listings[l.id] = l
                        if rf:
                            rent_freq[l.id] = rf
            else:
                gaps.append(f"project page without compound data {url}")
            continue
        if page == "/[slug]" and isinstance(pp.get("searchResult"), dict):
            sr = pp["searchResult"]
            srp_counts[final] = {"site_count": sr.get("count"), "on_page": len(sr.get("properties") or []),
                                 "projects": sr.get("unitCount"), "auctions": sr.get("aucCount")}
            flat = []
            for p in sr.get("properties") or []:
                flat.extend(p if isinstance(p, list) else [p])
            for p in flat:
                if not isinstance(p, dict):
                    continue
                lr = listing_from_wasalt(p, sa)
                if lr:
                    l, rf = lr
                    listings.setdefault(l.id, l)
                    if rf:
                        rent_freq[l.id] = rf
            # SEO city guide text
            para = html_to_text(pp.get("para") or "")
            if para and len(para) > 200:
                para = strip_pii(para)
                h = hashlib.md5(para.encode()).hexdigest()
                if h not in text_seen:
                    text_seen.add(h)
                    title = (pp.get("metaData") or {}).get("h1tag") or final
                    pid = "wasalt-pg-" + hashlib.sha1(final.encode()).hexdigest()[:10]
                    pages[pid] = Page(id=pid, site="Wasalt", page_type="city_guide", title=f"{title} — area guide",
                                      text=para, lang="en", source_url=final, scraped_at=sa)
            continue
        if page and page.startswith("/property/"):
            continue  # PDP probe only
        if page == "/404":
            gaps.append(f"404 page {url}")
            continue
        # static pages (Next or WordPress/other)
        title, text = visible_text(body)
        text = strip_pii(text) or ""
        if len(text) < 150:
            gaps.append(f"static page with too little SSR text ({len(text)} chars) {url}")
            continue
        h = hashlib.md5(text.encode()).hexdigest()
        if h in text_seen:
            gaps.append(f"duplicate content (redirect/alias) {url} -> {final}")
            continue
        text_seen.add(h)
        h1 = re.search(r"^# (.+)$", text, re.M)
        if h1 and (not title or title.strip() in ("Wasalt Real Estate Services", "وصلت للخدمات العقارية")):
            title = h1.group(1).strip()
        lang = "ar" if ("/ar" in urlparse(final).path[:4] or is_arabic(text)) else "en"
        pid = "wasalt-pg-" + hashlib.sha1(final.encode()).hexdigest()[:10]
        pages[pid] = Page(id=pid, site="Wasalt", page_type=page_type_for(final), title=title or final,
                          text=text, lang=lang, source_url=final, scraped_at=sa)

    # link standalone listings to projects when the unit list says so
    for lid, l in listings.items():
        raw = lid.removeprefix("wasalt-l-")
        if not l.project_ref and raw in unit_to_project:
            l.project_ref = unit_to_project[raw]

    # DarGlobal: the public sitemap (fetched before the block) gives official URLs only, no facts.
    dg_sm = None
    for meta, body_p in snaps:
        if meta["url"] == "https://darglobal.co.uk/sitemap.xml" and meta["status"] == 200:
            dg_sm = (meta, body_p.read_text(encoding="utf-8", errors="ignore"))
    if dg_sm:
        meta, t = dg_sm
        locs = re.findall(r"<loc>(.*?)</loc>", t)
        keep = [l for l in locs if not any(x in l for x in ("/blog/", "/press/", "careers", "internship", "broker",
                                                              "become-an-agent", "pay-online", "thank-you", "success",
                                                              "landingpage", "new-home-page"))]
        keep = list(dict.fromkeys(keep))
        text = ("DarGlobal official website — list of public page URLs taken from darglobal.co.uk/sitemap.xml. "
                "The automated scraper could not read these pages (the site served an automated-client challenge); "
                "a small set of project pages was later collected manually by the owner in a normal browser and is "
                "stored as DarGlobal project records. Visit the official pages for details.\n" + "\n".join(keep))
        pid = "darglobal-pg-sitemap"
        pages[pid] = Page(id=pid, site="DarGlobal", page_type="sitemap_index",
                          title="DarGlobal official pages (URL index only)", text=text, lang="en",
                          source_url="https://darglobal.co.uk/sitemap.xml", scraped_at=meta["fetched_at"])

        if CONTACT_DG in keep:
            pages["darglobal-pg-contact"] = Page(
                id="darglobal-pg-contact", site="DarGlobal", page_type="contact", title="DarGlobal official contact page",
                text="Official DarGlobal contact page", lang="en", source_url=CONTACT_DG, scraped_at=meta["fetched_at"])
        else:
            gaps.append("DarGlobal contact URL not in sitemap snapshot; no contact page row")

    # Wasalt: the official corporate page is in the snapshots (no contact-us URL exists in the static sitemap).
    corp = next((pg for pg in pages.values() if pg.site == "Wasalt" and pg.source_url == CONTACT_WASALT), None)
    if corp:
        pages["wasalt-pg-contact"] = Page(
            id="wasalt-pg-contact", site="Wasalt", page_type="contact", title="Wasalt official corporate / contact page",
            text="Official Wasalt corporate page (company information and official contact channels)", lang="en",
            source_url=CONTACT_WASALT, scraped_at=corp.scraped_at)
    else:
        gaps.append(f"Wasalt corporate page not in snapshots ({CONTACT_WASALT}); no contact page row")

    # DarGlobal projects from the owner's manual browser collection (offline parse).
    dg = dgm.load()
    tp_extra, tp_report = dgt.merge(dg["projects"])
    dg["report"]["thirdparty"] = tp_report
    dg_extra: dict[str, dict] = {}
    for pid, r in sorted(dg["projects"].items()):
        desc = strip_pii(r.get("description_en"))
        proj = Project(
            id=pid, slug=r["slug"], name_en=r["name_en"], name_ar=None, site="DarGlobal", developer="DarGlobal",
            brand_partner=r.get("brand_partner"), city=r.get("city"), country=r.get("country"),
            lat=r.get("lat"), lng=r.get("lng"), property_types=r.get("property_types") or [],
            unit_types=r.get("unit_types") or [], price_from_amount=None, price_from_currency=None, price_to_amount=None,
            area_min_m2=r.get("area_min_m2"), area_max_m2=r.get("area_max_m2"), amenities=r.get("amenities") or [],
            status=r.get("status"), handover_year=r.get("handover_year"), description_en=desc or None,
            description_ar=None, image_urls=(r.get("image_urls") or [])[:6], source_url=r["source_url"],
            scraped_at=r["scraped_at"])
        projects[pid] = proj
        dg_extra[pid] = {"location_published": r.get("location_published"), "card_caption": r.get("card_caption"),
                         "area_published": r.get("area_published"), "area_text_sqm": r.get("area_text_sqm"),
                         "featuring": r.get("featuring"), "dg_source_url": r.get("dg_source_url", r["source_url"]),
                         "sections": [(sec, strip_pii(t)) for sec, t in r.get("sections") or [] if strip_pii(t)]}
        if pid in tp_extra:
            tpx = tp_extra[pid]
            dg_extra[pid]["thirdparty"] = tpx
            corr = next((c for c in tp_report["corrections"] if c["id"] == pid and c["column"] == "country"), None)
            if corr:
                dg_extra[pid]["country_note"] = f"country not stated by DarGlobal; {corr['to']} per third-party sources"
            if r.get("thirdparty_only"):
                dg_extra[pid]["related"] = sorted({
                    dg["projects"][c["to"]]["name_en"] for c in tp_report["cross_attached"]
                    if c["from"] in tpx["files"] and c["to"] in dg["projects"]})
            # per-project page listing every public source, so the bot can cite the list
            own = r.get("dg_source_url")
            own_txt = ("darglobal.co.uk/projects index (name and location only; detail page not collected)"
                       if own == dgm.INDEX_URL else (own or "none collected under this name"))
            lines = [f"# {r['name_en']} - public sources",
                     f"Third-party public sources used for the DarGlobal project {r['name_en']}"
                     + (f" ({', '.join(v for v in (r.get('city'), r.get('country')) if v)})" if r.get("city") else "")
                     + ". darglobal.co.uk was not fetched for these facts. Wire-hosted Dar Global releases are "
                       "company statements; the RNS is Dar Global PLC's regulatory announcement (FY2025 results, "
                       "RNS 1301W), read from the ticker.app mirror.",
                     f"DarGlobal's own listing: {own_txt}."]
            lines += [f"- {s}" for s in tpx["source_list"]]
            if corr:
                lines.append(f"Correction: country set to {corr['to']} ({corr['why']}).")
            gid = f"darglobal-pg-sources-{r['slug']}"
            pages[gid] = Page(id=gid, site="DarGlobal", page_type="project_sources",
                              title=f"{r['name_en']} - public sources", text="\n".join(lines), lang="en",
                              source_url=tpx["primary_source"], scraped_at=tpx["collected_at"])
    return projects, listings, rent_freq, pages, gaps, srp_counts, dg_extra, dg["report"]


def completeness(rows: list[dict], fields: list[str]) -> dict:
    n = len(rows) or 1
    out = {}
    for f in fields:
        c = 0
        for r in rows:
            v = r.get(f)
            if v not in (None, "", [], "[]"):
                c += 1
        out[f] = round(c / n, 3)
    return out


def write_db(path: Path, projects, listings, rent_freq, pages, version_tag: str | None = None,
             dg_extra: dict | None = None):
    dg_extra = dg_extra or {}
    final_path, path = path, path.with_name(path.name + ".building")
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    chunks = []
    for p in projects:
        d = p.model_dump()
        d["content_hash"] = chash(d)
        for k in ("property_types", "unit_types", "amenities", "image_urls"):
            d[k] = json.dumps(d[k], ensure_ascii=False)
        con.execute(f"INSERT INTO projects({','.join(d)}) VALUES({','.join('?' * len(d))})", list(d.values()))
        x = dg_extra.get(p.id, {})
        en, ar = dg_fact_text(p, x) if p.site == "DarGlobal" else project_fact_text(p)
        fsrc = dg_fact_source(p, x) if p.site == "DarGlobal" else p.source_url
        chunks.append(dict(id=f"{p.id}#fact-en", entity_type="project", entity_id=p.id, site=p.site, lang="en", text=en,
                           city=p.city, country=p.country, source_url=fsrc, scraped_at=p.scraped_at))
        chunks.append(dict(id=f"{p.id}#fact-ar", entity_type="project", entity_id=p.id, site=p.site, lang="ar", text=ar,
                           city=p.city, country=p.country, source_url=fsrc, scraped_at=p.scraped_at))
        tp = x.get("thirdparty")
        if tp:  # third-party facts: one chunk group per source, each citing that source's own URL
            for i, sc in enumerate(tp["source_chunks"]):
                hdr = chunk_header(p.name_en, p.name_ar, p.city, p.country, p.site,
                                   f"Third-party source - {sc['short']}, {dgt.human_date(sc['source_date'])}")
                for j, c in enumerate(window_chunks(sc["text"], 300, 0.0)):
                    chunks.append(dict(id=f"{p.id}#tp-en-{i}-{j}", entity_type="project", entity_id=p.id, site=p.site,
                                       lang="en", text=hdr + c, city=p.city, country=p.country,
                                       source_url=sc["source_url"], scraped_at=sc["scraped_at"]))
            if tp["figures"]:
                hdr = chunk_header(p.name_en, p.name_ar, p.city, p.country, p.site, "Figures by source and date")
                for j, c in enumerate(window_chunks(tp["figures"]["text"], 300, 0.0)):
                    chunks.append(dict(id=f"{p.id}#tp-figures-en-{j}", entity_type="project", entity_id=p.id,
                                       site=p.site, lang="en", text=hdr + c, city=p.city, country=p.country,
                                       source_url=tp["figures"]["source_url"], scraped_at=tp["collected_at"]))
            hdr = chunk_header(p.name_en, p.name_ar, p.city, p.country, p.site, "Public sources")
            body = (f"Public sources for {p.name_en} (third-party; darglobal.co.uk was not fetched for these): "
                    + " ; ".join(tp["source_list"]) + ".")
            for j, c in enumerate(window_chunks(body, 300, 0.0)):
                chunks.append(dict(id=f"{p.id}#tp-sources-en-{j}", entity_type="project", entity_id=p.id, site=p.site,
                                   lang="en", text=hdr + c, city=p.city, country=p.country,
                                   source_url=tp["primary_source"], scraped_at=tp["collected_at"]))
        for lang, desc in (("en", p.description_en), ("ar", p.description_ar)):
            if desc:
                hdr = chunk_header(p.name_en, p.name_ar, p.city, p.country, p.site,
                                   "Overview" if p.site == "DarGlobal" else "Description")
                for i, c in enumerate(window_chunks(desc, 300, 0.0)):
                    chunks.append(dict(id=f"{p.id}#desc-{lang}-{i}", entity_type="project", entity_id=p.id, site=p.site,
                                       lang=lang, text=hdr + c, city=p.city, country=p.country,
                                       source_url=p.source_url, scraped_at=p.scraped_at))
        # DarGlobal page sections (key features, amenities, location, FAQ), grouped per section into ~300-token chunks
        groups: dict[str, list[str]] = {}
        for sec, t in x.get("sections") or []:
            groups.setdefault(sec, []).append(t)
        n = 0
        for sec, texts in groups.items():
            hdr = chunk_header(p.name_en, p.name_ar, p.city, p.country, p.site, sec)
            buf: list[str] = []
            for t in texts + [None]:
                if t is not None and len(" ".join(buf + [t]).split()) <= 200:
                    buf.append(t)
                    continue
                if buf:
                    for c in window_chunks(" ".join(buf), 300, 0.0):
                        chunks.append(dict(id=f"{p.id}#sec-en-{n}", entity_type="project", entity_id=p.id, site=p.site,
                                           lang="en", text=hdr + c, city=p.city, country=p.country,
                                           source_url=p.source_url, scraped_at=p.scraped_at))
                        n += 1
                buf = [t] if t is not None else []
    for l in listings:
        d = l.model_dump()
        d["content_hash"] = chash(d)
        d["image_urls"] = json.dumps(d["image_urls"], ensure_ascii=False)
        con.execute(f"INSERT INTO listings({','.join(d)}) VALUES({','.join('?' * len(d))})", list(d.values()))
        chunks.append(dict(id=f"{l.id}#fact", entity_type="listing", entity_id=l.id, site="Wasalt", lang="en",
                           text=listing_fact_text(l, rent_freq.get(l.id)), city=l.city, country="Saudi Arabia",
                           source_url=l.source_url, scraped_at=l.scraped_at))
    for pg in pages:
        d = pg.model_dump()
        con.execute(f"INSERT INTO pages({','.join(d)}) VALUES({','.join('?' * len(d))})", list(d.values()))
        pcountry = "Saudi Arabia" if pg.site == "Wasalt" else None
        hdr = chunk_header(pg.title, None, None, pcountry, pg.site, pg.page_type)
        for i, c in enumerate(window_chunks(pg.text, 400, 0.15)):
            chunks.append(dict(id=f"{pg.id}#{i}", entity_type="page", entity_id=pg.id, site=pg.site, lang=pg.lang,
                               text=hdr + c, city=None, country=pcountry,
                               source_url=pg.source_url, scraped_at=pg.scraped_at))
    for c in chunks:
        con.execute(f"INSERT INTO chunks({','.join(c)}) VALUES({','.join('?' * len(c))})", list(c.values()))

    proj_rows = [p.model_dump() for p in projects]
    list_rows = [l.model_dump() for l in listings]
    comp = {
        "projects": completeness(proj_rows, ["name_en", "name_ar", "city", "country", "source_url", "price_from_amount",
                                             "status", "handover_year", "lat", "description_en", "description_ar",
                                             "image_urls", "property_types", "unit_types", "developer", "amenities",
                                             "area_min_m2"]),
        "listings": completeness(list_rows, ["title", "city", "district", "source_url", "price_amount", "beds", "baths",
                                             "area_m2", "property_type", "image_urls", "project_ref"]),
    }
    comp["projects"]["name_any"] = completeness([{"n": r["name_en"] or r["name_ar"]} for r in proj_rows], ["n"])["n"]
    pfields = ["name_en", "name_ar", "city", "country", "source_url", "price_from_amount", "status", "handover_year",
               "lat", "description_en", "description_ar", "image_urls", "property_types", "unit_types", "developer",
               "amenities", "area_min_m2"]
    comp["by_site"] = {}
    for site in ("DarGlobal", "Wasalt"):
        rows = [r for r in proj_rows if r["site"] == site]
        comp["by_site"][site] = {"projects_n": len(rows), "projects": completeness(rows, pfields)}
        if site == "DarGlobal":
            lvl = {p.id: dg_level(p, dg_extra) for p in projects if p.site == "DarGlobal"}
            det = [r for r in rows if lvl[r["id"]] == "page"]
            comp["by_site"][site]["projects_detail_page_n"] = len(det)
            comp["by_site"][site]["projects_detail_page"] = completeness(det, pfields)
            tpr = [r for r in rows if dg_extra.get(r["id"], {}).get("thirdparty")]
            comp["by_site"][site]["projects_with_thirdparty_facts_n"] = len(tpr)
            comp["by_site"][site]["projects_with_thirdparty_facts"] = completeness(tpr, pfields)
            comp["by_site"][site]["projects_thirdparty_only_n"] = sum(1 for v in lvl.values() if v == "thirdparty_only")
        else:
            comp["by_site"][site]["listings_n"] = len(list_rows)
    all_ts = [r["scraped_at"] for r in proj_rows + list_rows] + [p.scraped_at for p in pages]
    counts = {"projects": len(projects), "listings": len(listings), "pages": len(pages), "chunks": len(chunks),
              "projects_by_site": {s: sum(1 for p in projects if p.site == s) for s in ("DarGlobal", "Wasalt")},
              "listings_by_type": {t: sum(1 for l in listings if l.listing_type == t) for t in ("buy", "rent")},
              "projects_detail_by_site": {"DarGlobal": {
                  "page": sum(1 for p in projects if p.site == "DarGlobal" and dg_level(p, dg_extra) == "page"),
                  "index": sum(1 for p in projects if p.site == "DarGlobal" and dg_level(p, dg_extra) == "index"),
                  "thirdparty_only": sum(1 for p in projects if p.site == "DarGlobal"
                                         and dg_level(p, dg_extra) == "thirdparty_only"),
                  "with_thirdparty_facts": sum(1 for p in projects if p.site == "DarGlobal"
                                               and dg_extra.get(p.id, {}).get("thirdparty")),
                  "with_any_detail_facts": sum(1 for p in projects if p.site == "DarGlobal"
                                               and (dg_level(p, dg_extra) == "page"
                                                    or dg_extra.get(p.id, {}).get("thirdparty")))}},
              "projects_by_site_country": {s: dict(sorted(
                  {c: sum(1 for p in projects if p.site == s and (p.country or "unresolved") == c)
                   for c in {p.country or "unresolved" for p in projects if p.site == s}}.items()))
                  for s in ("DarGlobal", "Wasalt")},
              "pages_by_type": {t: sum(1 for g in pages if g.page_type == t) for t in sorted({g.page_type for g in pages})}}
    h = hashlib.sha256(json.dumps([r.get("content_hash") for r in []] + sorted(c["id"] + c["text"] for c in chunks),
                                  ensure_ascii=False).encode()).hexdigest()[:8]
    version = version_tag or f"{max(all_ts)[:10].replace('-', '') if all_ts else 'empty'}-{h}"
    con.execute("INSERT INTO dataset_meta VALUES(?,?,?,?,?)",
                (version, min(all_ts) if all_ts else None, max(all_ts) if all_ts else None,
                 json.dumps(counts), json.dumps(comp)))
    con.commit()
    con.close()
    publish_db(path, final_path)
    return version, counts, comp, chunks


def dg_level(p: Project, dg_extra: dict) -> str:
    """'page' = own DarGlobal page collected; 'index' = DarGlobal projects index only (possibly enriched with
    third-party facts); 'thirdparty_only' = no DarGlobal entry by this name, third-party sources only."""
    src = dg_extra.get(p.id, {}).get("dg_source_url", p.source_url)
    if src is None:
        return "thirdparty_only"
    return "index" if src == dgm.INDEX_URL else "page"


def publish_db(tmp: Path, final: Path) -> None:
    """Move the freshly built DB into place. On Windows a running dev server may hold the target open, so fall back
    to SQLite's online backup API, which replaces the target's content in place."""
    try:
        if final.exists():
            final.unlink()
        tmp.replace(final)
        return
    except PermissionError:
        pass
    src, dst = sqlite3.connect(tmp), sqlite3.connect(final, timeout=30)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()
    tmp.unlink()


def pii_scan(db: Path) -> list[str]:
    con = sqlite3.connect(db)
    hits = []
    phone = re.compile(r"(?<![\d/._-])(?:\+?966|00966|0)?5\d{8}(?!\d)|(?<![\d/._-])\+\d{9,14}(?!\d)|(?<![\d/._-])0\d{9}(?!\d)")
    for table, cols in (("projects", ["name_en", "name_ar", "developer", "description_en", "description_ar", "status"]),
                        ("listings", ["title", "district"]), ("pages", ["title", "text"]), ("chunks", ["text"])):
        for row in con.execute(f"SELECT id, {', '.join(cols)} FROM {table}"):
            for col, v in zip(cols, row[1:]):
                if not v:
                    continue
                t = str(v).translate(ARABIC_DIGITS)
                for name, rx in (("phone", phone), ("email", EMAIL_RE), ("whatsapp", re.compile(r"wa\.me/|whatsapp\s*[:+]?\s*\d", re.I))):
                    m = rx.search(t)
                    if m:
                        hits.append(f"{table}.{col} id={row[0]} {name}: …{t[max(0, m.start() - 20):m.end() + 5]!r}")
    # schema check: no agent/owner columns
    for table in ("projects", "listings"):
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
        for c in cols:
            if any(x in c for x in ("agent", "owner", "phone", "email", "whatsapp")):
                hits.append(f"schema column {table}.{c}")
    con.close()
    return hits


def main():
    projects, listings, rent_freq, pages, gaps, srp_counts, dg_extra, dg_report = build()
    P, L, G = list(projects.values()), list(listings.values()), list(pages.values())
    version, counts, comp, chunks = write_db(DATA / "concierge.sqlite", P, L, rent_freq, G, dg_extra=dg_extra)
    hits = pii_scan(DATA / "concierge.sqlite")
    # mini fixture: projects with most fields, their listings first, plus pages of different types
    Ps = sorted((p for p in P if p.site == "Wasalt"),
                key=lambda p: (p.price_from_amount is None, p.description_en is None and p.description_ar is None, p.id))[:10]
    # + 3 DarGlobal: 2 with a collected detail page, 1 index-only in Oman
    dgp = sorted((p for p in P if p.site == "DarGlobal"), key=lambda p: p.id)
    Ps += [p for p in dgp if dg_level(p, dg_extra) == "page"][:2]
    Ps += [p for p in dgp if dg_level(p, dg_extra) == "index" and p.country == "Oman"][:1]
    pids = {p.id for p in Ps}
    Ls = [l for l in L if l.project_ref in pids][:4]
    rest = [l for l in L if l.project_ref is None]
    for t in ("buy", "rent"):
        Ls += [l for l in rest if l.listing_type == t and l.price_amount][:3 if t == "buy" else 3]
    Ls = list({l.id: l for l in Ls}.values())[:10]
    Gs, seen_t = [], set()
    contacts = [g for g in G if g.page_type == "contact"]
    for g in sorted((g for g in G if g.page_type not in ("contact", "project_sources")), key=lambda g: g.page_type):
        if g.page_type not in seen_t or len(Gs) < 10:
            if len(Gs) < 10:
                Gs.append(g)
                seen_t.add(g.page_type)
    Gs = sorted(contacts, key=lambda g: g.id) + Gs
    # the public-sources page of each DarGlobal project in the fixture
    Gs += sorted((g for g in G if g.page_type == "project_sources"
                  and any(g.id == f"darglobal-pg-sources-{p.slug}" for p in Ps)), key=lambda g: g.id)
    mversion, mcounts, _, _ = write_db(DATA / "fixtures" / "mini.sqlite", Ps, Ls, rent_freq, Gs,
                                       version_tag=f"mini-{version}", dg_extra=dg_extra)
    mini_hits = pii_scan(DATA / "fixtures" / "mini.sqlite")

    (DATA / "completeness.json").write_text(json.dumps({"dataset_version": version, "counts": counts, "completeness": comp,
                                                        "by_site": comp["by_site"]},
                                                       indent=1, ensure_ascii=False), encoding="utf-8")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    md = [f"# PII scan — {now}", "", f"Dataset: `data/concierge.sqlite` version `{version}`", "",
          "Patterns: Saudi mobile (05xxxxxxxx / +9665xxxxxxxx), any +international 9-14 digits, 10-digit 0-prefixed numbers, "
          "email addresses, wa.me / 'whatsapp <digits>'. Arabic-Indic digits normalised before matching. Also checks that no "
          "agent/owner/phone/email/whatsapp column exists in projects/listings.", "",
          f"Columns scanned: projects(name_en,name_ar,developer,description_en,description_ar,status), listings(title,district), "
          f"pages(title,text), chunks(text).", "",
          f"**Hits in concierge.sqlite: {len(hits)}**", f"**Hits in fixtures/mini.sqlite: {len(mini_hits)}**", ""]
    if hits or mini_hits:
        md += ["## Hits", ""] + [f"- {h}" for h in (hits + mini_hits)[:200]]
    md += ["", "Fields never extracted at source (by design): leadContactInfo, propertyOwner, contactDetails, ownerName, "
           "resEmployee, managedBy (person/agency names), REGA licence numbers.", "",
           "DarGlobal manual extracts: names were already replaced with '[name removed]' and phone numbers with '[phone]' "
           "at collection time; both placeholders are dropped. From JSON-LD only GeoCoordinates and amenityFeature names "
           "are read; Organization founder/person, contactPoint and address nodes are never ingested. Contact pages "
           "(page_type='contact') hold one line of text and no phone, email or WhatsApp."]
    (DATA / "PII_SCAN.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    hdr_rx = re.compile(r"^[^:]+ \| (?:DarGlobal|Wasalt) \| [^:|]+: ")
    need_hdr = [c for c in chunks if c["entity_type"] == "page" or "#desc-" in c["id"] or "#sec-" in c["id"]]
    claim_rx = re.compile(r"yield|returns|doubled", re.I)
    dg_rep = dict(dg_report)
    report = {"dataset_version": version, "counts": counts, "mini_counts": mcounts, "pii_hits": len(hits),
              "mini_pii_hits": len(mini_hits),
              "darglobal": {
                  "collection_method": dg_rep.pop("method", None),
                  "index_h3_names": sum(r["h3_names"] for r in dg_rep.get("index", [])),
                  "projects": counts["projects_by_site"]["DarGlobal"],
                  "detail_slugs": dg_rep.pop("detail_slugs", []),
                  "oman_rows": sum(1 for p in P if p.site == "DarGlobal" and p.country == "Oman"),
                  "priced_rows": sum(1 for p in P if p.site == "DarGlobal" and p.price_from_amount is not None),
                  "chunks": sum(1 for c in chunks if c["site"] == "DarGlobal"),
                  "thirdparty_chunks": sum(1 for c in chunks if "#tp-" in c["id"]),
                  "projects_by_level": {lv: sorted(p.id for p in P if p.site == "DarGlobal"
                                                   and dg_level(p, dg_extra) == lv)
                                        for lv in ("page", "index", "thirdparty_only")},
                  "projects_without_chunk": sorted(p.id for p in P if p.site == "DarGlobal"
                                                   and not any(c["entity_id"] == p.id for c in chunks)),
                  "claim_word_chunks": sum(1 for c in chunks if c["site"] == "DarGlobal" and claim_rx.search(c["text"])),
                  **dg_rep},
              "darglobal_unresolved": [
                  {**u, "resolved_by_thirdparty": next(
                      (f"country -> {c['to']} ({c['source_url']})" for c in dg_report.get("thirdparty", {})
                       .get("corrections", []) if c["id"] == u["id"]), None)}
                  for u in dg_report.get("darglobal_unresolved", [])],
              "chunk_headers": {"chunks_total": len(chunks), "chunks_needing_header": len(need_hdr),
                                "with_header": sum(1 for c in need_hdr if hdr_rx.match(c["text"])),
                                "format": "{name_en} | {name_ar} | {city}, {country} | {site} | {section}: "},
              "contact_pages": [g.source_url for g in G if g.page_type == "contact"],
              "srp_site_counts": srp_counts, "gaps": gaps}
    (DATA / "build_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("srp_site_counts",)}, indent=1, ensure_ascii=False))
    return 0 if not hits and not mini_hits else 1


if __name__ == "__main__":
    sys.exit(main())
