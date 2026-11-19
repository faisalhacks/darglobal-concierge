"""Offline checks on the built datasets (no network)."""
import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scraper"))
from build_dataset import ARABIC_DIGITS, pii_scan, strip_pii  # noqa: E402

DBS = [REPO / "data" / "concierge.sqlite", REPO / "data" / "fixtures" / "mini.sqlite"]
TABLES = {
    "projects": ["id", "slug", "name_en", "name_ar", "site", "developer", "brand_partner", "city", "country", "lat", "lng",
                 "property_types", "unit_types", "price_from_amount", "price_from_currency", "price_to_amount",
                 "area_min_m2", "area_max_m2", "amenities", "status", "handover_year", "description_en",
                 "description_ar", "image_urls", "source_url", "scraped_at", "content_hash"],
    "listings": ["id", "title", "listing_type", "property_type", "price_amount", "price_currency", "beds", "baths",
                 "area_m2", "city", "district", "project_ref", "image_urls", "source_url", "scraped_at", "content_hash"],
    "pages": ["id", "site", "page_type", "title", "text", "lang", "source_url", "scraped_at"],
    "chunks": ["id", "entity_type", "entity_id", "site", "lang", "text", "city", "country", "source_url", "scraped_at"],
    "dataset_meta": ["version", "scraped_at_min", "scraped_at_max", "counts", "completeness"],
}


@pytest.fixture(params=DBS, ids=lambda p: p.name)
def con(request):
    if not request.param.exists():
        pytest.skip(f"{request.param} not built")
    c = sqlite3.connect(request.param)
    yield c
    c.close()


def test_schema_exact(con):
    for t, cols in TABLES.items():
        assert [r[1] for r in con.execute(f"PRAGMA table_info({t})")] == cols


def test_non_empty_and_meta(con):
    for t in ("listings", "pages", "chunks"):
        assert con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] > 0
    v, mn, mx, counts, comp = con.execute("SELECT * FROM dataset_meta").fetchone()
    assert v and mn <= mx
    assert json.loads(counts)["listings"] == con.execute("SELECT count(*) FROM listings").fetchone()[0]


def _thirdparty_urls() -> set[str]:
    """Source URLs of the sourced third-party DarGlobal facts (scraper/manual/darglobal/thirdparty/*.json)."""
    out = set()
    for p in (REPO / "scraper" / "manual" / "darglobal" / "thirdparty").glob("*.json"):
        out |= {f["source_url"] for f in json.loads(p.read_text(encoding="utf-8")).get("facts") or []}
    return out


def test_required_fields_and_urls(con):
    tp = _thirdparty_urls()
    for site, url in con.execute("SELECT site, source_url FROM projects UNION ALL SELECT 'Wasalt', source_url FROM listings"):
        if site == "Wasalt":
            assert url.startswith("https://wasalt.sa/"), url
        else:  # DarGlobal: its own site, or a recorded third-party source (RNS mirror / press / wire release)
            assert url.startswith("https://darglobal.co.uk/") or url in tp, url
    assert con.execute("SELECT count(*) FROM listings WHERE listing_type NOT IN ('buy','rent')").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM projects WHERE coalesce(name_en, name_ar) IS NULL").fetchone()[0] == 0


def test_chunks_point_to_entities(con):
    orphans = con.execute("""SELECT count(*) FROM chunks c WHERE
        (c.entity_type='project' AND c.entity_id NOT IN (SELECT id FROM projects)) OR
        (c.entity_type='listing' AND c.entity_id NOT IN (SELECT id FROM listings)) OR
        (c.entity_type='page' AND c.entity_id NOT IN (SELECT id FROM pages))""").fetchone()[0]
    assert orphans == 0


def test_project_refs_resolve(con):
    assert con.execute("SELECT count(*) FROM listings WHERE project_ref IS NOT NULL "
                       "AND project_ref NOT IN (SELECT id FROM projects)").fetchone()[0] == 0


@pytest.mark.parametrize("db", DBS, ids=lambda p: p.name)
def test_pii_zero(db):
    if not db.exists():
        pytest.skip()
    assert pii_scan(db) == []


def test_strip_pii_examples():
    assert "0551000605" not in (strip_pii("ابتداء من 435 الف\n0551000605") or "")
    assert "@" not in (strip_pii("email me: a.b@example.com today") or "")
    out = strip_pii("للتواصل واتساب ٠٥٥١٢٣٤٥٦٧\nفيلا 3 غرف") or ""
    assert "فيلا" in out and "055" not in out.translate(ARABIC_DIGITS)
    assert strip_pii("Price 1,195,000 SAR, area 81 sqm") == "Price 1,195,000 SAR, area 81 sqm"
