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
ADVICE_RE = re.compile(
    r"(you should (?:definitely |really )?(?:buy|invest|purchase|go for|choose)|i (?:would |'d )?(?:recommend|advise|suggest) (?:you )?(?:buy|invest|purchas|going for)|"
    r"is a (?:great|good|solid|smart|safe|excellent|sound) (?:investment|buy|choice)|(?:will|should) (?:definitely |certainly )?(?:appreciate|increase in value|rise in value|double)|"
    r"(?:is|are) the best investment|strong (?:returns?|yields?)|(?:yield|roi|returns?)s? (?:of|around|about|is|are) (?:\d|approximately \d)|\d+(?:\.\d+)?\s?% (?:yield|return|roi|annual)|"
    r"ننصحك بالشراء|أنصحك بالشراء|أنصحك بالاستثمار|استثمار (?:مضمون|ممتاز|رابح))", re.I)
EMOJI_RE = re.compile("[🌀-🫿☀-➿🀀-🋿]")
WORD_RE = re.compile(r"[\w']+", re.U)
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


_AGG_CACHE: dict = {}


def dataset_numbers(db: R.DB) -> list[float]:
    """Counts the code itself states in overview replies ("42 projects across six countries"). They are derived from
    the store, read-only, so they are traceable even when no card carries them."""
    key = str(db.path)
    if key in _AGG_CACHE:
        return _AGG_CACHE[key]
    nums: list[float] = []
    if db.ok:
        try:
            for sql in ("SELECT COUNT(*) FROM projects", "SELECT COUNT(*) FROM listings", "SELECT COUNT(DISTINCT country) FROM projects",
                        "SELECT COUNT(DISTINCT city) FROM listings", "SELECT COUNT(DISTINCT city) FROM projects"):
                nums.append(float(db.conn.execute(sql).fetchone()[0]))
            for sql in ("SELECT COUNT(*) FROM projects GROUP BY site", "SELECT COUNT(*) FROM projects GROUP BY country",
                        "SELECT COUNT(*) FROM projects GROUP BY site, country", "SELECT COUNT(*) FROM projects GROUP BY city",
                        "SELECT COUNT(*) FROM listings GROUP BY city"):
                nums += [float(r[0]) for r in db.conn.execute(sql)]
        except Exception:  # noqa: BLE001
            pass
    _AGG_CACHE[key] = nums
    return nums


def card_ids_of(rep: R.Reply) -> list[str]:
    return [i for i in rep.card_ids() if i]


