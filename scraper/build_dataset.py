"""Parse saved snapshots -> data/concierge.sqlite (SPEC section 7). NO network access.

    python scraper/build_dataset.py

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

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
SNAP = ROOT / "snapshots"
DATA = REPO / "data"
DATA.mkdir(exist_ok=True)
(DATA / "fixtures").mkdir(exist_ok=True)

IMG_BASE = "https://imagedelivery.net/1DNKFJPRaeUdy_j8F7HT3w/production"

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
                "Page contents were NOT collected (the site served an automated-client challenge), so no project facts "
                "are available here; visit the official pages for details.\n" + "\n".join(keep))
        pid = "darglobal-pg-sitemap"
        pages[pid] = Page(id=pid, site="DarGlobal", page_type="sitemap_index",
                          title="DarGlobal official pages (URL index only)", text=text, lang="en",
                          source_url="https://darglobal.co.uk/sitemap.xml", scraped_at=meta["fetched_at"])

    return projects, listings, rent_freq, pages, gaps, srp_counts


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


def write_db(path: Path, projects, listings, rent_freq, pages, version_tag: str | None = None):
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
        en, ar = project_fact_text(p)
        chunks.append(dict(id=f"{p.id}#fact-en", entity_type="project", entity_id=p.id, site=p.site, lang="en", text=en,
                           city=p.city, country=p.country, source_url=p.source_url, scraped_at=p.scraped_at))
        chunks.append(dict(id=f"{p.id}#fact-ar", entity_type="project", entity_id=p.id, site=p.site, lang="ar", text=ar,
                           city=p.city, country=p.country, source_url=p.source_url, scraped_at=p.scraped_at))
        for lang, desc in (("en", p.description_en), ("ar", p.description_ar)):
            if desc:
                name = p.name_en or p.name_ar
                for i, c in enumerate(window_chunks(desc, 300, 0.0)):
                    chunks.append(dict(id=f"{p.id}#desc-{lang}-{i}", entity_type="project", entity_id=p.id, site=p.site,
                                       lang=lang, text=f"{name}: {c}", city=p.city, country=p.country,
                                       source_url=p.source_url, scraped_at=p.scraped_at))
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
        for i, c in enumerate(window_chunks(pg.text, 400, 0.15)):
            chunks.append(dict(id=f"{pg.id}#{i}", entity_type="page", entity_id=pg.id, site=pg.site, lang=pg.lang,
                               text=f"{pg.title}: {c}" if i else c if c.startswith(pg.title) else f"{pg.title}: {c}",
                               city=None, country="Saudi Arabia" if pg.site == "Wasalt" else None,
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
    all_ts = [r["scraped_at"] for r in proj_rows + list_rows] + [p.scraped_at for p in pages]
    counts = {"projects": len(projects), "listings": len(listings), "pages": len(pages), "chunks": len(chunks),
              "projects_by_site": {s: sum(1 for p in projects if p.site == s) for s in ("DarGlobal", "Wasalt")},
              "listings_by_type": {t: sum(1 for l in listings if l.listing_type == t) for t in ("buy", "rent")}}
    h = hashlib.sha256(json.dumps([r.get("content_hash") for r in []] + sorted(c["id"] + c["text"] for c in chunks),
                                  ensure_ascii=False).encode()).hexdigest()[:8]
    version = version_tag or f"{max(all_ts)[:10].replace('-', '') if all_ts else 'empty'}-{h}"
    con.execute("INSERT INTO dataset_meta VALUES(?,?,?,?,?)",
                (version, min(all_ts) if all_ts else None, max(all_ts) if all_ts else None,
                 json.dumps(counts), json.dumps(comp)))
    con.commit()
    con.close()
    return version, counts, comp, chunks


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
    projects, listings, rent_freq, pages, gaps, srp_counts = build()
    P, L, G = list(projects.values()), list(listings.values()), list(pages.values())
    version, counts, comp, chunks = write_db(DATA / "concierge.sqlite", P, L, rent_freq, G)
    hits = pii_scan(DATA / "concierge.sqlite")
    # mini fixture: projects with most fields, their listings first, plus pages of different types
    Ps = sorted(P, key=lambda p: (p.price_from_amount is None, p.description_en is None and p.description_ar is None, p.id))[:10]
    pids = {p.id for p in Ps}
    Ls = [l for l in L if l.project_ref in pids][:4]
    rest = [l for l in L if l.project_ref is None]
    for t in ("buy", "rent"):
        Ls += [l for l in rest if l.listing_type == t and l.price_amount][:3 if t == "buy" else 3]
    Ls = list({l.id: l for l in Ls}.values())[:10]
    Gs, seen_t = [], set()
    for g in sorted(G, key=lambda g: g.page_type):
        if g.page_type not in seen_t or len(Gs) < 10:
            if len(Gs) < 10:
                Gs.append(g)
                seen_t.add(g.page_type)
    mversion, mcounts, _, _ = write_db(DATA / "fixtures" / "mini.sqlite", Ps, Ls, rent_freq, Gs, version_tag=f"mini-{version}")
    mini_hits = pii_scan(DATA / "fixtures" / "mini.sqlite")

    (DATA / "completeness.json").write_text(json.dumps({"dataset_version": version, "counts": counts, "completeness": comp},
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
           "resEmployee, managedBy (person/agency names), REGA licence numbers."]
    (DATA / "PII_SCAN.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    report = {"dataset_version": version, "counts": counts, "mini_counts": mcounts, "pii_hits": len(hits),
              "mini_pii_hits": len(mini_hits), "srp_site_counts": srp_counts, "gaps": gaps}
    (DATA / "build_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("srp_site_counts",)}, indent=1, ensure_ascii=False))
    return 0 if not hits and not mini_hits else 1


if __name__ == "__main__":
    sys.exit(main())
