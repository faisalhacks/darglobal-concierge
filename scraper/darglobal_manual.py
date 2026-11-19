"""DarGlobal manual-collection parser. OFFLINE ONLY: never fetches darglobal.*.

Input:  scraper/manual/darglobal/extracts/*.json  (pages the owner opened in their own Chrome at human pace;
        each file carries url, headings, text, images, jsonld, collected_at, method).
Output: plain dicts consumed by scraper/build_dataset.py:
        - one project row per name on https://darglobal.co.uk/projects (index-only rows)
        - detail rows (upgrades of index rows) for every other collected project page
        - a report (unresolved countries, excluded sections, text repairs, area notes)

Rules (data lane, binding):
- No prices: DarGlobal pages publish none, so price_* stay NULL.
- Country only from an explicit token map; unresolved -> None and listed in the report. No guessing.
- The 'WHY INVEST' section (yield / capital-growth / 'doubled market price' claims), investment FAQ entries,
  'OTHER PROJECTS' cross-sell, register-interest and cookie boilerplate are excluded from descriptions and chunks.
- lat/lng only from JSON-LD GeoCoordinates. Images: original cdn.darglobal.co.uk URLs only, max 6.
- JSON-LD founder/person/contactPoint nodes are never read (only GeoCoordinates and amenityFeature names are used).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXTRACTS = ROOT / "manual" / "darglobal" / "extracts"
INDEX_URL = "https://darglobal.co.uk/projects"
CONTACT_URL = "https://darglobal.co.uk/get-in-touch"
CDN = "https://cdn.darglobal.co.uk/"
SQFT_TO_M2 = 0.092903

# explicit token map (plus the page's own location filter list, which is checked against it)
COUNTRY_TOKENS = {
    "uae": "United Arab Emirates", "united arab emirates": "United Arab Emirates",
    "ksa": "Saudi Arabia", "saudi arabia": "Saudi Arabia",
    "oman": "Oman", "qatar": "Qatar", "spain": "Spain",
    "united kingdom": "United Kingdom", "england": "United Kingdom", "uk": "United Kingdom",
}
COUNTRY_AR = {"United Arab Emirates": "الإمارات العربية المتحدة", "Saudi Arabia": "المملكة العربية السعودية",
              "Oman": "عُمان", "Qatar": "قطر", "Spain": "إسبانيا", "United Kingdom": "المملكة المتحدة"}
# spelling/abbreviation normalisation of published city strings (no inference of a city that is not written)
CITY_ALIASES = {"rak": "Ras Al Khaimah", "jeddha": "Jeddah"}
# master-development names that appear in location strings but are not cities ('AIDA | Oman', 'AIDA, Muscat, Oman'):
# never stored as a city; the raw published location string is kept verbatim in location_published.
NOT_CITIES = {"aida"}

# brand partner only when the published name contains it
BRANDS = [("aston martin", "Aston Martin"), ("pagani", "Pagani"), ("missoni", "Missoni"), ("elie saab", "Elie Saab"),
          ("fendi casa", "Fendi Casa"), ("lamborghini", "Lamborghini"), ("marriott", "Marriott"),
          ("mouawad", "Mouawad"), ("nickelodeon", "Nickelodeon"), ("mulliner", "Mulliner"), ("trump", "Trump")]

LABELS = ["Property Type", "Unit Type", "Units", "Status", "Area (SQFT)", "Area (SQM)", "Location", "Featuring"]
LABEL_RE = re.compile(r"(?i:(" + "|".join(re.escape(l) for l in sorted(LABELS, key=len, reverse=True)) + r"))(?=[A-Z0-9])")

EXCLUDE_H2 = [  # (regex on H2 heading, reason)
    (r"why\s*invest", "WHY INVEST (investment / yield / capital-growth claims)"),
    (r"other\s*projects", "OTHER PROJECTS (cross-sell cards for other projects)"),
    (r"register\s*your\s*interest", "REGISTER YOUR INTEREST (lead form boilerplate)"),
    (r"value\s*our\s*privacy|cookie", "cookie banner"),
]
FAQ_EXCLUDE = re.compile(r"invest|golden visa|residency|register interest|enquir|property values|\bprice|how do i (buy|register)",
                         re.I)
# any sentence still carrying an investment-return claim is dropped
CLAIM_RE = re.compile(r"\b(yields?|high-yield|returns?|doubl(?:ed|ing|e)|capital (?:appreciation|values?|growth)|"
                      r"price premiums?|rental premiums?|ROI)\b", re.I)
UI_NOISE = re.compile(r"Download Brochure|Book Unit|BOOK UNIT|Progress Update|Choose your residence|360 View|"
                      r"View All Images|View [Aa]ll Projects|Show more|\[phone\]|\[name removed\]|\[email\]|"
                      r"To activate drag with keyboard.*?press Escape\.")


# ---------------------------------------------------------------- small helpers
def repair(s: str | None, log: list | None = None) -> str:
    """Repair U+FFFD left by the page's encoding: apostrophes, a few known words, dashes. Logged."""
    if not s:
        return s or ""
    if "�" not in s:
        return s
    n0 = s.count("�")
    s = re.sub(r"(?<=[A-Za-z])�(?=(?:s|re|ll|t|ve|d|m)\b)", "'", s)
    s = re.sub(r"\s�\s", " – ", s)
    s = s.replace("�", " ")
    if log is not None:
        log.append(n0)
    return s


