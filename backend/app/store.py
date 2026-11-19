"""Read-only dataset store. The SQLite file (SPEC §7) is small, so it is loaded into memory at startup.

Cards, compare tables and sources are built here in code from DB rows (SPEC D6) - the LLM never writes them.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .arabic import normalize_text

log = logging.getLogger("concierge.store")

JSON_FIELDS = {"property_types", "unit_types", "amenities", "image_urls"}


def _json(v):
    if v is None or isinstance(v, (list, dict)):
        return v
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return None


def site_label(v: str | None) -> str:
    s = (v or "").strip().lower()
    if s.startswith("wasalt"):
        return "Wasalt"
    return "DarGlobal"


def _first_image(row: dict) -> str | None:
    imgs = row.get("image_urls")
    if isinstance(imgs, list):
        for u in imgs:
            if isinstance(u, str) and u.startswith("https://"):
                return u
    return None


@dataclass
class Store:
    projects: list[dict] = field(default_factory=list)
    listings: list[dict] = field(default_factory=list)
    pages: list[dict] = field(default_factory=list)
    chunks: list[dict] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    loaded: bool = False
    allowed_hosts: set[str] = field(default_factory=set)

    # ---------- loading ----------
    @classmethod
    def load(cls, path: str) -> "Store":
        st = cls()
        if not os.path.exists(path):
            log.warning("dataset not found at %s; serving empty store", path)
            return st
        con = sqlite3.connect(f"file:{os.path.abspath(path)}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            st.projects = [cls._row(r) for r in cls._q(con, "SELECT * FROM projects")]
            st.listings = [cls._row(r) for r in cls._q(con, "SELECT * FROM listings")]
            st.pages = [dict(r) for r in cls._q(con, "SELECT * FROM pages")]
            st.chunks = [dict(r) for r in cls._q(con, "SELECT * FROM chunks")]
            metas = [dict(r) for r in cls._q(con, "SELECT * FROM dataset_meta")]
        finally:
            con.close()
        if metas:
            m = metas[-1]
            st.meta = {
                "version": str(m.get("version") or "unknown"),
                "scraped_at_min": m.get("scraped_at_min"),
                "scraped_at_max": m.get("scraped_at_max"),
                "counts": _json(m.get("counts")) or {},
                "completeness": _json(m.get("completeness")) or {},
            }
        for p in st.projects:
            p["site"] = site_label(p.get("site"))
        for item in st.listings:
            item["site"] = "Wasalt"
        for pg in st.pages:
            pg["site"] = site_label(pg.get("site"))
        if not st.chunks:
            st.chunks = st._synth_chunks()
        for c in st.chunks:
            c["site"] = site_label(c.get("site"))
        for row in st.projects + st.listings + st.pages + st.chunks:
            h = urlparse(row.get("source_url") or "").hostname
            if h:
                st.allowed_hosts.add(h.lower())
        st.loaded = True
        log.info("store loaded: %d projects, %d listings, %d pages, %d chunks",
                 len(st.projects), len(st.listings), len(st.pages), len(st.chunks))
        return st

    @staticmethod
    def _q(con, sql):
        try:
            return con.execute(sql).fetchall()
        except sqlite3.Error as e:
            log.warning("query failed (%s): %s", sql, e)
            return []

    @staticmethod
    def _row(r) -> dict:
        d = dict(r)
        for k in JSON_FIELDS:
            if k in d:
                d[k] = _json(d[k])
        return d

    def _synth_chunks(self) -> list[dict]:
        """Fallback when the chunks table is empty: one fact chunk per row + page text windows."""
        out = []
        for p in self.projects:
            out.append({"id": f"pf:{p['id']}", "entity_type": "project", "entity_id": p["id"], "site": p["site"],
                        "lang": "en", "text": project_fact_text(p), "city": p.get("city"), "country": p.get("country"),
                        "source_url": p.get("source_url"), "scraped_at": p.get("scraped_at")})
        for item in self.listings:
            out.append({"id": f"lf:{item['id']}", "entity_type": "listing", "entity_id": item["id"], "site": "Wasalt",
                        "lang": "en", "text": listing_fact_text(item), "city": item.get("city"), "country": None,
                        "source_url": item.get("source_url"), "scraped_at": item.get("scraped_at")})
        for pg in self.pages:
            text = pg.get("text") or ""
            for i in range(0, max(len(text), 1), 1600):
                out.append({"id": f"pg:{pg['id']}:{i}", "entity_type": "page", "entity_id": pg["id"], "site": pg["site"],
                            "lang": pg.get("lang") or "en", "text": f"{pg.get('title') or ''}\n{text[i:i + 1800]}",
                            "city": None, "country": None, "source_url": pg.get("source_url"),
                            "scraped_at": pg.get("scraped_at")})
        return out

    # ---------- meta ----------
    @property
    def version(self) -> str:
        return self.meta.get("version", "none")

    @property
    def data_as_of(self) -> str | None:
        v = self.meta.get("scraped_at_max") or self.meta.get("scraped_at_min")
        if not v:
            dates = [r.get("scraped_at") for r in self.projects + self.listings + self.pages if r.get("scraped_at")]
            v = max(dates) if dates else None
        return str(v)[:10] if v else None

    def counts(self) -> dict:
        return {"projects": len(self.projects), "listings": len(self.listings),
                "pages": len(self.pages), "chunks": len(self.chunks)}

    def coverage(self) -> dict:
        """Contract C2 /api/meta.coverage, computed from the rows actually loaded."""
        dg = [p for p in self.projects if p["site"] == "DarGlobal"]
        return {"DarGlobal": {"projects": len(dg), "detail_pages": sum(1 for p in dg if detail_level(p) == "page"),
                              "prices_published": any(p.get("price_from_amount") is not None for p in dg)},
                "Wasalt": {"projects": sum(1 for p in self.projects if p["site"] == "Wasalt"),
                           "listings": len(self.listings)}}

    # ---------- lookups ----------
    def project_by_id(self, pid: str) -> dict | None:
        return next((p for p in self.projects if p["id"] == pid or p.get("slug") == pid), None)

    def listing_by_id(self, lid: str) -> dict | None:
        return next((x for x in self.listings if x["id"] == lid), None)

    def page_by_id(self, pid: str) -> dict | None:
        return next((x for x in self.pages if x["id"] == pid), None)

    def licence_for(self, p: dict) -> dict:
        """Verbatim licence/disclaimer wording for a DarGlobal project, from its page row with page_type 'disclaimer'
        (id darglobal-pg-disclaimer-<slug>, written by the data lane from the official page). Never composed here:
        no row -> no note."""
        if p.get("site") != "DarGlobal":
            return {}
        slug = str(p["id"])[3:] if str(p["id"]).startswith("dg-") else str(p["id"])
        pg = self.page_by_id(f"darglobal-pg-disclaimer-{slug}")
        if not pg or pg.get("page_type") != "disclaimer" or not (pg.get("text") or "").strip():
            return {}
        return {"licence_note": pg["text"].strip(), "licence_url": pg.get("source_url")}

    def chunk_by_id(self, cid: str) -> dict | None:
        return next((c for c in self.chunks if c["id"] == cid), None)

    def filter_projects(self, city=None, country=None, site=None, brand=None) -> list[dict]:
        def eq(a, b):
            return normalize_text(a or "") == normalize_text(b)
        out = []
        for p in self.projects:
            if city and not eq(p.get("city"), city):
                continue
            if country and not eq(p.get("country"), country):
                continue
            if site and p["site"].lower() != site.lower():
                continue
            if brand and normalize_text(brand) not in normalize_text(p.get("brand_partner") or ""):
                continue
            out.append(p)
        return out

    def filter_listings(self, city=None, listing_type=None, min_price=None, max_price=None, beds=None,
                        property_type=None, currency=None) -> list[dict]:
        out = []
        for x in self.listings:
            if city and normalize_text(x.get("city") or "") != normalize_text(city):
                continue
            if listing_type and x.get("listing_type") != listing_type:
                continue
            price = x.get("price_amount")
            if (min_price is not None or max_price is not None) and price is None:
                continue
            if currency and price is not None and (x.get("price_currency") or "").upper() != currency.upper():
                continue
            if min_price is not None and price < min_price:
                continue
            if max_price is not None and price > max_price:
                continue
            if beds is not None and x.get("beds") != beds:
                continue
            if property_type and normalize_text(property_type) not in normalize_text(
                    f"{x.get('property_type') or ''} {x.get('title') or ''}"):
                continue
            out.append(x)
        return out

    def contact_pages(self) -> list[dict]:
        return [pg for pg in self.pages
                if (pg.get("page_type") or "").lower() == "contact" and self.is_allowed_url(pg.get("source_url"))]

    def is_allowed_url(self, url: str | None) -> bool:
        if not url or not url.startswith("https://"):
            return False
        h = (urlparse(url).hostname or "").lower()
        return h in self.allowed_hosts


# ---------- builders (code, never LLM) ----------
def money(amount, currency):
    if amount is None:
        return None
    return {"amount": amount, "currency": (currency or "").upper() or None}


def fmt_num(v) -> str:
    f = float(v)
    return f"{int(f):,}" if f.is_integer() else f"{f:,.2f}"


def fmt_money(amount, currency) -> str | None:
    if amount is None:
        return None
    return f"{fmt_num(amount)} {(currency or '').upper()}".strip()


def project_name(p: dict, lang: str = "en") -> str:
    if lang == "ar" and p.get("name_ar"):
        return p["name_ar"]
    return p.get("name_en") or p.get("name_ar") or p.get("slug") or p["id"]


# Contract C1: a DarGlobal row whose source is the projects index holds name + location only.
DARGLOBAL_INDEX_URL = "https://darglobal.co.uk/projects"
PRICE_ON_REQUEST = {"en": "Price on request", "ar": "السعر عند الطلب"}


OFFICIAL_HOSTS = ("darglobal.co.uk", "darglobal.com", "wasalt.sa", "wasalt.com")
# Third-party hosts that carry sourced DarGlobal facts, with an honest label (never "DarGlobal").
THIRDPARTY_LABELS = {"ticker.app": "LSE filing via ticker.app", "thenationalnews.com": "The National (news)"}


def _host(url: str | None) -> str:
    try:
        h = (urlparse(url or "").hostname or "").lower()
    except ValueError:
        return ""
    return h[4:] if h.startswith("www.") else h


_TEST_SUFFIXES = (".invalid", ".test", ".example", "example.com", "example.org")  # RFC 2606 names in test fixtures


def is_official(url: str | None) -> bool:
    h = _host(url)
    return any(h == d or h.endswith("." + d) for d in OFFICIAL_HOSTS) or h.endswith(_TEST_SUFFIXES)


def source_site(url: str | None, site: str | None) -> str:
    """Who published the page at `url`: the brand for its own domains, otherwise an honest third-party label."""
    h = _host(url)
    if not h or is_official(url):
        return "Wasalt" if "wasalt" in h else "DarGlobal" if "darglobal" in h else site_label(site)
    return next((v for k, v in THIRDPARTY_LABELS.items() if h == k or h.endswith("." + k)), h)


def detail_level(p: dict) -> str:
    """'index' = collected from the DarGlobal projects index only (name + location); 'thirdparty' = the structured
    record comes from a third-party public source (LSE filing, press); 'page' = its own official page was collected."""
    u = (p.get("source_url") or "").rstrip("/")
    if u == DARGLOBAL_INDEX_URL:
        return "index"
    return "page" if (not u or is_official(u)) else "thirdparty"


def price_label(p: dict, lang: str = "en") -> str:
    return fmt_money(p.get("price_from_amount"), p.get("price_from_currency")) or \
        PRICE_ON_REQUEST["ar" if lang == "ar" else "en"]


def project_card(p: dict, lang: str = "en") -> dict:
    from .planner import place_display
    return {
        "id": p["id"], "slug": p.get("slug") or p["id"], "name": project_name(p, lang), "site": p["site"],
        "city": p.get("city"), "country": p.get("country"),
        "city_display": place_display(p.get("city"), lang) or None,
        "country_display": place_display(p.get("country"), lang) or None,
        "source_site": source_site(p.get("source_url"), p.get("site")),
        "price_from": money(p.get("price_from_amount"), p.get("price_from_currency")),
        "price_label": price_label(p, lang), "detail": detail_level(p),
        "status": p.get("status"), "image_url": _first_image(p), "source_url": p.get("source_url"),
    }


# A listing whose area per bedroom is above this is probably mis-entered (e.g. a 730 m² one-bedroom apartment).
AREA_PER_BED_FLAG_M2 = 250


def listing_card(x: dict, lang: str = "en") -> dict:
    from .planner import place_display
    beds, area = x.get("beds"), x.get("area_m2")
    flag = bool(beds and area and area / beds > AREA_PER_BED_FLAG_M2
                and "apartment" in str(x.get("property_type") or "").lower())
    from .calculator import usd_approx  # lazy: calculator imports planner, which imports this module
    card = {"area_flag": flag,
        "id": x["id"], "title": x.get("title") or "", "site": "Wasalt", "listing_type": x.get("listing_type"),
        "price": money(x.get("price_amount"), x.get("price_currency")),
        "beds": x.get("beds"), "baths": x.get("baths"), "area_m2": x.get("area_m2"),
        "district": x.get("district"), "city": x.get("city"),
        "city_display": place_display(x.get("city"), lang) or None, "image_url": _first_image(x),
        "source_url": x.get("source_url"),
    }
    usd = usd_approx(x.get("price_amount"), x.get("price_currency"))  # whole USD via the official peg, never a market rate
    if usd is not None:
        card["price_usd_approx"] = usd  # optional field: the UI shows "≈ $X" only when it is present
    return card


def project_fact_text(p: dict) -> str:
    parts = [f"{p.get('name_en') or ''} {p.get('name_ar') or ''}".strip()]
    loc = ", ".join(x for x in (p.get("city"), p.get("country")) if x)
    if loc:
        parts.append(f"Location: {loc}")
    if p.get("developer"):
        parts.append(f"Developer: {p['developer']}")
    if p.get("brand_partner"):
        parts.append(f"Brand partner: {p['brand_partner']}")
    if p.get("price_from_amount") is not None:
        parts.append(f"Price from: {fmt_money(p['price_from_amount'], p.get('price_from_currency'))}")
    else:
        parts.append("Price: not published")
    if p.get("property_types"):
        parts.append("Property types: " + ", ".join(map(str, p["property_types"])))
    if p.get("unit_types"):
        parts.append("Unit types: " + ", ".join(map(str, p["unit_types"])))
    if p.get("status"):
        parts.append(f"Status: {p['status']}")
    if p.get("handover_year"):
        parts.append(f"Handover: {p['handover_year']}")
    if p.get("area_min_m2") or p.get("area_max_m2"):
        lo, hi = p.get("area_min_m2"), p.get("area_max_m2")
        parts.append("Unit sizes: " + (f"{fmt_num(lo)} to {fmt_num(hi)} m2" if lo and hi and lo != hi
                                       else f"{fmt_num(lo or hi)} m2"))
    if p.get("amenities"):
        parts.append("Amenities: " + ", ".join(map(str, p["amenities"][:10])))
    if p.get("description_en"):
        parts.append("Description: " + str(p["description_en"]).strip())
    return ". ".join(parts)


def project_fact_text_ar(p: dict) -> str:
    """Arabic labels for the LLM context of an Arabic question (values stay as published)."""
    from .planner import place_display
    parts = [f"المشروع: {project_name(p, 'ar')}"]
    loc = "، ".join(place_display(x, "ar") for x in (p.get("city"), p.get("country")) if x)
    if loc:
        parts.append(f"الموقع: {loc}")
    if p.get("developer"):
        parts.append("المطور: " + ("دار جلوبال" if p["developer"] == "DarGlobal" else p["developer"]))
    if p.get("brand_partner"):
        parts.append(f"العلامة الشريكة: {p['brand_partner']}")
    price = fmt_money(p.get("price_from_amount"), p.get("price_from_currency"))
    parts.append(f"السعر يبدأ من: {price}" if price else "السعر: غير منشور")
    if p.get("unit_types"):
        parts.append("أنواع الوحدات: " + "، ".join(map(str, p["unit_types"])))
    if p.get("status"):
        parts.append(f"الحالة: {p['status']}")
    if p.get("handover_year"):
        parts.append(f"التسليم: {p['handover_year']}")
    return ". ".join(parts)


def listing_fact_text(x: dict) -> str:
    parts = [x.get("title") or "", f"For {x.get('listing_type')}"]
    if x.get("price_amount") is not None:
        parts.append(f"Price: {fmt_money(x['price_amount'], x.get('price_currency'))}")
    for k, lab in (("beds", "Bedrooms"), ("baths", "Bathrooms"), ("area_m2", "Area m2"),
                   ("district", "District"), ("city", "City")):
        if x.get(k) is not None:
            parts.append(f"{lab}: {x[k]}")
    return ". ".join(parts)


def source_of(row: dict, title: str | None = None) -> dict:
    # site = who published the page (honest label); brand = which brand's project/listing it is about.
    return {"site": source_site(row.get("source_url"), row.get("site")), "brand": site_label(row.get("site")),
            "title": title or row.get("title") or row.get("name_en") or "",
            "url": row.get("source_url"), "scraped_at": row.get("scraped_at")}


def _area(p):
    lo, hi = p.get("area_min_m2"), p.get("area_max_m2")
    if lo is None and hi is None:
        return None
    if lo is not None and hi is not None:
        return f"{fmt_num(lo)}–{fmt_num(hi)}"
    return fmt_num(lo if lo is not None else hi)


COMPARE_ROWS = [
    ("Location", "الموقع", lambda p: ", ".join(x for x in (p.get("city"), p.get("country")) if x) or None),
    ("Developer", "المطور", lambda p: p.get("developer")),
    ("Brand partner", "العلامة الشريكة", lambda p: p.get("brand_partner")),
    ("Price from", "السعر يبدأ من", lambda p: fmt_money(p.get("price_from_amount"), p.get("price_from_currency"))),
    ("Property types", "أنواع العقارات",
     lambda p: ", ".join(map(str, p["property_types"])) if p.get("property_types") else None),
    ("Unit types", "أنواع الوحدات", lambda p: ", ".join(map(str, p["unit_types"])) if p.get("unit_types") else None),
    ("Area (m²)", "المساحة (م²)", _area),
    ("Status", "الحالة", lambda p: p.get("status")),
    ("Handover", "التسليم", lambda p: str(p["handover_year"]) if p.get("handover_year") else None),
]

LISTING_COMPARE_ROWS = [
    ("Type", "النوع", lambda x: x.get("listing_type")),
    ("Price", "السعر", lambda x: fmt_money(x.get("price_amount"), x.get("price_currency"))),
    ("Bedrooms", "غرف النوم", lambda x: str(x["beds"]) if x.get("beds") is not None else None),
    ("Bathrooms", "دورات المياه", lambda x: str(x["baths"]) if x.get("baths") is not None else None),
    ("Area (m²)", "المساحة (م²)", lambda x: fmt_num(x["area_m2"]) if x.get("area_m2") is not None else None),
    ("Location", "الموقع", lambda x: ", ".join(v for v in (x.get("district"), x.get("city")) if v) or None),
]


def compare_payload(store: Store, ids: list[str], lang: str = "en") -> dict | None:
    rows_src = []
    for i in ids:
        p = store.project_by_id(i)
        if p:
            rows_src.append(("p", p))
            continue
        x = store.listing_by_id(i)
        if x:
            rows_src.append(("l", x))
    if len(rows_src) < 2:
        return None
    kinds = {k for k, _ in rows_src}
    spec = COMPARE_ROWS if kinds == {"p"} else LISTING_COMPARE_ROWS if kinds == {"l"} else None
    if spec is None:
        return None
    cols, srcs = [], []
    for k, r in rows_src:
        name = project_name(r, lang) if k == "p" else r.get("title") or r["id"]
        cols.append({"id": r["id"], "name": name, "site": r["site"]})
        srcs.append(source_of(r, name))
    rows = []
    for en, ar, fn in spec:
        vals = [fn(r) for _, r in rows_src]
        if lang == "ar":
            vals = [_ar_value(en, v, r) for v, (_, r) in zip(vals, rows_src)]
        present = [v for v in vals if v is not None]
        rows.append({"label": (ar if lang == "ar" else en), "values": vals,
                     "differs": len(set(present)) > 1 or (0 < len(present) < len(vals))})
    return {"columns": cols, "rows": rows, "sources": srcs, "verdict": _verdict(cols, rows, lang)}


_STATUS_AR = {"under development": "قيد التطوير", "completed": "مكتمل", "completed and sold out": "مكتمل ومباع بالكامل",
              "sold out": "مباع بالكامل", "off-plan": "على الخريطة", "under construction": "قيد الإنشاء", "ready": "جاهز",
              "buy": "للبيع", "rent": "للإيجار"}


def _ar_value(row_en: str, v, r: dict):
    """Arabic compare cells: places and statuses in Arabic; published names and figures unchanged."""
    from .planner import place_display
    if v is None:
        return None
    if row_en in ("Location",):
        return "، ".join(place_display(x, "ar") for x in (r.get("district"), r.get("city"), r.get("country")) if x
                        and (x != r.get("district") or "district" in r)) or v
    if row_en in ("Status", "Type"):
        return _STATUS_AR.get(str(v).strip().lower(), v)
    if row_en == "Developer" and v == "DarGlobal":
        return "دار جلوبال"
    return v


def _verdict(cols: list[dict], rows: list[dict], lang: str) -> str:
    """One line computed only from the table: which rows differ, which are the same, how many are unpublished."""
    diff = [r["label"] for r in rows if r["differs"]]
    same = [r["label"] for r in rows if not r["differs"] and all(v is not None for v in r["values"])]
    missing = sum(1 for r in rows for v in r["values"] if v is None)
    a, b = cols[0]["name"], cols[1]["name"]
    if lang == "ar":
        out = f"يختلف {a} و{b} في: {'، '.join(diff) or 'لا شيء منشور'}"
        if same:
            out += f"؛ ويتشابهان في: {'، '.join(same)}"
        return out + (f". {missing} من الخانات غير منشورة." if missing else ".")
    out = f"{a} and {b} differ on: {', '.join(diff).lower() or 'nothing published'}"
    if same:
        out += f"; they share: {', '.join(same).lower()}"
    return out + (f". {missing} cell{'s are' if missing != 1 else ' is'} not published." if missing else ".")
