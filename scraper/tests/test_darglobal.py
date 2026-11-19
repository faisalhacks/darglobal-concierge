"""DarGlobal manual-collection parser + built-dataset checks (offline, no network)."""
import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scraper"))
import darglobal_manual as dgm  # noqa: E402

EXT = REPO / "scraper" / "manual" / "darglobal" / "extracts"
DB = REPO / "data" / "concierge.sqlite"
MINI = REPO / "data" / "fixtures" / "mini.sqlite"
CLAIMS = re.compile(r"yield|returns|doubled", re.I)


def _load(name):
    return json.loads((EXT / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def index_rows():
    if not (EXT / "projects.json").exists():
        pytest.skip("projects.json extract not present")
    return dgm.parse_index(_load("projects.json"))


def test_index_one_row_per_h3_name(index_rows):
    rows, rep = index_rows
    d = _load("projects.json")
    h3 = [h for h in d["headings"] if h.startswith("H3:") and "Discover" not in h]
    assert rep["h3_names"] == len(h3) == len(rows)
    assert rep["missing_in_text"] == []
    assert len({r["id"] for r in rows}) == len(rows)
    assert all(r["id"].startswith("dg-") and r["source_url"] == dgm.INDEX_URL for r in rows)
    # names keep the published title case from the text, not the upper-case heading
    by = {r["id"]: r for r in rows}
    assert by["dg-w-residences"]["name_en"] == "W Residences"
    assert by["dg-the-astera-interiors-by-aston-martin"]["name_en"] == "The Astera, Interiors by Aston Martin"


def test_index_locations(index_rows):
    rows, rep = index_rows
    by = {r["id"]: r for r in rows}
    assert sum(1 for r in rows if r["country"] == "Oman") >= 10
    assert (by["dg-the-astera-interiors-by-aston-martin"]["city"], by["dg-the-astera-interiors-by-aston-martin"]["country"]) \
        == ("Ras Al Khaimah", "United Arab Emirates")
    assert (by["dg-amaya"]["city"], by["dg-amaya"]["country"]) == ("Jeddah", "Saudi Arabia")   # not 'AmayaLuxury...'
    assert (by["dg-the-great-escape"]["country"], by["dg-the-great-escape-2"]["country"]) == ("Oman", "Oman")
    assert by["dg-7and8-albert-hall-mansions"]["country"] == "United Kingdom"                 # 'England' token
    assert by["dg-les-vagues-by-elie-saab"]["country"] == "Qatar"
    # no country token in 'Rayana, Wadi Safar, Riyadh' -> NULL and reported, not guessed
    assert by["dg-trump-mansions"]["country"] is None
    assert any(u["id"] == "dg-trump-mansions" for u in rep["unresolved"])
    assert rep["location_filter_list"] == ["United Arab Emirates", "Spain", "Qatar", "Oman", "United Kingdom",
                                           "Saudi Arabia"]


def test_parse_location_token_map_only():
    assert dgm.parse_location("AIDA | Oman") == (None, "Oman", True)  # AIDA is a development, not a city
    assert dgm.parse_location("AIDA, Muscat, Oman") == ("Muscat", "Oman", True)
    assert dgm.parse_location("Overlooking Hyde Park, London, England") == ("London", "United Kingdom", True)
    assert dgm.parse_location("Somewhere, Atlantis") == ("Atlantis", None, False)


def test_astera_detail():
    if not (EXT / "the-astera.json").exists():
        pytest.skip()
    row, rep = dgm.parse_detail(_load("the-astera.json"), set(), set())
    assert row["status"] == "Under Development"
    assert (row["area_min_m2"], row["area_max_m2"]) == (61.0, 265.0)       # published sqm, not the sqft label
    assert "682 - 12,277" in row["area_published"]
    assert (row["lat"], row["lng"]) == (25.684983, 55.741664)
    assert "Infinity Pool" in row["amenities"]
    assert row["brand_partner"] == "Aston Martin"
    assert row["handover_year"] == 2028
    assert row["description_en"].startswith("The Astera, Interiors by Aston Martin is a beachfront")
    assert 0 < len(row["image_urls"]) <= 6
    assert all(u.startswith("https://cdn.darglobal.co.uk/") and "projects_bg" not in u for u in row["image_urls"])
    assert any("WHY INVEST" in s for s in rep["excluded_sections"])
    text = row["description_en"] + " ".join(t for _, t in row["sections"])
    assert not CLAIMS.search(text)
    assert "Wynn" not in row["description_en"]
    assert "[phone]" not in text and "[name removed]" not in text
    assert "Register Interest" not in text and "cookies" not in text


def test_sqft_conversion_when_no_sqm_stated():
    if not (EXT / "w-residences.json").exists():
        pytest.skip()
    row, rep = dgm.parse_detail(_load("w-residences.json"), set(), set())
    assert (row["area_min_m2"], row["area_max_m2"]) == (round(701 * 0.092903, 1), round(7627 * 0.092903, 1))
    assert row["status"] == "Completed and Sold out"
    assert row["brand_partner"] == "W Hotels"


def test_load_merges_detail_into_index():
    out = dgm.load()
    p = out["projects"]
    detail = [r for r in p.values() if r["source_url"] != dgm.INDEX_URL]
    assert len(detail) == len(out["report"]["detail"])
    no_status_published = {"dg-trump-furnished-residences"}     # the page has no STATUS label and no FAQ status
    for r in detail:
        assert r["description_en"]
        assert r["status"] or r["id"] in no_status_published
        assert r["id"] in out["report"]["detail_slugs"]


# ---------------------------------------------------------------- built dataset
@pytest.fixture(params=[DB, MINI], ids=lambda x: x.name)
def con(request):
    if not request.param.exists():
        pytest.skip("not built")
    c = sqlite3.connect(request.param)
    yield c
    c.close()


def test_darglobal_rows_have_no_price_and_chunks(con):
    assert con.execute("SELECT count(*) FROM projects WHERE site='DarGlobal' AND (price_from_amount IS NOT NULL "
                       "OR price_to_amount IS NOT NULL OR price_from_currency IS NOT NULL)").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM projects WHERE site='DarGlobal' AND developer != 'DarGlobal'").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM projects p WHERE site='DarGlobal' AND NOT EXISTS "
                       "(SELECT 1 FROM chunks c WHERE c.entity_id=p.id)").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM chunks WHERE site='DarGlobal' AND (text LIKE '%yield%' OR "
                       "text LIKE '%returns%' OR text LIKE '%doubled%')").fetchone()[0] == 0
    for (imgs,) in con.execute("SELECT image_urls FROM projects WHERE site='DarGlobal'"):
        imgs = json.loads(imgs)
        assert len(imgs) <= 6 and all(u.startswith("https://cdn.darglobal.co.uk/") for u in imgs)


def test_contact_pages(con):
    rows = con.execute("SELECT site, source_url, text FROM pages WHERE page_type='contact' ORDER BY site").fetchall()
    assert [r[0] for r in rows] == ["DarGlobal", "Wasalt"]
    assert rows[0][1] == "https://darglobal.co.uk/get-in-touch"
    for _, _, text in rows:
        assert not re.search(r"\d{6,}|@|whatsapp|wa\.me", text, re.I)


def test_headers_on_description_and_page_chunks(con):
    rx = re.compile(r"^[^:]+ \| (?:DarGlobal|Wasalt) \| [^:|]+: ")
    rows = con.execute("SELECT id, text FROM chunks WHERE entity_type='page' OR id LIKE '%#desc-%' "
                       "OR id LIKE '%#sec-%'").fetchall()
    assert rows
    bad = [i for i, t in rows if not rx.match(t)]
    assert bad == []


def test_counts_detail_by_site(con):
    counts = json.loads(con.execute("SELECT counts FROM dataset_meta").fetchone()[0])
    d = counts["projects_detail_by_site"]["DarGlobal"]
    # level is read from the fact chunk's source: own darglobal.co.uk page / the projects index / third-party only
    n_page = con.execute(f"SELECT count(*) FROM chunks WHERE id LIKE 'dg-%#fact-en' AND source_url LIKE "
                         f"'https://darglobal.co.uk/%' AND source_url != '{dgm.INDEX_URL}'").fetchone()[0]
    n_idx = con.execute(f"SELECT count(*) FROM chunks WHERE id LIKE 'dg-%#fact-en' "
                        f"AND source_url = '{dgm.INDEX_URL}'").fetchone()[0]
    n_all = con.execute("SELECT count(*) FROM projects WHERE site='DarGlobal'").fetchone()[0]
    assert (d["page"], d["index"]) == (n_page, n_idx)
    assert d["page"] + d["index"] + d["thirdparty_only"] == n_all


def test_mini_has_three_darglobal():
    if not MINI.exists():
        pytest.skip()
    c = sqlite3.connect(MINI)
    # DarGlobal level comes from the fact chunk's source (an index row enriched from the RNS carries the RNS as
    # projects.source_url, while its fact chunk still cites the DarGlobal index)
    rows = c.execute("SELECT c.source_url, p.country FROM projects p JOIN chunks c ON c.id = p.id || '#fact-en' "
                     "WHERE p.site='DarGlobal'").fetchall()
    n_tp = c.execute("SELECT count(*) FROM chunks WHERE id LIKE 'dg-%#tp-en-%'").fetchone()[0]
    c.close()
    assert len(rows) == 3
    assert sum(1 for u, _ in rows if u.startswith("https://darglobal.co.uk/") and u != dgm.INDEX_URL) == 2
    assert any(u == dgm.INDEX_URL and k == "Oman" for u, k in rows)
    assert n_tp > 0          # the Oman index row (AIDA) carries third-party facts


def test_index_meta_matches_db():
    meta_p = REPO / "data" / "index" / "meta.json"
    if not (meta_p.exists() and DB.exists()):
        pytest.skip()
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    c = sqlite3.connect(DB)
    v = c.execute("SELECT version FROM dataset_meta").fetchone()[0]
    n = c.execute("SELECT count(*) FROM chunks").fetchone()[0]
    c.close()
    assert meta["dataset_version"] == v and meta["n"] == n


# ---------------------------------------------------------------- third-party facts
import darglobal_thirdparty as dgt  # noqa: E402

TP = REPO / "scraper" / "manual" / "darglobal" / "thirdparty"
RNS = "https://www.ticker.app/lse/DAR/rns/2026-03-11/Full-Year-Results/1301W"


@pytest.fixture(scope="module")
def merged():
    if not TP.exists():
        pytest.skip("no third-party facts")
    rows = dgm.load()["projects"]
    extras, rep = dgt.merge(rows)
    return rows, extras, rep


def test_thirdparty_matching(merged):
    rows, extras, rep = merged
    assert sorted(rep["skipped_empty"]) == ["fairway-villas-aida.json", "la-collina.json", "sunrise-haven-aida.json"]
    m = {x["file"]: x["id"] for x in rep["matches"]}
    assert m["trump-tower-jeddah.json"] == "dg-trump-tower-jeddah"
    assert m["marriott-residences-aida.json"] == "dg-marriott-residences"
    assert m["the-great-escape-aida.json"] == "dg-the-great-escape"
    assert {x["id"] for x in rep["new_rows"]} == {"dg-rayana", "dg-trump-plaza-jeddah", "dg-trump-signature-villas"}
    for x in rep["new_rows"]:
        assert rows[x["id"]]["source_url"].startswith("https://") and "darglobal" not in rows[x["id"]]["source_url"]
    # the reviewed table and the fuzzy matcher agree wherever the fuzzy matcher is confident
    for x in rep["matches"]:
        if x["fuzzy_suggestion"] and x["how"] == "reviewed":
            assert x["fuzzy_suggestion"] == x["id"]


def test_thirdparty_rules(merged):
    rows, extras, rep = merged
    ex = {(x["file"], x["field"]) for x in rep["excluded_facts"]}
    assert ("the-mulliner.json", "marketed_price") in ex and ("the-mulliner.json", "sale_price") in ex
    assert ("aida.json", "site_area") in ex                                  # curator: misprint, do not use
    # an index-only row: structured columns come from the most recent RNS value, the fact chunk cites the index
    dv = rows["dg-d-villas-at-jumeirah-golf-estates"]
    assert (dv["status"], dv["handover_year"], dv["source_url"]) == (
        "Under construction; main construction contracts awarded", 2028, RNS)
    assert dv["dg_source_url"] == dgm.INDEX_URL
    # a row with its own collected page keeps the page's values and source; the RNS value stays in the figures
    ttj = rows["dg-trump-tower-jeddah"]
    assert (ttj["status"], ttj["handover_year"], ttj["source_url"]) == (
        "Under Development", 2029, "https://darglobal.co.uk/trump-tower-jeddah")
    assert ttj["dg_source_url"] == "https://darglobal.co.uk/trump-tower-jeddah"
    tm = rows["dg-trump-mansions"]
    assert tm["country"] == "Saudi Arabia" and tm["location_published"] == "Rayana, Wadi Safar, Riyadh"
    assert any(c["id"] == "dg-trump-mansions" for c in rep["corrections"])
    fig = extras["dg-trump-tower-jeddah"]["figures"]["text"]
    assert "about 500 units (The National, 12 Dec 2024)" in fig and "561 (Dar Global PLC RNS 1301W, 11 Mar 2026)" in fig


def test_thirdparty_chunks_in_db(con):
    if not con.execute("SELECT count(*) FROM chunks WHERE id LIKE '%#tp-%'").fetchone()[0]:
        pytest.skip("no third-party chunks in this db")
    tp_urls = {f["source_url"] for p in TP.glob("*.json")
               for f in json.loads(p.read_text(encoding="utf-8")).get("facts") or []}
    for cid, url, text in con.execute("SELECT id, source_url, text FROM chunks WHERE id LIKE '%#tp-en-%'"):
        assert url in tp_urls, cid
        if cid.endswith("-0"):                       # first window of a source carries its own URL in the text
            assert f"URL: {url}." in text, cid
        if "hosted on a wire" in text:
            assert "company statement" in text
    prices = [t for (t,) in con.execute("SELECT text FROM chunks WHERE site='DarGlobal' "
                                        "AND text LIKE '%press-reported on%'")]
    assert all(t.startswith("Trump Tower Jeddah |") for t in prices)
    assert sum(t.count("Price press-reported on") for t in prices) <= 2
    # no other price figure, not even inside a quoted headline (URLs are left as published)
    for (t,) in con.execute("SELECT text FROM chunks WHERE site='DarGlobal' UNION ALL "
                            "SELECT text FROM pages WHERE site='DarGlobal'"):
        bare = re.sub(r"https://\S+", " ", t)
        assert "26.25" not in bare and "25mln" not in bare
    # every project with third-party facts has a public-sources chunk and a project_sources page
    for (pid,) in con.execute("SELECT DISTINCT entity_id FROM chunks WHERE id LIKE '%#tp-en-%'"):
        assert con.execute("SELECT count(*) FROM chunks WHERE id = ?", (f"{pid}#tp-sources-en-0",)).fetchone()[0] == 1
        slug = con.execute("SELECT slug FROM projects WHERE id=?", (pid,)).fetchone()[0]
        assert con.execute("SELECT count(*) FROM pages WHERE id=? AND page_type='project_sources'",
                           (f"darglobal-pg-sources-{slug}",)).fetchone()[0] == 1


# ---------------------------------------------------------------- get_page_text extracts (v2) + city / label fixes
V2 = ["aida-trump-international-apartments", "marriott-residences-aida-oman", "trump-tower-jeddah", "neptune",
      "the-mulliner", "tierra-viva"]


def test_v2_extracts_all_ingested():
    out = dgm.load()
    assert out["report"]["skipped"] == []
    urls = {r["source_url"] for r in out["projects"].values()} | {r.get("dg_source_url") for r in out["projects"].values()}
    for slug in V2:
        if (EXT / f"{slug}.json").exists():
            assert f"https://darglobal.co.uk/{slug}" in urls, slug


def test_v2_parse_values_and_conflicts():
    if not (EXT / "neptune.json").exists():
        pytest.skip()
    n, rep = dgm.parse_detail_v2(_load("neptune.json"))
    assert (n["status"], n["handover_year"], n["handover_text"]) == ("Under Development", 2027, "December 2027")
    assert (n["area_min_m2"], n["area_max_m2"]) == (300.0, 448.0)          # spec box
    assert n["area_text_sqm"] == "300 to 420 sqm"                           # prose figure kept beside it
    assert "both kept" in rep["area_note"]
    t, _ = dgm.parse_detail_v2(_load("tierra-viva.json"))
    assert (t["area_min_m2"], t["area_max_m2"], t["area_text_sqm"]) == (680.0, 1515.0, "700 to 1,450 sqm")
    assert t["description_en"].startswith("Tierra Viva is")                 # accented location line stripped
    a, rep = dgm.parse_detail_v2(_load("aida-trump-international-apartments.json"))
    assert any("WHY INVEST" in x for x in rep["excluded_sections"])
    txt = a["description_en"] + " ".join(x for _, x in a["sections"])
    assert "Capital Gains" not in txt and "Residency Visa" not in txt and "Highest ROI" not in txt
    assert (a["lat"], a["lng"]) == (23.529569, 58.675125)
    for slug in V2:
        r, _ = dgm.parse_detail_v2(_load(f"{slug}.json"))
        body = r["description_en"] + " ".join(x for _, x in r["sections"])
        assert not CLAIMS.search(body), slug
        assert not re.search(r"\bROI\b|tax", body), slug


def test_v2_disclaimers_verbatim():
    for slug, start in (("trump-tower-jeddah", "Trump Tower Jeddah is not owned, developed or sold by The Trump "
                                               "Organization"),
                        ("marriott-residences-aida-oman", "Marriott Residences Aida, Oman are not owned, developed or "
                                                          "sold by Marriott International")):
        d = _load(f"{slug}.json")
        r, _ = dgm.parse_detail_v2(d)
        assert len(r["disclaimers"]) == 1 and r["disclaimers"][0].startswith(start)
        assert r["disclaimers"][0] in d["text"]                             # verbatim substring of the extract
        assert "Disclaimer" not in r["description_en"]


def test_no_city_aida_and_aida_rows_in_muscat():
    out = dgm.load()
    rows = out["projects"]
    assert not any((r.get("city") or "").lower() == "aida" for r in rows.values())
    fixed = {x["id"] for x in out["report"]["city_from_master_development"]}
    assert {"dg-marriott-residences", "dg-fairway-villas", "dg-the-great-escape", "dg-the-great-escape-2",
            "dg-azure-oceanfront-villas-interiors-by-fendi-casa", "dg-nickelodeon-hotels-and-resorts"} <= fixed
    for pid in fixed:
        assert rows[pid]["city"] == "Muscat" and rows[pid]["country"] == "Oman"


def test_built_db_cities_and_disclaimer_pages(con):
    assert con.execute("SELECT count(*) FROM projects WHERE lower(city) = 'aida'").fetchone()[0] == 0
    if con.execute("SELECT count(*) FROM projects WHERE id='dg-trump-tower-jeddah'").fetchone()[0]:
        rows = dict(con.execute("SELECT id, text FROM pages WHERE page_type='disclaimer'").fetchall())
        assert set(rows) >= {"darglobal-pg-disclaimer-trump-tower-jeddah"}


def test_page_vs_thirdparty_figures_kept(merged):
    rows, extras, rep = merged
    fig = extras["dg-marriott-residences"]["figures"]["text"]
    assert "September 2029 (DarGlobal project page" in fig and "Q4 2027 (" in fig
    fig = extras["dg-the-mulliner"]["figures"]["text"]
    assert "485.22" in fig and "5,222 sq.ft" in fig and "four-bedroom" in fig and "5-Bedroom" in fig


def test_source_labels_never_bare_darglobal(merged):
    rows, extras, rep = merged
    for e in extras.values():
        for url, label in e["source_labels"].items():
            if "darglobal.co.uk" not in url:
                assert label != "DarGlobal", url
            if "zawya.com/en/press-release" in url or "prnewswire" in url:
                assert label.startswith("DarGlobal (via "), url
    p = REPO / "data" / "source_labels.json"
    if p.exists():
        lab = json.loads(p.read_text(encoding="utf-8"))["labels"]
        assert all(v != "DarGlobal" for u, v in lab.items() if "darglobal.co.uk" not in u)