def slugify(name: str) -> str:
    s = name.lower().replace("&", "and")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower().replace("&", "and"))


def iso(ts: str) -> str:
    """'2026-11-19T09:48:05.015Z' -> '2026-11-19T09:48:05+00:00' (same format as the Wasalt snapshots)."""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat(timespec="seconds")
    except ValueError:
        return ts


def parse_location(loc: str) -> tuple[str | None, str | None, bool]:
    """'Al Marjan Island, RAK, UAE' -> ('Ras Al Khaimah', 'United Arab Emirates', True). Country via token map only."""
    parts = [p.strip() for p in re.split(r"\s*[,|]\s*", loc or "") if p.strip()]
    if not parts:
        return None, None, False
    country = COUNTRY_TOKENS.get(parts[-1].lower())
    rest = parts[:-1] if country else parts
    rest = [p for p in rest if p.lower() not in NOT_CITIES]
    city = rest[-1] if rest else None
    if city:
        city = CITY_ALIASES.get(city.lower(), city)
    return city, country, country is not None


def brand_for(name: str) -> str | None:
    low = name.lower()
    for tok, brand in BRANDS:
        if re.search(r"\b" + re.escape(tok) + r"\b", low):
            return brand
    if re.match(r"w\s+residences\b", low):
        return "W Hotels"
    return None


def headings(d: dict, level: str) -> list[str]:
    return [h.split(":", 1)[1].strip() for h in d.get("headings") or [] if h.startswith(level + ":")]


def jsonld_blob(d: dict) -> str:
    j = d.get("jsonld")
    if isinstance(j, dict) and isinstance(j.get("truncated"), str):
        return j["truncated"]
    return json.dumps(j or [], ensure_ascii=False)


def sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|(?<=[a-z][.!?])(?=[A-Z])", text) if s.strip()]


def drop_claims(text: str) -> tuple[str, int]:
    keep, dropped = [], 0
    for s in sentences(text):
        if CLAIM_RE.search(s):
            dropped += 1
        else:
            keep.append(s.strip())
    return " ".join(keep), dropped


CAMEL_KEEP = re.compile(r"DarGlobal|McLaren|YouTube|LinkedIn|WhatsApp")


def unglue(text: str) -> str:
    """Re-insert the space lost between adjacent page blocks ('resortsLocated', 'Rooms24/7'), keeping real
    camel-case names such as DarGlobal intact."""
    keep = {m.start() + i for m in CAMEL_KEEP.finditer(text) for i in range(1, len(m.group(0)))}
    out = []
    for i, ch in enumerate(text):
        if i and i not in keep:
            prev = text[i - 1]
            nxt = text[i + 1] if i + 1 < len(text) else ""
            if (prev in "abcdefghijklmnopqrstuvwxyz.!?)" and ch.isupper() and nxt.islower()) or \
                    (prev in "abcdefghijklmnopqrstuvwxyz" and ch.isdigit()):
                out.append(" ")
        out.append(ch)
    return "".join(out)