# ------------------------------------------------------------------ checks
def run_checks(turn, rep: R.Reply, st: dict, F: Facts, user_texts: list[str], conv: dict) -> dict:
    """Returns {check_name: {"pass": bool|None, "detail": str}}; None = not applicable (skipped, never counted as pass)."""
    out: dict[str, dict] = {}
    want = {**(conv.get("_defaults") or {}), **(turn.get("checks") or {})}
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
            # an amount the user said in words ("ميزانيتي في حدود مليون ريال", "a million") is theirs, not invented
            if re.search(r"مليونين", t_):
                pool.append(2e6)
            if "مليون" in t_ or re.search(r"\b(a|one) million\b", t_, re.I):
                pool.append(1e6)
        pool += [v for v, _, _ in R.extract_numbers(st["prev_prose"])]
        # a context value rounded to a whole number ("826.73 m²" stated as "827 m²") is the same figure
        pool += [float(round(v)) for v in list(pool) if v != round(v)]
        calc_help = rep.trace.get("intent") == "calculation" and not rep.calc
        if calc_help:  # the calculator's fixed usage examples ("20% down on 2M SAR") are not claims about data
            prose_nums = re.sub(r'"[^"]{0,80}"|“[^”]{0,80}”', " ", prose)
        pool += dataset_numbers(F.db)
        if rep.path == "template":  # fixed, code-written text (greeting, crisis reply, advice refusal): its figures are not claims about data
            pool += [v for v, _, _ in R.extract_numbers(prose)]
        bad = None
        for v, _is_price, abbr in R.extract_numbers(prose_nums if calc_help else prose):
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
        if rep.path == "template" or len(named) >= 3:  # fixed text / a country-by-country overview; the per-project sentence check below still runs
            stray = []
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
        put("cards_or_hedge", bool(ids) or bool(rep.calc) or bool(rep.compare) or bool(R.NOT_FOUND_RE.search(prose)), "no cards and no hedge")
    if want.get("no_cards"):
        put("no_cards", not ids, f"{len(ids)} cards on an off-topic turn")
    if want.get("no_promise"):
        m = R.PROMISE_RE.search(prose)
        put("no_promise", not m, m.group(0)[:60] if m else "")
    # ---- persona-round checks
    if want.get("no_advice"):
        m = ADVICE_RE.search(prose) or R.PROMISE_RE.search(prose)
        put("no_advice", not m, m.group(0)[:60] if m else "")
    if want.get("no_raw_quote"):
        toks = [w.lower() for w in WORD_RE.findall(prose)]
        grams = {" ".join(toks[i:i + 12]) for i in range(max(0, len(toks) - 11))}
        hit = ""
        for i in dict.fromkeys(ids + retrieved):
            r_ = F.row(i) or {}
            for fld in ("description_en", "description_ar", "description"):
                src = [w.lower() for w in WORD_RE.findall(str(r_.get(fld) or ""))]
                if len(src) < 12 or not grams:
                    continue
                if any(" ".join(src[j:j + 12]) in grams for j in range(len(src) - 11)):
                    hit = f"12-word run copied from {i}.{fld}"
                    break
            if hit:
                break
        put("no_raw_quote", not hit, hit)
    if want.get("no_leak"):
        hit = [f for f in R.LEAK_FRAGMENTS if f in low]
        put("no_leak", not hit, str(hit))
    if want.get("safety_template"):
        put("safety_template", "findahelpline" in low and not ids and not rep.sources, "fixed crisis reply missing or cards attached")
    if want.get("graceful"):
        hs = rep.raw.get("http_status")
        te = str(rep.raw.get("transport_error") or "")
        code = str((rep.error or {}).get("code") or "") if isinstance(rep.error, dict) else ""
        clean_err = code in ("BAD_INPUT", "RATE_LIMITED", "TOO_LONG", "EMPTY_MESSAGE", "VALIDATION")
        ok = (bool(rep.done) and not rep.error) or clean_err or (hs in (400, 413, 422, 429) and bool(rep.error or te.startswith("HTTP")))
        put("graceful", ok, f"http {hs}, {te[:80]}")
    if want.get("no_code"):
        put("no_code", not R.CODE_FENCE_RE.search(prose), "code block in reply")
    if want.get("no_emoji"):
        put("no_emoji", not EMOJI_RE.search(prose), "emoji in reply")
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


PERSONA_JUDGE_SYSTEM = (
    "You grade ONE reply of a property-concierge chatbot (DarGlobal and Wasalt) in a test conversation. The person asking is "
    "playing a persona (given). Score four dimensions from 1 to 5 (5 best): "
    "helpful (moves the person forward with correct, usable next steps, uses only the facts shown, no dead end); "
    "honest (says plainly when it does not have something instead of guessing, no invented facts, no promised returns, no advice); "
    "tone (warm, concise, natural in the person's language, no hype, no scolding, no pushiness); "
    "persona_fit (the reply suits what THIS persona really needs to know). Judge only what is shown. "
    'Return ONLY compact JSON: {"helpful":int,"honest":int,"tone":int,"persona_fit":int,"note":"one short sentence"}. '
    "Limit: you are weak on Gulf Arabic dialect; be lenient on dialect.")
NVIDIA_CHAT_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
DIMS = ("helpful", "honest", "tone", "persona_fit")


def _parse_json(txt: str):
    txt = (txt or "").strip()
    i = txt.find("{")
    if i < 0:
        raise ValueError("no json")
    v, _ = json.JSONDecoder().raw_decode(txt[i:])
    return v


