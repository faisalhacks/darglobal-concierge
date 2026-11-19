#!/usr/bin/env python3
"""Multi-turn conversation eval (quality round). Drives POST /api/chat/stream with history and last_entities.

  # server first (keys loaded in-process from .env, never printed):
  python evals/serve_eval.py nvidia 8020
  # then the run (cap is mandatory against a live server; env EVAL_MAX_LLM_CALLS or --max-llm-calls):
  EVAL_MAX_LLM_CALLS=120 python evals/run_conversations.py --label before --base-url http://localhost:8020 --probe-nvidia
  python evals/run_conversations.py --list                      # validate the set, no network
  python evals/run_conversations.py --label fix1 --only c05,c07 --max-llm-calls 30 ...

Per turn it records answer, trace, cards, chips, sources, the check verdicts and (optional) a Gemini 1-5 judge.
Writes evals/results/conv_<label>.json after every conversation, so a stopped run keeps what was measured.

LLM budget rules
  * The cap counts the server's own per-request counter (trace.llm_calls, reconciled with /api/meta llm.budget.used).
    A turn with no trace counts as 1. The run stops before a turn when the count has reached the cap.
  * Stop on quota: a quota/credit/402 style degradation stops the run at once; a rate-limit degradation (429) three turns
    in a row stops it. Recorded as "NVIDIA free limit reached at N calls". Never retried in a loop.
  * Rate-limit headers: --probe-nvidia makes one GET /v1/models (no completion, no tokens) before and after and records
    any rate-limit/quota headers it returns. The key is read from the environment and is never printed or stored.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import runner as R  # noqa: E402  (chat_stream, Reply, DB, number helpers: the same parsing as the 177-case suite)
from envload import load_env  # noqa: E402

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("PyYAML required")

ROOT = HERE.parent
DEFAULT_CONV = HERE / "conversations_30.yaml"
RESULTS = HERE / "results"
NVIDIA_MODELS_URL = "https://integrate.api.nvidia.com/v1/models"
GEMINI_MODEL = os.getenv("EVAL_JUDGE_GEMINI_MODEL", "gemini-2.5-flash-lite")

COUNTRIES = {  # canonical English name -> aliases (word-bounded for Latin, plain for Arabic)
    "Saudi Arabia": ["saudi arabia", "saudi", "ksa", "السعودية", "المملكة العربية السعودية"],
    "United Arab Emirates": ["united arab emirates", "uae", "emirates", "الإمارات", "الامارات"],
    "Oman": ["oman", "sultanate of oman", "عمان", "سلطنة عمان", "عُمان"],
    "Qatar": ["qatar", "قطر"],
    "Spain": ["spain", "إسبانيا", "اسبانيا"],
    "United Kingdom": ["united kingdom", "uk", "britain", "england", "بريطانيا", "المملكة المتحدة"],
    "France": ["france", "فرنسا"],
    "Egypt": ["egypt", "مصر"],
    "Kuwait": ["kuwait", "الكويت"],
    "Bahrain": ["bahrain", "البحرين"],
    "Turkey": ["turkey", "türkiye", "تركيا"],
    "Italy": ["italy", "إيطاليا"],
    "Germany": ["germany", "ألمانيا"],
    "Jordan": ["jordan", "الأردن"],
}
CITY_COUNTRY = {"riyadh": "Saudi Arabia", "jeddah": "Saudi Arabia", "makkah": "Saudi Arabia", "madinah": "Saudi Arabia",
                "dammam": "Saudi Arabia", "al khobar": "Saudi Arabia", "muscat": "Oman", "dubai": "United Arab Emirates",
                "ras al khaimah": "United Arab Emirates", "doha": "Qatar", "london": "United Kingdom", "paris": "France",
                "cairo": "Egypt", "الرياض": "Saudi Arabia", "جدة": "Saudi Arabia", "الدمام": "Saudi Arabia",
                "مسقط": "Oman", "دبي": "United Arab Emirates", "الدوحة": "Qatar", "لندن": "United Kingdom"}
BLOG_RE = re.compile(r"(/blog|/blogs|/terms|/legal|/privacy|/policy|/conditions?|terms[-_ ]of|privacy|مدونة|الشروط)", re.I)
QUOTA_RE = re.compile(r"(quota|credit|insufficient|payment|billing|\b402\b|free limit|exceeded your)", re.I)
RATE_RE = re.compile(r"(rate[_ -]?limit|\b429\b|too many requests|rate_limited)", re.I)
HEADER_RE = re.compile(r"(rate|limit|remaining|reset|retry|quota|credit)", re.I)
DATE_RE = re.compile(r"(as of|updated|\b20\d\d\b|محدث|تاريخ|آخر تحديث)", re.I)


# ------------------------------------------------------------------ helpers
def mentions(text: str, aliases) -> bool:
    low = text.lower()
    for a in aliases:
        if re.search(r"[a-z]", a):
            if re.search(r"(?<![a-z])" + re.escape(a) + r"(?![a-z])", low):
                return True
        elif a in text:
            return True
    return False


def countries_in(text: str) -> set[str]:
    return {c for c, al in COUNTRIES.items() if mentions(text, al)} | \
           {CITY_COUNTRY[k] for k in CITY_COUNTRY if mentions(text, [k])}


def sentences(text: str):
    return [s for s in re.split(r"(?<=[.!?؟\n])\s+", text) if s.strip()]


class Facts:
    """Read-only lookups on the store for card ids (price, country, city, type, names)."""

    def __init__(self, db: R.DB):
        self.db = db

    def row(self, i):
        if not self.db.ok or not i:
            return None
        return self.db.one("SELECT * FROM projects WHERE id=?", (i,)) or self.db.one("SELECT * FROM listings WHERE id=?", (i,))

    def is_project(self, i):
        return bool(self.db.ok and i in self.db.project_ids)

    def price(self, i):
        r = self.row(i)
        if not r:
            return None
        v = r.get("price_from_amount") if "price_from_amount" in r else r.get("price_amount")
        return float(v) if v else None

    def country(self, i):
        r = self.row(i)
        if not r:
            return None
        if r.get("country"):
            return r["country"]
        return CITY_COUNTRY.get(str(r.get("city") or "").lower())  # listings are Wasalt KSA

    def city(self, i):
        r = self.row(i)
        return r.get("city") if r else None

    def site(self, i):
        r = self.row(i)
        if not r:
            return None
        return r.get("site") or "Wasalt"

    def ptype(self, i):
        r = self.row(i)
        if not r:
            return ""
        return (str(r.get("property_types") or "") + " " + str(r.get("property_type") or "") + " " + str(r.get("title") or "")).lower()

    def names(self, i):
        r = self.row(i)
        if not r:
            return []
        return [str(n).lower() for n in (r.get("name_en"), r.get("name_ar"), r.get("title")) if n and len(str(n)) >= 4]


def card_ids_of(rep: R.Reply) -> list[str]:
    return [i for i in rep.card_ids() if i]


# ------------------------------------------------------------------ checks
def run_checks(turn, rep: R.Reply, st: dict, F: Facts, user_texts: list[str], conv: dict) -> dict:
    """Returns {check_name: {"pass": bool|None, "detail": str}}; None = not applicable (skipped, never counted as pass)."""
    out: dict[str, dict] = {}
    want = dict(turn.get("checks") or {})
    prose = rep.prose
    ids = card_ids_of(rep)
    retrieved = [r.get("id") for r in (rep.trace.get("retrieved") or []) if isinstance(r, dict)]

    def put(name, ok, detail=""):
        out[name] = {"pass": ok, "detail": detail if not ok else ""}

    def on(name, default=True):
        v = want.get(name, default)
        return bool(v) if not isinstance(v, (list, dict)) else True

    # ---- defaults
    if on("stream_ok"):
        err = rep.error or rep.raw.get("transport_error")
        put("stream_ok", bool(rep.done) and not err, str(err)[:120] if err else "no done event")
    if on("empty_content"):
        put("empty_content", len(prose.strip()) >= 20, f"{len(prose.strip())} chars")
    if on("numbers_traceable"):
        ctx_ids = list(dict.fromkeys(ids + retrieved + st["prev_ids"]))
        pool = list(F.db.context_numbers(ctx_ids))
        for payload in (rep.cards, rep.calc, rep.compare):
            pool += R.flat_numbers(payload)
        for t_ in user_texts:
            pool += [v for v, _, _ in R.extract_numbers(t_)]
        pool += [v for v, _, _ in R.extract_numbers(st["prev_prose"])]
        bad = None
        for v, _is_price, abbr in R.extract_numbers(prose):
            if abs(v) < 10:
                continue
            if not R.num_in(v, pool, abbr):
                bad = v
                break
        put("numbers_traceable", bad is None, f"{bad:g} not in context" if bad is not None else "")
    if on("country_city"):
        extra = set(want.get("allowed_countries") or [])
        card_c = {F.country(i) for i in ids + retrieved if F.country(i)}
        prev_c = st["prev_countries"]
        user_c = set()
        for t_ in user_texts:
            user_c |= countries_in(t_)
        allowed = extra | card_c | prev_c | user_c
        named = countries_in(prose)
        stray = sorted(named - allowed)
        # sentence level: a sentence naming a project may only name that project's country (plus explicit extras)
        sent_bad = []
        known = {i: F.names(i) for i in dict.fromkeys(ids + retrieved + st["prev_ids"]) if F.row(i)}
        for s_ in sentences(prose):
            low = s_.lower()
            hit = [i for i, ns in known.items() if any(n in low for n in ns) and F.country(i)]
            if hit:
                ok_c = {F.country(i) for i in hit} | extra
                wrong = countries_in(s_) - ok_c
                if wrong:
                    sent_bad.append(f"{sorted(wrong)} in a sentence about {hit[0]}")
        put("country_city", not stray and not sent_bad, "; ".join(([f"unexpected country {stray}"] if stray else []) + sent_bad)[:200])
    if on("no_dead_end"):
        ok = bool(ids or rep.compare or rep.calc or rep.chips or "?" in prose or "؟" in prose)
        put("no_dead_end", ok, "no cards, chips or question")
    if on("lang_match"):
        lang = conv.get("lang", "en")
        ar_user = R.arabic_ratio(user_texts[-1]) > 0.5
        want_lang = (want.get("reply_lang") or ("any" if lang == "arabizi" else ("ar" if ar_user else "en")))
        r_ar = R.arabic_ratio(prose)
        ok = want_lang == "any" or (want_lang == "ar" and r_ar >= 0.4) or (want_lang == "en" and r_ar < 0.3)
        put("lang_match", ok, f"arabic ratio {r_ar:.2f}, expected {want_lang}")

    # ---- optional
    if "cards_min" in want:
        put("cards_min", len(ids) >= want["cards_min"], f"{len(ids)} cards")
    if "cards_city" in want:
        got = {str(F.city(i) or "").lower() for i in ids}
        ok = bool(ids) and got <= {c.lower() for c in want["cards_city"]}
        put("cards_city", ok or not ids, f"cities {sorted(got)}") if ids else put("cards_city", None, "no cards")
    if "cards_country" in want:
        got = {F.country(i) for i in ids}
        put("cards_country", bool(ids) and got <= set(want["cards_country"]), f"countries {sorted(map(str, got))}") if ids else put("cards_country", False, "no cards")
    if "cards_site" in want:
        got = {F.site(i) for i in ids}
        put("cards_site", bool(ids) and got <= set(want["cards_site"]), f"sites {sorted(map(str, got))}") if ids else put("cards_site", False, "no cards")
    if "cards_property" in want:
        pt = want["cards_property"].lower()
        known_t = [F.ptype(i) for i in ids if F.ptype(i).strip()]
        put("cards_property", bool(known_t) and all(pt in t for t in known_t), f"types {[t[:30] for t in known_t][:4]}") if known_t else put("cards_property", None, "no typed cards")
    if "sorted" in want:
        pr = [F.price(i) for i in ids if F.price(i)]
        if len(pr) < 2:
            put("sorted", None, "fewer than 2 priced cards")
        else:
            asc = all(a <= b for a, b in zip(pr, pr[1:]))
            desc = all(a >= b for a, b in zip(pr, pr[1:]))
            put("sorted", asc if want["sorted"] == "asc" else desc, f"prices {pr[:5]}")
    if want.get("no_blog_source"):
        bad = [s_.get("url") or s_.get("title") for s_ in rep.sources if BLOG_RE.search(str(s_.get("url") or "") + " " + str(s_.get("title") or ""))]
        put("no_blog_source", not bad, str(bad[:2]))
    if "ref" in want:
        picks = want["ref"].get("pick") or []
        prev = st["prev_ids"]
        if any(p > len(prev) for p in picks):
            put("ref", None, f"previous turn showed {len(prev)} cards")
        else:
            low = prose.lower()
            miss = []
            for p in picks:
                eid = prev[p - 1]
                if not (eid in ids or eid in retrieved or any(n in low for n in F.names(eid))):
                    miss.append(f"#{p}={eid}")
            put("ref", not miss, f"not resolved: {miss}; got {ids[:3]}")
    if want.get("cheaper_than_prev"):
        pp = [F.price(i) for i in st["prev_ids"] if F.price(i)]
        cp = [F.price(i) for i in ids if F.price(i)]
        if not pp:
            put("cheaper_than_prev", None, "no priced previous cards")
        else:
            put("cheaper_than_prev", bool(cp) and all(c < max(pp) for c in cp), f"prev max {max(pp):g}, now {cp[:5]}")
    low = prose.lower()
    if "contains_any_ci" in want:
        put("contains_any_ci", any(s_.lower() in low for s_ in want["contains_any_ci"]), f"none of {want['contains_any_ci'][:3]}")
    if "not_contains_any_ci" in want:
        hit = [s_ for s_ in want["not_contains_any_ci"] if s_.lower() in low]
        put("not_contains_any_ci", not hit, str(hit))
    if "not_regex" in want:
        hit = [p for p in want["not_regex"] if re.search(p, prose, re.I)]
        put("not_regex", not hit, str(hit))
    if want.get("hedge"):
        put("hedge", bool(R.NOT_FOUND_RE.search(prose)), "no honest not-found / not-published statement")
    if want.get("hedge_or_date"):
        put("hedge_or_date", bool(R.NOT_FOUND_RE.search(prose) or DATE_RE.search(prose)), "neither a hedge nor a date")
    if want.get("cards_or_hedge"):
        put("cards_or_hedge", bool(ids) or bool(R.NOT_FOUND_RE.search(prose)), "no cards and no hedge")
    if want.get("no_cards"):
        put("no_cards", not ids, f"{len(ids)} cards on an off-topic turn")
    if want.get("no_promise"):
        m = R.PROMISE_RE.search(prose)
        put("no_promise", not m, m.group(0)[:60] if m else "")
    return out


# ------------------------------------------------------------------ providers: rate-limit probe and judge
def probe_nvidia() -> dict:
    """One GET /v1/models: no completion, no tokens. Records rate-limit/quota headers if any. Key never stored."""
    key = (os.environ.get("NVIDIA_API_KEY") or "").strip()
    if not key:
        return {"status": "skipped", "note": "NVIDIA_API_KEY not set"}
    req = urllib.request.Request(NVIDIA_MODELS_URL, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    rec = {"at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "url": NVIDIA_MODELS_URL}
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            rec["status"] = r.status
            rec["headers"] = {k: v for k, v in r.getheaders() if HEADER_RE.search(k)}
    except urllib.error.HTTPError as e:
        rec["status"] = e.code
        rec["headers"] = {k: v for k, v in e.headers.items() if HEADER_RE.search(k)}
    except Exception as e:  # noqa: BLE001
        rec["status"] = f"error: {type(e).__name__}"
    if not rec.get("headers"):
        rec["note"] = "no rate-limit or quota headers returned on this endpoint"
    return rec


JUDGE_SYSTEM = (
    "You grade one reply of a property-concierge chatbot (DarGlobal and Wasalt). Score two dimensions from 1 to 5 "
    "(5 best): helpfulness (moves the user forward with correct, usable next steps using only the given facts) and tone "
    "(warm, concise, natural in the user's language, no pushiness). Judge only what is shown. Return JSON only: "
    '{"helpfulness":int,"tone":int,"note":"one short sentence"}. Limit: you are weak on Gulf Arabic dialect; be lenient on dialect.')


def judge_turn(payload: dict, key: str, counter: dict) -> dict:
    if counter.get("quota_exhausted"):
        return {"judged": False, "error": "gemini daily quota exhausted earlier"}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    body = {"systemInstruction": {"parts": [{"text": JUDGE_SYSTEM}]},
            "contents": [{"role": "user", "parts": [{"text": json.dumps(payload, ensure_ascii=False)}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json", "maxOutputTokens": 300}}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    counter["calls"] += 1
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            obj = json.loads(r.read())
        txt = "".join(p.get("text", "") for p in obj["candidates"][0]["content"]["parts"])
        v, _ = json.JSONDecoder().raw_decode(txt[txt.index("{"):])
        return {"judged": True, "helpfulness": int(v.get("helpfulness")), "tone": int(v.get("tone")), "note": str(v.get("note", ""))[:200], "model": GEMINI_MODEL}
    except urllib.error.HTTPError as e:
        if e.code == 429:
            counter["quota_exhausted"] = True  # stop judging, never loop
        return {"judged": False, "error": f"HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001
        return {"judged": False, "error": f"{type(e).__name__}"}


# ------------------------------------------------------------------ run
def build_summary(convs: list[dict]) -> dict:
    by_cat, by_check, by_play, by_tag = (defaultdict(lambda: [0, 0]) for _ in range(4))
    turns_n = path_llm = empty = 0
    lat, hb, tt = [], [], []
    for c in convs:
        for t in c["turns"]:
            turns_n += 1
            verdicts = [v["pass"] for v in t["checks"].values() if v["pass"] is not None]
            ok = all(verdicts)
            for tab, key in ((by_cat, c["category"]), (by_play, t.get("playbook") or c["playbook"])):
                tab[key][0] += ok
                tab[key][1] += 1
            for tag in c.get("tags") or []:
                by_tag[tag][0] += ok
                by_tag[tag][1] += 1
            for name, v in t["checks"].items():
                if v["pass"] is not None:
                    by_check[name][0] += bool(v["pass"])
                    by_check[name][1] += 1
            path_llm += (t.get("trace") or {}).get("path") == "llm_understanding"
            empty += not (t.get("answer") or "").strip()
            if t.get("trace_latency_ms") is not None:
                lat.append(t["trace_latency_ms"])
            if t.get("ttft_ms") is not None:
                tt.append(t["ttft_ms"])
            if t.get("judge", {}).get("judged"):
                hb.append((t["judge"]["helpfulness"], t["judge"]["tone"]))

    def fmt(d):
        return {k: {"passed": v[0], "n": v[1], "rate": round(v[0] / v[1], 4) if v[1] else None} for k, v in sorted(d.items())}

    return {"turns": turns_n, "turn_pass_by_category": fmt(by_cat), "turn_pass_by_check": fmt(by_check),
            "turn_pass_by_playbook": fmt(by_play), "turn_pass_by_tag": fmt(by_tag),
            "share_path_llm_understanding": round(path_llm / turns_n, 4) if turns_n else None,
            "empty_content_rate": round(empty / turns_n, 4) if turns_n else None,
            "latency_trace_ms": {"p50": R.pct(lat, 0.5), "p95": R.pct(lat, 0.95), "n": len(lat)},
            "ttft_ms": {"p50": R.pct(tt, 0.5), "p95": R.pct(tt, 0.95), "n": len(tt)},
            "judge": {"n": len(hb), "helpfulness_mean": round(sum(h for h, _ in hb) / len(hb), 2) if hb else None,
                      "tone_mean": round(sum(t for _, t in hb) / len(hb), 2) if hb else None,
                      "limit": "Gemini judge is weak on Gulf dialect; reported separately, never overrides a check"}}


def main() -> int:
    for st_ in (sys.stdout, sys.stderr):
        try:
            st_.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.getenv("EVAL_BASE_URL", "http://localhost:8020"))
    ap.add_argument("--conv", default=str(DEFAULT_CONV))
    ap.add_argument("--label", default="run")
    ap.add_argument("--only", default="", help="comma list of conversation ids")
    ap.add_argument("--max-llm-calls", type=int, default=int(os.getenv("EVAL_MAX_LLM_CALLS", "0") or 0))
    ap.add_argument("--stop-after-429", type=int, default=3)
    ap.add_argument("--rpm", type=float, default=10)
    ap.add_argument("--judge", default="", choices=["", "gemini"])
    ap.add_argument("--judge-limit", type=int, default=0)
    ap.add_argument("--probe-nvidia", action="store_true")
    ap.add_argument("--db", default=str(ROOT / "data" / "concierge.sqlite"))
    ap.add_argument("--out-dir", default=str(RESULTS))
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    spec = yaml.safe_load(Path(args.conv).read_text(encoding="utf-8"))
    convs = spec["conversations"]
    if args.only:
        keep = {x.strip() for x in args.only.split(",")}
        convs = [c for c in convs if c["id"] in keep]
    if args.list:
        nt = sum(len(c["turns"]) for c in convs)
        cats = defaultdict(int)
        for c in convs:
            cats[c["category"]] += 1
        tags = defaultdict(int)
        for c in convs:
            for t in c.get("tags") or []:
                tags[t] += 1
        print(f"{len(convs)} conversations, {nt} turns")
        print("categories:", dict(cats))
        print("tags:", dict(tags))
        print("playbook ids used:", sorted({t.get('playbook') or c['playbook'] for c in convs for t in c['turns']}))
        return 0

    load_env()
    base = args.base_url.rstrip("/")
    try:
        _, meta = R.http_json(base, "/api/meta")
    except Exception as e:  # noqa: BLE001
        print(f"[abort] cannot reach {base}: {type(e).__name__}", file=sys.stderr)
        return 2
    llm = (meta or {}).get("llm") or {}
    live = (llm.get("mode") or ("live" if (meta or {}).get("llm_available") else "off")) == "live"
    if live and args.max_llm_calls <= 0:
        print("[abort] server reports llm.mode=live: set EVAL_MAX_LLM_CALLS or --max-llm-calls N", file=sys.stderr)
        return 3
    budget_start = (llm.get("budget") or {}).get("used")
    db = R.DB(Path(args.db))
    F = Facts(db)
    throttle = R.Throttle(args.rpm)
    gkey = os.environ.get("GEMINI_API_KEY", "") if args.judge else ""
    jcount = {"calls": 0, "quota_exhausted": False}

    out = {"label": args.label, "run_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "base_url": base,
           "conversation_file": Path(args.conv).name, "dataset_version": (meta or {}).get("dataset_version"),
           "provider": llm.get("provider") or "openrouter", "model": llm.get("model") or ((meta or {}).get("models") or [None])[0],
           "llm_mode": llm.get("mode"), "max_llm_calls": args.max_llm_calls,
           "nvidia_probe_before": probe_nvidia() if args.probe_nvidia else None, "conversations": []}
    counted = 0
    consec_rate = 0
    stop_reason = None
    outpath = Path(args.out_dir) / f"conv_{args.label}.json"
    outpath.parent.mkdir(parents=True, exist_ok=True)

    def save(final=False):
        out["llm_calls_counted"] = counted
        out["stop_reason"] = stop_reason
        out["judge_calls"] = jcount["calls"]
        out["summary"] = build_summary(out["conversations"])
        if final:
            out["nvidia_probe_after"] = probe_nvidia() if args.probe_nvidia else None
            _, m2 = R.http_json(base, "/api/meta")
            b_end = (((m2 or {}).get("llm") or {}).get("budget") or {}).get("used")
            out["server_budget_used"] = {"start": budget_start, "end": b_end,
                                         "delta": (b_end - budget_start) if isinstance(b_end, int) and isinstance(budget_start, int) else None}
        outpath.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    for ci, conv in enumerate(convs, 1):
        if stop_reason:
            break
        session = f"conv-{conv['id']}-{uuid.uuid4().hex[:6]}"
        history: list[dict] = []
        st = {"prev_ids": [], "prev_prose": "", "prev_countries": set()}
        user_texts: list[str] = []
        crec = {"id": conv["id"], "category": conv["category"], "playbook": conv["playbook"], "lang": conv["lang"],
                "tags": conv.get("tags") or [], "turns": []}
        print(f"[{ci}/{len(convs)}] {conv['id']} {conv['category']} ({conv['playbook']})")
        for ti, turn in enumerate(conv["turns"], 1):
            if live and counted >= args.max_llm_calls:
                stop_reason = f"EVAL_MAX_LLM_CALLS cap reached at {counted} calls"
                break
            msg = turn["say"]
            user_texts.append(msg)
            payload = {"session_id": session, "message": msg, "history": history[-8:], "lang": "auto",
                       "last_entities": st["prev_ids"][:6]}
            throttle.wait()
            rep = R.Reply(R.chat_stream(base, payload, timeout=90))
            if rep.error and rep.error.get("code") == "RATE_LIMITED":  # the app's own per-IP limiter, not a provider quota
                time.sleep(min(float(rep.error.get("retry_after_s") or 20), 60))
                rep = R.Reply(R.chat_stream(base, payload, timeout=90))
            calls = rep.trace.get("llm_calls")
            counted += int(calls) if isinstance(calls, int) else (1 if live else 0)
            checks = run_checks(turn, rep, st, F, user_texts, conv)
            reason = str(rep.trace.get("degraded_reason") or "")
            errtxt = json.dumps(rep.error, ensure_ascii=False) if rep.error else ""
            trace = {k: rep.trace.get(k) for k in ("intent", "path", "tool", "llm_calls", "model", "provider", "latency_ms", "cache_hit",
                                                   "degraded", "degraded_reason", "fallback_hops", "steps", "retrieved")}
            trec = {"n": ti, "say": msg, "playbook": turn.get("playbook") or conv["playbook"], "payload_last_entities": payload["last_entities"],
                    "answer": rep.prose, "trace": trace, "trace_latency_ms": rep.trace.get("latency_ms"), "ttft_ms": rep.ttft_ms,
                    "cards": [{"id": c.get("id"), "name": c.get("name") or c.get("title"), "city": c.get("city"), "price": c.get("price_from") or c.get("price")}
                              for c in rep.projects + rep.listings],
                    "compare": bool(rep.compare), "chips": [c if isinstance(c, str) else (c.get("label") or c.get("text")) for c in rep.chips],
                    "sources": [{"title": s_.get("title"), "url": s_.get("url")} for s_ in rep.sources], "checks": checks}
            if args.judge == "gemini" and gkey and rep.prose.strip() and (not args.judge_limit or jcount["calls"] < args.judge_limit):
                trec["judge"] = judge_turn({"question": msg, "earlier_user_turns": user_texts[:-1][-3:], "answer": rep.prose,
                                            "cards": trec["cards"][:5], "chips": trec["chips"][:4], "language": conv["lang"]}, gkey, jcount)
            crec["turns"].append(trec)
            bad = [f"{n}: {v['detail']}" for n, v in checks.items() if v["pass"] is False]
            print(f"   t{ti} {'PASS' if not bad else 'FAIL ' + ' | '.join(bad)[:150]}  [{trace.get('path')}, calls={calls}, {counted} counted]")
            # carry state for the next turn
            history += [{"role": "user", "content": msg}, {"role": "assistant", "content": rep.prose}]
            st["prev_ids"] = card_ids_of(rep)[:6]
            st["prev_prose"] = rep.prose
            st["prev_countries"] |= {F.country(i) for i in st["prev_ids"] if F.country(i)}
            # stop on quota
            if QUOTA_RE.search(reason + " " + errtxt):
                stop_reason = f"NVIDIA free limit reached at {counted} calls (quota/credit error: {reason or errtxt[:80]})"
            consec_rate = consec_rate + 1 if RATE_RE.search(reason + " " + errtxt) else 0
            if consec_rate >= args.stop_after_429:
                stop_reason = f"NVIDIA free limit reached at {counted} calls ({consec_rate} consecutive 429 / rate-limit degradations)"
            if stop_reason:
                print(f"[stop] {stop_reason}")
                break
        out["conversations"].append(crec)
        save()
    save(final=True)
    s = out["summary"]
    print("=" * 60)
    print(f"{args.label}: {s['turns']} turns, llm calls counted {counted}, stop: {stop_reason or 'none (completed)'}")
    for k, v in s["turn_pass_by_category"].items():
        print(f"  {k:28s} {v['passed']}/{v['n']}")
    print(f"  share path=llm_understanding {s['share_path_llm_understanding']}  p95 latency {s['latency_trace_ms']['p95']} ms  -> {outpath}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