def clean(text: str) -> str:
    text = UI_NOISE.sub(" ", text)
    text = re.sub(r"\d{1,3}\.\d{4,}\d*\.\d{4,}", " ", text)       # concatenated map coordinates
    return re.sub(r"\s+", " ", unglue(text)).strip()


def find_heading(text: str, heading: str, start: int) -> int:
    """First occurrence of an H2/H3 at or after start, case-insensitive, glued to the next block (next char upper/digit)."""
    rx = re.compile(r"(?i:" + re.escape(heading) + r")(?=[A-Z0-9\"'“(]|$)")
    m = rx.search(text, start)
    return m.start() if m else -1


# ---------------------------------------------------------------- index page
def parse_index(d: dict) -> tuple[list[dict], dict]:
    rep = {"url": d["url"], "h3_names": 0, "missing_in_text": [], "location_filter_list": [], "unresolved": []}
    names, started = [], False
    for h in d.get("headings") or []:
        if h.startswith("H2:"):
            if started or re.search(r"register", h, re.I):
                break
            started = True
            continue
        if h.startswith("H3:") and started:
            names.append(h.split(":", 1)[1].strip())
    rep["h3_names"] = len(names)
    repairs: list = []
    text = repair(d.get("text") or "", repairs)
    low = text.lower()
    cur = low.find("all locations")
    cur = cur + len("all locations") if cur >= 0 else 0
    # the page's own location filter list ('United Arab EmiratesSpainQatar...')
    toks = sorted(COUNTRY_TOKENS, key=len, reverse=True)
    while True:
        t = next((t for t in toks if low.startswith(t, cur) and len(t) > 3), None)
        if not t:
            break
        rep["location_filter_list"].append(text[cur:cur + len(t)])
        cur += len(t)
    rows, prev = [], None
    sa = iso(d["collected_at"])
    for name in names:
        nl = name.lower()
        pos = low.find(nl, cur)
        while pos >= 0 and low[pos + len(nl):pos + len(nl) + 1] == ",":   # 'Amaya, Jeddah' is a location, not the name
            pos = low.find(nl, pos + 1)
        if pos < 0:
            rep["missing_in_text"].append(name)
            continue
        seg = text[cur:pos]
        bounds = [m.start() for m in re.finditer(r"(?<=[a-z])(?=[A-Z0-9])", seg)]
        caption, loc = (seg[:bounds[-1]].strip(), seg[bounds[-1]:].strip()) if bounds else ("", seg.strip())
        if caption and prev is not None:
            prev["card_caption"] = caption
        published = text[pos:pos + len(nl)].strip()
        city, country, ok = parse_location(loc)
        row = dict(id=f"dg-{slugify(published)}", slug=slugify(published), name_en=published, city=city, country=country,
                   brand_partner=brand_for(published), location_published=loc, source_url=INDEX_URL, scraped_at=sa)
        if not ok:
            rep["unresolved"].append({"id": row["id"], "name": published, "location_published": loc})
        rows.append(row)
        prev = row
        cur = pos + len(nl)
    return rows, rep


# ---------------------------------------------------------------- project detail page
def split_sections(text: str, h2s: list[str]) -> list[tuple[str, str]]:
    out, cur, name = [], 0, "intro"
    for h in h2s:
        p = find_heading(text, h, cur)
        if p < 0:
            continue
        out.append((name, text[cur:p]))
        name, cur = h, p + len(h)
    out.append((name, text[cur:]))
    return out


def parse_labels(block: str) -> dict[str, str]:
    ms = list(LABEL_RE.finditer(block))
    out = {}
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(block)
        key = next(l for l in LABELS if l.lower() == m.group(1).lower())
        out.setdefault(key, block[m.end():end].strip())
    return out