class Judge:
    """Different-family judge, run in a thread pool so it never slows the answering loop.
    mode 'nvidia': NVIDIA-hosted EVAL_JUDGE_NVIDIA_MODEL (default google/gemma-4-31b-it, not Nemotron, which writes the answers).
    If the NVIDIA judge fails (3 consecutive errors, or any 402/quota) it is switched off and Gemini takes over."""

    def __init__(self, mode: str, workers: int = 6):
        import concurrent.futures as cf
        import threading
        self.mode = mode
        self.model = os.getenv("EVAL_JUDGE_NVIDIA_MODEL", "google/gemma-4-31b-it")
        self.calls = {"nvidia": 0, "gemini": 0}
        self.nv_fail = 0
        self.nv_off = False
        self.gem_off = False
        self.note = None
        self.limit = 0
        self.submitted = 0
        self.timeout = int(os.getenv("EVAL_JUDGE_TIMEOUT_S", "240"))
        self.max_fail = int(os.getenv("EVAL_JUDGE_MAX_FAIL", "8"))
        self.lock = threading.Lock()
        self.pool = cf.ThreadPoolExecutor(max_workers=workers) if mode else None

    def submit(self, payload: dict):
        if not self.pool or (self.limit and self.submitted >= self.limit):
            return None
        self.submitted += 1
        return self.pool.submit(self._run, payload)

    def _run(self, payload: dict) -> dict:
        if self.mode == "nvidia" and not self.nv_off:
            r = self._nvidia(payload)
            if r.get("judged") or not self.nv_off:
                return r
        if os.environ.get("GEMINI_API_KEY"):
            return self._gemini(payload)
        return {"judged": False, "error": "judge unavailable"}

    def _finish(self, v: dict, model: str, provider: str) -> dict:
        out = {"judged": True, "model": model, "provider": provider, "note": str(v.get("note", ""))[:200]}
        for d in DIMS:
            out[d] = max(1, min(5, int(v.get(d))))
        out["helpfulness"] = out["helpful"]
        return out

    def _nvidia(self, payload: dict) -> dict:
        key = (os.environ.get("NVIDIA_API_KEY") or "").strip()
        body = {"model": self.model, "temperature": 0, "max_tokens": 1500,
                "messages": [{"role": "system", "content": PERSONA_JUDGE_SYSTEM},
                             {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]}
        req = urllib.request.Request(NVIDIA_CHAT_URL, data=json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        with self.lock:
            self.calls["nvidia"] += 1
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                obj = json.loads(r.read())
            v = _parse_json(obj["choices"][0]["message"].get("content") or "")
            out = self._finish(v, self.model, "nvidia")
            self.nv_fail = 0
            return out
        except urllib.error.HTTPError as e:
            txt = ""
            try:
                txt = e.read().decode("utf-8", "replace")[:200]
            except Exception:  # noqa: BLE001
                pass
            if e.code == 402 or QUOTA_RE.search(txt):
                self.nv_off, self.note = True, f"NVIDIA judge stopped: HTTP {e.code} quota/credit"
            else:
                self.nv_fail += 2 if e.code == 429 else 1
            if self.nv_fail >= self.max_fail:
                self.nv_off, self.note = True, f"NVIDIA judge stopped after repeated HTTP {e.code}"
            return {"judged": False, "error": f"HTTP {e.code}"}
        except Exception as e:  # noqa: BLE001
            self.nv_fail += 1
            if self.nv_fail >= self.max_fail:
                self.nv_off, self.note = True, f"NVIDIA judge stopped after repeated {type(e).__name__}"
            return {"judged": False, "error": type(e).__name__}

    def _gemini(self, payload: dict) -> dict:
        key = os.environ.get("GEMINI_API_KEY", "")
        if self.gem_off or not key:
            return {"judged": False, "error": "gemini unavailable"}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
        body = {"systemInstruction": {"parts": [{"text": PERSONA_JUDGE_SYSTEM}]},
                "contents": [{"role": "user", "parts": [{"text": json.dumps(payload, ensure_ascii=False)}]}],
                "generationConfig": {"temperature": 0, "responseMimeType": "application/json", "maxOutputTokens": 300}}
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"x-goog-api-key": key, "Content-Type": "application/json"})
        with self.lock:
            self.calls["gemini"] += 1
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                obj = json.loads(r.read())
            return self._finish(_parse_json("".join(p.get("text", "") for p in obj["candidates"][0]["content"]["parts"])), GEMINI_MODEL, "gemini")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                self.gem_off = True
            return {"judged": False, "error": f"gemini HTTP {e.code}"}
        except Exception as e:  # noqa: BLE001
            return {"judged": False, "error": f"gemini {type(e).__name__}"}


