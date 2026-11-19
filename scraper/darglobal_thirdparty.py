"""DarGlobal third-party facts merge. OFFLINE ONLY: reads local JSON, never fetches anything.

Input:  scraper/manual/darglobal/thirdparty/*.json, shape
        {slug, name, method, collected_at, facts: [{field, value, source_url, source_title, source_date, source_type,
        note?}]} -- public facts about DarGlobal projects taken from the LSE RNS (Dar Global PLC FY2025 results, via the
        ticker.app mirror), press and wire-hosted company releases. darglobal.* was never fetched for these.
Output: merge(projects) mutates the DarGlobal rows from darglobal_manual.load() and returns per-project extras
        (facts grouped by source, figures-by-date lines, source list) for build_dataset.py, plus a report.

Rules (data lane, binding):
- A file whose project is already a DarGlobal row (same project; reviewed name match in MATCH, fuzzy match for any
  future file) ENRICHES that row; the row keeps its DarGlobal source_url. Otherwise a new row `dg-<slug>` is created
  with source_url = the primary third-party URL (the source with most facts; ties -> most recent).
- Never invent: every fact is quoted as published, with its own source URL, title, type and date.
- Prices: only the two Trump Tower Jeddah press figures are kept, written as "press-reported on <date>: ..."; every
  price_* column stays NULL. Other price figures are excluded and listed in the report.
- Structured columns are filled only when empty and only from the most recent Dar Global PLC RNS value
  (status, handover_year, property_types), except name/city/country of new rows and the Trump Mansions country
  correction. A row whose structured record now comes from the RNS gets source_url = the RNS URL, so a
  card/field answer never cites darglobal.co.uk for a value DarGlobal did not publish; the DarGlobal URL is kept in
  dg_source_url and cited by the fact chunk for name/location.
- Conflicting figures are all kept, each with its source and date, in a 'Figures by source and date' chunk.
- Wire-hosted Dar Global releases (source_type press_release_wire) are tagged "company statement".
- A sale/asking price quoted in a headline is cut from the stored title (reported under redacted_titles).
- Empty files are skipped and reported. Facts whose curator note says "do not use" are excluded.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

try:
    from . import darglobal_manual as dgm
except ImportError:
    import darglobal_manual as dgm

ROOT = Path(__file__).resolve().parent
THIRDPARTY = ROOT / "manual" / "darglobal" / "thirdparty"

# Reviewed name matches (file slug -> existing DarGlobal row id, or None = new row). The fuzzy matcher below is used
# for any file not listed here; its suggestion for the listed files is shown in the report for comparison.
MATCH = {
    "aida": "dg-aida",
    "albert-hall-mansion": "dg-7and8-albert-hall-mansions",
    "azure-oceanfront-villas-fendi-casa-aida": "dg-azure-oceanfront-villas-interiors-by-fendi-casa",
    "d-villas-jge": "dg-d-villas-at-jumeirah-golf-estates",
    "marea": "dg-marea-interiors-by-missoni",
    "marriott-residences-aida": "dg-marriott-residences",
    "neptune": "dg-neptune-interiors-by-mouawad",
    "rayana-wadi-safar": None,            # masterplan; DarGlobal lists only its component 'Trump Mansions'
    "the-great-escape-aida": "dg-the-great-escape",
    "the-mulliner": "dg-the-mulliner",
    "tierra-viva": "dg-tierra-viva-design-inspired-by-automobili-lamborghini",
    "trump-golf-villas-aida": "dg-trump-golf-villas",
    "trump-international-golf-club-qatar": "dg-trump-international-simaisma-qatar",
    "trump-international-oman": "dg-trump-international-hotel-oman",
    "trump-plaza-jeddah": None,           # parent of the listed Trump Executive / Park Residences
    "trump-signature-villas-aida": None,  # not on the DarGlobal index under this name
    "trump-tower-jeddah": "dg-trump-tower-jeddah",
}
# A fact that names a component also listed as its own DarGlobal row is attached there too:
# (file slug, field, substring of value or '' for any) -> extra row id
CROSS = [
    ("trump-plaza-jeddah", "unit_types", "Trump Executive Residences", "dg-trump-executive-residences"),
    ("trump-plaza-jeddah", "unit_types", "Trump Park Residences", "dg-trump-park-residences"),
    ("trump-plaza-jeddah", "master_development", "Amaya", "dg-amaya"),
    ("the-great-escape-aida", "related_phase", "The Great Escape 2", "dg-the-great-escape-2"),
    ("trump-international-oman", "component_listing", "Trump Cliff Villas", "dg-trump-cliff-villas"),
    ("rayana-wadi-safar", "property_type", "Trump Mansions", "dg-trump-mansions"),
    ("rayana-wadi-safar", "location", "", "dg-trump-mansions"),
    ("rayana-wadi-safar", "country", "", "dg-trump-mansions"),
]
# the only price figures allowed into the dataset (chunk text only, never the price columns)
PRICE_ALLOW = {("trump-tower-jeddah", "average_price_per_unit"), ("trump-tower-jeddah", "price_range")}
PRICE_FIELD = re.compile(r"price", re.I)
# a sale/asking price quoted inside a headline is a price figure too; it is cut from the title (the URL stays as published)
HEADLINE_PRICE = re.compile(r"\s*\b(?:marketed at|sold for)\s+[^\s\d]?\s?\d[\d.,]*\s?(?:mln|million|m|bn)?\b", re.I)

TYPE_LABEL = {
    "rns": "regulatory announcement (Dar Global PLC FY2025 results, RNS 1301W; read via the ticker.app mirror of the "
           "LSE announcement)",
    "press_release_wire": "company statement (Dar Global release hosted on a wire/aggregator)",
    "press_supplement_developer_bylined": "company statement (developer-bylined press supplement)",
    "press": "press report",
    "trade_press": "trade press report",
    "third_party_professional": "publication by a third-party professional firm",
}
TAG = {"rns": "Dar Global PLC RNS", "press_release_wire": "company statement",
       "press_supplement_developer_bylined": "company statement", "press": "press", "trade_press": "trade press",
       "third_party_professional": "professional firm"}
FIELD_LABEL = {
    "name": "Name as reported", "jv_partner": "Joint-venture partner", "brand_partner": "Brand partner",
    "sales_launch": "Sales launch", "launch_period": "Launch period", "launch": "Launch", "launch_year": "Launch year",
    "site_area": "Site area", "project_value": "Reported total project value (not a unit price)",
    "phase_1_value": "Reported Phase 1 value (not a unit price)", "launched_units": "Launched units",
    "phase_1_composition": "Phase 1 composition", "completion": "Expected completion", "handover": "Expected handover",
    "phase_1_villas_main_contract": "Phase 1 villas main contract",
    "phase_1_infrastructure_contract": "Phase 1 infrastructure contract", "property_type": "Property type",
    "unit_types": "Unit types", "units": "Units", "built_up_area": "Built-up area", "plot_size": "Plot size",
    "hotel_keys": "Hotel keys", "hotel_opening": "Hotel opening", "main_contract_award": "Main contract award",
    "main_contractor": "Main contractor", "infrastructure_contract": "Infrastructure contract",
    "masterplan_components": "Masterplan components", "related_project": "Related project",
    "related_phase": "Related phase", "component_listing": "Component listing", "master_development": "Master development",
    "agreement_date": "Agreement date", "owner_benefit": "Owner benefit",
}
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
STOP = {"the", "by", "interiors", "interior", "design", "inspired", "automobili", "at", "of", "and", "in"}


# ---------------------------------------------------------------- helpers
def iso_date(s: str | None) -> str | None:
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s or "")
    return m.group(1) if m else None


def human_date(s: str | None) -> str:
    d = iso_date(s)
    if not d:
        return "undated on page"
    y, m, dd = d.split("-")
    return f"{int(dd)} {MONTHS[int(m) - 1]} {y}" + (" (date as displayed; uncertain)" if "uncertain" in (s or "") else "")


def short_source(f: dict) -> str:
    if f["source_type"] == "rns":
        return "Dar Global PLC RNS 1301W"
    m = re.search(r"\(([^()]*)\)\s*$", f.get("source_title") or "")
    return m.group(1) if m else (f.get("source_title") or f["source_url"])


def tokens(name: str) -> set[str]:
    name = re.sub(r"\([^)]*\)", " ", name.lower().replace("&", " and "))
    return {t for t in re.findall(r"[a-z0-9]+", name) if t not in STOP}


def fuzzy(names: list[str], rows: dict[str, dict]) -> tuple[str | None, float]:
    """Best DarGlobal row by token Jaccard over all name variants; a match needs >= 0.8 and a unique best."""
    scored = []
    for pid, r in rows.items():
        b = tokens(r.get("name_en") or "")
        s = max((len(tokens(n) & b) / len(tokens(n) | b) for n in names if tokens(n) | b), default=0.0)
        scored.append((s, pid))
    scored.sort(reverse=True)
    if not scored or scored[0][0] < 0.8 or (len(scored) > 1 and scored[1][0] == scored[0][0]):
        return None, scored[0][0] if scored else 0.0
    return scored[0][1], scored[0][0]


def date_key(f: dict) -> tuple:
    d = iso_date(f.get("source_date"))
    return (d is None, d or "", f["source_url"])


def year_from_quarter(v: str) -> int | None:
    m = re.fullmatch(r"\s*Q[1-4]\s+(\d{4})\s*", v or "")
    return int(m.group(1)) if m else None


def canon_country(v: str | None) -> str | None:
    return dgm.COUNTRY_TOKENS.get((v or "").strip().lower())


def fact_line(f: dict, slug: str) -> str:
    if (slug, f["field"]) in PRICE_ALLOW:
        what = f["field"].replace("_", " ")
        return (f"Price press-reported on {iso_date(f['source_date'])}: {what} {f['value']} "
                f"(not an official DarGlobal price list)")
    label = FIELD_LABEL.get(f["field"], f["field"].replace("_", " ").capitalize())
    return f"{label}: {f['value']}"


# ---------------------------------------------------------------- loading
def load_files(d: Path = THIRDPARTY) -> list[dict]:
    out = []
    for p in sorted(d.glob("*.json")):
        if p.name.startswith("_"):
            continue
        doc = json.loads(p.read_text(encoding="utf-8"))
        doc["_file"] = p.name
        out.append(doc)
    return out


def merge(projects: dict[str, dict], d: Path = THIRDPARTY) -> tuple[dict[str, dict], dict]:
    """Enrich / add DarGlobal rows in `projects` (in place). Returns (extras by project id, report)."""
    rep = {"files": [], "skipped_empty": [], "matches": [], "new_rows": [], "cross_attached": [], "excluded_facts": [],
           "structured_updates": [], "corrections": [], "redacted_titles": [], "sources_n": 0}
    facts_by_pid: dict[str, list[dict]] = {}
    origin: dict[str, str] = {}
    dg_rows = {k: v for k, v in projects.items()}
    for doc in load_files(d):
        slug, facts = doc["slug"], doc.get("facts") or []
        rep["files"].append(doc["_file"])
        if not facts:
            rep["skipped_empty"].append(doc["_file"])
            continue
        names = [doc["name"]] + [f["value"] for f in facts if f["field"] == "name"]
        sugg, score = fuzzy(names, dg_rows)
        if slug in MATCH:
            pid, how = MATCH[slug], "reviewed"
        else:
            pid, how = sugg, "fuzzy"
        kept = []
        for f in facts:
            f = {**f, "value": (f.get("value") or "").strip(), "_slug": slug, "_file": doc["_file"],
                 "_collected_at": doc.get("collected_at")}
            why = None
            if re.search(r"do not use", f.get("note") or "", re.I):
                why = "curator note: misprint, do not use"
            elif PRICE_FIELD.search(f["field"]) and (slug, f["field"]) not in PRICE_ALLOW:
                why = "price figure (only the two Trump Tower Jeddah press figures are kept)"
            elif dgm.CLAIM_RE.search(f["value"]):
                why = "investment-return claim"
            t2 = HEADLINE_PRICE.sub(" [price figure omitted]", f.get("source_title") or "")
            if t2 != f.get("source_title"):
                if not any(x["source_url"] == f["source_url"] for x in rep["redacted_titles"]):
                    rep["redacted_titles"].append({"source_url": f["source_url"], "title_as_published": f["source_title"],
                                                   "title_used": t2})
                f["source_title"] = t2
            if why:
                rep["excluded_facts"].append({"file": doc["_file"], "field": f["field"], "value": f["value"],
                                              "source_url": f["source_url"], "reason": why})
                continue
            kept.append(f)
        if pid is None:
            primary = primary_source(kept)
            name = next((f["value"] for f in kept if f["field"] == "name"), doc["name"])
            pid = f"dg-{dgm.slugify(name)}"
            city = next((f["value"] for f in kept if f["field"] == "city"), None)
            loc = next((f["value"] for f in kept if f["field"] == "location"), "")
            if not city and loc:
                city, _, _ = dgm.parse_location(loc)
            country = next((canon_country(f["value"]) for f in kept if f["field"] == "country"), None)
            projects[pid] = dict(id=pid, slug=dgm.slugify(name), name_en=name, city=city, country=country,
                                 brand_partner=dgm.brand_for(name), location_published=None, source_url=primary,
                                 scraped_at=doc.get("collected_at"), status=None, handover_year=None,
                                 property_types=[], unit_types=[], thirdparty_only=True)
            rep["new_rows"].append({"id": pid, "file": doc["_file"], "name": name, "city": city, "country": country,
                                    "source_url": primary})
        rep["matches"].append({"file": doc["_file"], "id": pid, "how": how if MATCH.get(slug, "x") is not None else
                               "new row", "fuzzy_suggestion": sugg, "fuzzy_score": round(score, 2)})
        origin.setdefault(pid, doc["name"])
        facts_by_pid.setdefault(pid, []).extend(kept)
        for f in kept:
            for s, fld, sub, extra in CROSS:
                if s == slug and f["field"] == fld and sub in f["value"] and extra in projects:
                    facts_by_pid.setdefault(extra, []).append({**f, "_via": doc["name"]})
                    rep["cross_attached"].append({"from": doc["_file"], "field": fld, "to": extra})

    extras: dict[str, dict] = {}
    for pid in sorted(facts_by_pid):
        row, fs = projects[pid], sorted(facts_by_pid[pid], key=date_key)
        row["dg_source_url"] = None if row.get("thirdparty_only") else row["source_url"]
        # structured columns: only when empty, only from the most recent RNS value. When any is filled, the row's
        # source_url becomes that RNS URL (the source of its structured record); the DarGlobal URL the name/location
        # came from stays in dg_source_url and is cited by the project's fact chunk.
        rns = [f for f in fs if f["source_type"] == "rns" and not f.get("_via")]
        n_upd = len(rep["structured_updates"])
        pt = [f["value"] for f in rns if f["field"] == "property_type"]
        if not row.get("property_types") and pt:
            row["property_types"] = pt[-1:]
            rep["structured_updates"].append({"id": pid, "column": "property_types", "value": pt[-1:],
                                              "source_url": rns[-1]["source_url"]})
        st = [f for f in rns if f["field"] == "status"]
        if not row.get("status") and st:
            row["status"] = st[-1]["value"]
            rep["structured_updates"].append({"id": pid, "column": "status", "value": row["status"],
                                              "source_url": st[-1]["source_url"]})
        comp = [f for f in rns if f["field"] == "completion" and year_from_quarter(f["value"])]
        if not row.get("handover_year") and comp:
            row["handover_year"] = year_from_quarter(comp[-1]["value"])
            row["handover_source"] = f"{short_source(comp[-1])}, {human_date(comp[-1]['source_date'])}: {comp[-1]['value']}"
            rep["structured_updates"].append({"id": pid, "column": "handover_year", "value": row["handover_year"],
                                              "source_url": comp[-1]["source_url"]})
        if len(rep["structured_updates"]) > n_upd:
            row["source_url"] = rns[-1]["source_url"]
        if not row.get("country"):
            c = next((canon_country(f["value"]) for f in fs if f["field"] == "country" and canon_country(f["value"])), None)
            if c:
                row["country"] = c
                src = next(f for f in fs if f["field"] == "country")
                rep["corrections"].append({
                    "id": pid, "column": "country", "from": None, "to": c,
                    "why": f"DarGlobal publishes the location as '{row.get('location_published')}' (no country token); "
                           f"third-party sources place Rayana in Wadi Safar, Diriyah, Riyadh, {c}",
                    "source_url": src["source_url"]})
        extras[pid] = build_extra(row, fs, origin.get(pid))
    for nr in rep["new_rows"]:
        nr["source_url"] = projects[nr["id"]]["source_url"]
    rep["sources_n"] = len({f["source_url"] for fs in facts_by_pid.values() for f in fs})
    rep["projects_with_facts"] = sorted(facts_by_pid)
    return extras, rep


def primary_source(fs: list[dict]) -> str:
    n: dict[str, int] = {}
    last: dict[str, str] = {}
    for f in fs:
        n[f["source_url"]] = n.get(f["source_url"], 0) + 1
        last[f["source_url"]] = max(last.get(f["source_url"], ""), iso_date(f["source_date"]) or "")
    return sorted(n, key=lambda u: (-n[u], -int((last[u] or "0").replace("-", "")), u))[0]


def build_extra(row: dict, fs: list[dict], tp_name: str | None) -> dict:
    """Group facts by source (one chunk each, own source_url), figures by date, and the source list."""
    slug_of = {f["_slug"] for f in fs}
    by_src: dict[str, list[dict]] = {}
    for f in fs:
        by_src.setdefault(f["source_url"], []).append(f)
    sources = sorted(by_src, key=lambda u: date_key(by_src[u][0]))
    src_chunks = []
    for u in sources:
        g, f0 = by_src[u], by_src[u][0]
        lines = []
        for f in g:
            ln = fact_line(f, f["_slug"])
            if f.get("_via"):
                ln += f" (reported about {f['_via']})"
            if f.get("note"):
                ln += f" [curator note: {f['note']}]"
            lines.append(ln + ".")
        src_chunks.append({
            "source_url": u, "source_title": f0["source_title"], "source_type": f0["source_type"],
            "source_date": f0["source_date"], "short": short_source(f0), "scraped_at": f0["_collected_at"],
            "text": (f"Source: {f0['source_title']}. Type: {TYPE_LABEL.get(f0['source_type'], f0['source_type'])}. "
                     f"Date: {human_date(f0['source_date'])}. URL: {u}. Reported facts: " + " ".join(lines))})
    # figures by source and date: every field reported by two or more sources (all values kept)
    by_field: dict[str, list[dict]] = {}
    for f in fs:
        if f["field"] != "name" or len({x["value"] for x in fs if x["field"] == "name"}) > 1:
            by_field.setdefault(f["field"], []).append(f)
    fig_lines = []
    for fld in sorted(by_field):
        g = by_field[fld]
        if len({x["source_url"] for x in g}) < 2:
            continue
        parts = [f"{x['value']} ({short_source(x)}, {human_date(x['source_date'])})" for x in g]
        label = FIELD_LABEL.get(fld, fld.replace("_", " ").capitalize())
        ln = f"{label}: reported as " + (", ".join(parts[:-1]) + " and " + parts[-1] if len(parts) > 1 else parts[0])
        if (fld == "status" and row.get("status") and any(x["source_type"] == "rns" and x["value"] == row["status"]
                                                          for x in g)) or (fld == "completion" and row.get("handover_source")):
            ln += "; the structured record uses the most recent RNS value"
        fig_lines.append(ln + ".")
    rns_url = next((f["source_url"] for f in reversed(fs) if f["source_type"] == "rns"), None)
    dated = [u for u in sources if iso_date(by_src[u][0]["source_date"])]
    latest = (dated or sources)[-1]
    # the figures chunk cites the RNS (the value structured columns follow) or else the most recent dated source;
    # every individual value in it names its own source and date inline
    figures = {"source_url": rns_url or latest, "text": " ".join(fig_lines)} if fig_lines else None
    src_list = [f"{by_src[u][0]['source_title']} - {TYPE_LABEL.get(by_src[u][0]['source_type'])}, "
                f"{human_date(by_src[u][0]['source_date'])}: {u}" for u in sources]
    tags = sorted({TAG.get(f["source_type"], f["source_type"]) for f in fs})
    return {"thirdparty_name": tp_name, "files": sorted({f["_file"] for f in fs}), "slugs": sorted(slug_of),
            "facts_n": len(fs), "sources": sources, "source_chunks": src_chunks, "figures": figures,
            "source_list": src_list, "source_tags": tags,
            "primary_source": row["source_url"] if row.get("thirdparty_only") else (rns_url or latest),
            "collected_at": fs[0]["_collected_at"]}


if __name__ == "__main__":
    base = dgm.load()["projects"]
    ex, rp = merge(base)
    print(json.dumps(rp, indent=1, ensure_ascii=False))