def rng(v: str) -> tuple[float, float] | None:
    nums = [float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*(?:\.\d+)?", v or "")]
    return (min(nums), max(nums)) if nums else None


def parse_detail(d: dict, sitewide_imgs: set[str], index_imgs: set[str]) -> tuple[dict, dict]:
    repairs: list = []
    text = repair(d.get("text") or "", repairs)
    h1 = repair(next(iter(headings(d, "H1")), "") or "")
    h2s = [repair(h) for h in headings(d, "H2")]
    rep = {"url": d["url"], "excluded_sections": [], "faq_excluded": [], "claim_sentences_dropped": 0,
           "text_repairs": sum(repairs)}
    low = text.lower()
    hpos = low.find(h1.lower())
    name_pub = text[hpos:hpos + len(h1)] if hpos >= 0 else h1.title()
    sections = split_sections(text, h2s)
    intro = sections[0][1]
    # description = first paragraph after the 'Name City | Country' line, before the label block
    short = " ".join(name_pub.split()[:2]).lower()
    bar = intro.find("|")
    ds = intro.lower().find(short, bar + 1) if bar >= 0 else -1
    lab = LABEL_RE.search(intro, ds if ds >= 0 else 0)
    title_loc = clean(intro[hpos + len(h1):ds]) if (hpos >= 0 and ds > hpos) else ""
    desc = clean(intro[ds:lab.start() if lab else len(intro)]) if ds >= 0 else ""
    if not desc:
        desc = (d.get("meta") or {}).get("description") or ""
    desc, nd = drop_claims(desc)
    rep["claim_sentences_dropped"] += nd
    labels = parse_labels(intro[lab.start():]) if lab else {}
    blob = jsonld_blob(d)
    if "Status" not in labels:
        m = re.search(r'"name":\s*"Status",\s*"value":\s*"([^"]+)"', blob)
        if m:
            labels["Status"] = m.group(1)
    # geo only from JSON-LD GeoCoordinates
    lat = lng = None
    m = re.search(r'"@type":\s*"GeoCoordinates",\s*"latitude":\s*"?(-?\d+\.\d+)"?,\s*"longitude":\s*"?(-?\d+\.\d+)', blob)
    if m:
        lat, lng = float(m.group(1)), float(m.group(2))
    amen = list(dict.fromkeys(repair(a).strip() for a in
                              re.findall(r'"@type":\s*"LocationFeatureSpecification",\s*"name":\s*"([^"]+)"', blob)))
    kept: list[tuple[str, str]] = []
    for h, body in sections[1:]:
        reason = next((r for rx, r in EXCLUDE_H2 if re.search(rx, h, re.I)), None)
        if reason:
            rep["excluded_sections"].append(f"{h}: {reason}")
            continue
        if re.match(r"frequently asked", h, re.I):
            qs = [repair(q) for q in faq_questions(d, h)]
            cur, found = 0, []
            for q in qs:
                p = find_heading(body, q, cur) if q else -1
                if p < 0:
                    p = body.lower().find(q.lower(), cur)
                if p >= 0:
                    found.append((q, p))
                    cur = p + len(q)
            for i, (q, p) in enumerate(found):
                end = found[i + 1][1] if i + 1 < len(found) else len(body)
                ans = clean(body[p + len(q):end])
                if FAQ_EXCLUDE.search(q):
                    rep["faq_excluded"].append(q)
                    continue
                ans, nd = drop_claims(ans)
                rep["claim_sentences_dropped"] += nd
                if ans:
                    qq = q if q.endswith("?") else q + "?"
                    kept.append(("FAQ", f"{qq} {ans}"))
            continue
        body = clean(body)
        if re.match(r"amenities", h, re.I):
            if not amen:   # fall back to the glued list in the section text
                amen = [a.strip() for a in re.split(r"(?<=[a-z])(?=[A-Z0-9])", re.sub(r"^.*?[.!]\s*", "", body))
                        if 2 < len(a.strip()) < 70]
            cut = body.lower().find(amen[0].lower()) if amen else -1
            lead = (body[:cut] if cut > 0 else "").strip().rstrip(".")
            body = (lead + ". " if lead else "") + ("Amenities: " + ", ".join(amen) + "." if amen else "")
        # cut the trailing map label ('Da Vinci TowerDubai, United Arab Emirates') at the end of location sections
        tail = body.lower().rfind(short)
        if tail > 40 and len(body) - tail < 90:
            body = body[:tail].strip()
        body, nd = drop_claims(body)
        rep["claim_sentences_dropped"] += nd
        if body:
            kept.append((section_label(h), body))
    # area: published SQM label > sqm stated in text > SQFT label converted
    area_pub = "; ".join(f"{k}: {labels[k]}" for k in ("Area (SQM)", "Area (SQFT)") if k in labels)
    amin = amax = None
    area_src = None
    if "Area (SQM)" in labels and rng(labels["Area (SQM)"]):
        amin, amax = rng(labels["Area (SQM)"])
        area_src = "label Area (SQM)"
    sqm_m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(?:to|-|–)\s*(\d[\d,]*(?:\.\d+)?)\s*(?:sq\.?\s?m\b|sqm\b)", desc) or \
        re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(?:to|-|–)\s*(\d[\d,]*(?:\.\d+)?)\s*(?:sq\.?\s?m\b|sqm\b)",
                  " ".join(t for _, t in kept))
    sqm_phrase = sqm_m.group(0) if sqm_m else None
    if amin is None and sqm_m:
        amin, amax = float(sqm_m.group(1).replace(",", "")), float(sqm_m.group(2).replace(",", ""))
        area_src = "text sqm"
    if amin is None and "Area (SQFT)" in labels and rng(labels["Area (SQFT)"]):
        a, b = rng(labels["Area (SQFT)"])
        amin, amax = round(a * SQFT_TO_M2, 1), round(b * SQFT_TO_M2, 1)
        area_src = "label Area (SQFT) x 0.092903"
    if sqm_phrase and area_src != "text sqm":
        rep["area_note"] = f"text states '{sqm_phrase}', used {area_src} ({amin:g}-{amax:g} m2)"
    elif area_src:
        rep["area_note"] = f"used {area_src}"
    hy = None
    m = re.search(r"(?:handover|completion)\s+(?:is\s+)?scheduled\s+for\s+(?:[A-Z][a-z]+\s+)?(\d{4})",
                  " ".join(t for _, t in kept))
    if m:
        hy = int(m.group(1))
    # images: page's JSON-LD images first, then the rest; drop the generic background, site-wide banners and
    # other projects' index cards. Max 6, original URLs only.
    # When the page's JSON-LD declares >= 3 images, only those are used (the page's own photos); otherwise the
    # extract's image list minus site-wide banners and other projects' index-card images.
    def ok_img(u: str) -> bool:
        return (u.startswith(CDN) and "projects_bg" not in u and "logo" not in u.lower()
                and bool(re.search(r"\.(webp|jpe?g|png)$", u, re.I)))
    ld_imgs = list(dict.fromkeys(u for u in re.findall(r'https://cdn\.darglobal\.co\.uk/[^"\s\\]+', blob) if ok_img(u)))
    if len(ld_imgs) >= 3:
        imgs = ld_imgs
        rep["image_rule"] = "JSON-LD images of the page"
    else:
        imgs = list(dict.fromkeys(u for u in ld_imgs + list(d.get("images") or [])
                                  if ok_img(u) and (u in ld_imgs or (u not in sitewide_imgs and u not in index_imgs))))
        rep["image_rule"] = "extract images minus site-wide banners and other projects' cards"
    imgs = imgs[:6]
    status = labels.get("Status", "").strip() or None
    row = dict(name_en=name_pub.strip(), h1=h1, title_location=title_loc, lat=lat, lng=lng,
               property_types=[labels["Property Type"].strip()] if labels.get("Property Type") else [],
               unit_types=[(labels.get("Unit Type") or labels.get("Units")).strip()]
               if (labels.get("Unit Type") or labels.get("Units")) else [],
               status=status, area_min_m2=amin, area_max_m2=amax, amenities=amen, handover_year=hy,
               description_en=desc or None, image_urls=imgs, source_url=d["url"], scraped_at=iso(d["collected_at"]),
               brand_partner=brand_for(name_pub), sections=kept, area_published=area_pub, area_text_sqm=sqm_phrase,
               featuring=labels.get("Featuring"), location_label=labels.get("Location"), method=d.get("method"))
    return row, rep