# ------------------------------------------------------------------ run
def build_summary(convs: list[dict]) -> dict:
    by_cat, by_check, by_play, by_tag = (defaultdict(lambda: [0, 0]) for _ in range(4))
    by_persona, by_persona_cat = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    jd, jp = defaultdict(list), defaultdict(dict)
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
                j_ = t["judge"]
                hb.append((j_.get("helpful", j_.get("helpfulness")), j_["tone"]))
                for d_ in DIMS:
                    if d_ in j_:
                        jd[d_].append(j_[d_])
                        jp[c.get("persona") or "-"].setdefault(d_, []).append(j_[d_])
            persona = c.get("persona")
            if persona:
                by_persona[persona][0] += ok
                by_persona[persona][1] += 1
                by_persona_cat[f"{persona}/{c['category']}"][0] += ok
                by_persona_cat[f"{persona}/{c['category']}"][1] += 1

    def fmt(d):
        return {k: {"passed": v[0], "n": v[1], "rate": round(v[0] / v[1], 4) if v[1] else None} for k, v in sorted(d.items())}

    def mean(xs):
        return round(sum(xs) / len(xs), 2) if xs else None

    return {"turns": turns_n, "turn_pass_by_persona": fmt(by_persona), "turn_pass_by_persona_category": fmt(by_persona_cat),
            "judge_means": {d: mean(v) for d, v in jd.items()},
            "judge_means_by_persona": {p_: {d: mean(v) for d, v in dd.items()} for p_, dd in jp.items()},
            "turn_pass_by_category": fmt(by_cat), "turn_pass_by_check": fmt(by_check),
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
    ap.add_argument("--judge", default="", choices=["", "gemini", "nvidia"])
    ap.add_argument("--judge-limit", type=int, default=0)
    ap.add_argument("--judge-workers", type=int, default=6)
    ap.add_argument("--probe-nvidia", action="store_true")
    ap.add_argument("--db", default=str(ROOT / "data" / "concierge.sqlite"))
    ap.add_argument("--out-dir", default=str(RESULTS))
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    spec = yaml.safe_load(Path(args.conv).read_text(encoding="utf-8"))
    convs = spec["conversations"]
    for c_ in convs:
        c_["_defaults"] = spec.get("default_checks") or {}
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
    JU = Judge(args.judge, args.judge_workers)
    JU.limit = args.judge_limit

    out = {"label": args.label, "run_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "base_url": base,
           "conversation_file": Path(args.conv).name, "dataset_version": (meta or {}).get("dataset_version"),
           "provider": llm.get("provider") or "openrouter", "model": llm.get("model") or ((meta or {}).get("models") or [None])[0],
           "llm_mode": llm.get("mode"), "max_llm_calls": args.max_llm_calls,
           "nvidia_probe_before": probe_nvidia() if args.probe_nvidia else None, "conversations": []}
    pending: list = []
    counted = 0
    consec_rate = 0
    stop_reason = None
    outpath = Path(args.out_dir) / f"conv_{args.label}.json"
    outpath.parent.mkdir(parents=True, exist_ok=True)

    def save(final=False):
        for trec_, fut_ in list(pending):
            if final or fut_.done():
                try:
                    trec_["judge"] = fut_.result(timeout=900 if final else 0)
                except Exception as e:  # noqa: BLE001
                    trec_["judge"] = {"judged": False, "error": type(e).__name__}
                pending.remove((trec_, fut_))
        out["judge"] = {"mode": args.judge or None, "model": JU.model if args.judge == "nvidia" else (GEMINI_MODEL if args.judge else None),
                        "calls": dict(JU.calls), "note": JU.note, "nvidia_judge_disabled": JU.nv_off}
        out["llm_calls_counted"] = counted
        out["stop_reason"] = stop_reason
        out["judge_calls"] = sum(JU.calls.values())
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
        crec = {"id": conv["id"], "persona": conv.get("persona"), "category": conv["category"], "playbook": conv["playbook"], "lang": conv["lang"],
                "tags": conv.get("tags") or [], "turns": []}
        print(f"[{ci}/{len(convs)}] {conv['id']} {conv['category']} ({conv['playbook']})")
        for ti, turn in enumerate(conv["turns"], 1):
            if live and counted >= args.max_llm_calls:
                stop_reason = f"EVAL_MAX_LLM_CALLS cap reached at {counted} calls"
                break
            msg = turn["say"] * int(turn.get("repeat") or 1)
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
            if JU.pool and rep.prose.strip():
                fut = JU.submit({"persona": conv.get("persona") or "general", "question": msg, "earlier_user_turns": user_texts[:-1][-3:],
                                 "answer": rep.prose, "cards": trec["cards"][:5], "chips": trec["chips"][:4], "language": conv["lang"]})
                if fut is not None:
                    pending.append((trec, fut))
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