def faq_questions(d: dict, faq_h2: str) -> list[str]:
    out, on = [], False
    for h in d.get("headings") or []:
        if h.startswith("H2:"):
            on = h.split(":", 1)[1].strip() == faq_h2 or repair(h.split(":", 1)[1].strip()) == faq_h2
            continue
        if on and h.startswith("H3:"):
            out.append(h.split(":", 1)[1].strip())
    return out


def section_label(h: str) -> str:
    low = h.lower()
    if "photo gallery" in low:
        return "Gallery overview"
    if "key features" in low:
        return "Key features"
    if "amenities" in low:
        return "Amenities"
    if low in ("location", "at the heart of it all"):
        return "Location"
    return h.title()


def is_detail(d: dict) -> bool:
    return bool(headings(d, "H1")) and bool(LABEL_RE.search(d.get("text") or ""))


# ---------------------------------------------------------------- entry point
def load(extract_dir: Path = EXTRACTS) -> dict:
    """Parse every extract. Returns {'projects': {id: row}, 'report': {...}}. Deterministic (sorted file order)."""
    files = sorted(p for p in extract_dir.glob("*.json") if not p.name.startswith("_"))
    docs = []
    for p in files:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            docs.append((p, None, str(e)))
            continue
        docs.append((p, d, None))
    report = {"extract_files": [p.name for p in files], "method": None, "index": [], "detail": [],
              "skipped": [], "darglobal_unresolved": [], "detail_slugs": []}
    projects: dict[str, dict] = {}
    by_norm: dict[str, str] = {}
    index_imgs: set[str] = set()
    for p, d, err in docs:
        if err or d is None:
            report["skipped"].append({"file": p.name, "reason": f"unreadable: {err}"})
            continue
        report["method"] = report["method"] or d.get("method")
        if d.get("blocked"):
            report["skipped"].append({"file": p.name, "reason": "extract marked blocked"})
            continue
        if d["url"].rstrip("/") == INDEX_URL or d["url"].startswith(INDEX_URL + "/"):
            rows, rep = parse_index(d)
            index_imgs.update(d.get("images") or [])
            report["index"].append(rep)
            report["darglobal_unresolved"] += rep["unresolved"]
            for r in rows:
                if r["id"] in projects:
                    continue
                projects[r["id"]] = r
                by_norm[norm_name(r["name_en"])] = r["id"]
    detail_docs = [(p, d) for p, d, err in docs if d is not None and not err and not d.get("blocked")
                   and not (d["url"].rstrip("/") == INDEX_URL or d["url"].startswith(INDEX_URL + "/"))]
    counts: dict[str, int] = {}
    for _, d in detail_docs:
        for u in set(d.get("images") or []):
            counts[u] = counts.get(u, 0) + 1
    sitewide = {u for u, c in counts.items() if c >= 3}
    for p, d in detail_docs:
        if not is_detail(d):
            report["skipped"].append({"file": p.name, "reason": "not a project detail page (no H1 + fact labels); "
                                                                "not ingested"})
            continue
        row, rep = parse_detail(d, sitewide, index_imgs)
        pid = by_norm.get(norm_name(row["h1"])) or by_norm.get(norm_name(row["name_en"]))
        if pid:
            base = projects[pid]
            rep["matched_index_row"] = pid
        else:
            pid = f"dg-{slugify(row['name_en'])}"
            city, country, ok = parse_location(row["title_location"] or row["location_label"] or "")
            base = dict(id=pid, slug=slugify(row["name_en"]), name_en=row["name_en"], city=city, country=country,
                        location_published=row["title_location"])
            rep["matched_index_row"] = None
            if not ok:
                report["darglobal_unresolved"].append({"id": pid, "name": row["name_en"],
                                                       "location_published": base["location_published"]})
            projects[pid] = base
            by_norm[norm_name(row["name_en"])] = pid
        name_keep = base.get("name_en") or row["name_en"]
        base.update({k: v for k, v in row.items() if k not in ("h1", "name_en")})
        base["name_en"] = name_keep
        if not base.get("city") and row["location_label"]:
            base["city"], _, _ = parse_location(row["location_label"])
        rep["id"] = pid
        report["detail"].append(rep)
        report["detail_slugs"].append(pid)
    report["detail_slugs"].sort()
    return {"projects": projects, "report": report}


if __name__ == "__main__":
    out = load()
    for pid, r in sorted(out["projects"].items()):
        print(pid, "|", r.get("name_en"), "|", r.get("city"), "|", r.get("country"), "|",
              "page" if r.get("source_url") != INDEX_URL else "index")
    print(json.dumps(out["report"], indent=1, ensure_ascii=False))
