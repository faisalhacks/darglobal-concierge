"""Answer playbook (quality round, Lane C): loader, deterministic selection and the writer's guidance block.

Policy only, never facts. `playbook.yaml` holds one entry per question type (32 + `generic`). Selection costs zero
LLM calls and is reproducible for the eval:
  1. `question_type` from the understanding call, when that call ran (a playbook id, or a coarse label mapped below);
  2. otherwise a fixed map from the code planner's intent, refined by a few deterministic text cues;
  3. no match -> `generic`.
Embedding-similarity selection was cut by the council (an extra failure mode, not reproducible enough).

The loader parses a strict YAML subset itself (the runtime image has no PyYAML): `key: scalar` lines and block lists
of double-quoted strings. A malformed file fails loudly at import time in tests, and the app then runs without a
playbook rather than with a half-read one.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field

from .arabic import normalize_text

log = logging.getLogger("concierge.playbook")

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "playbook.yaml")
GENERIC = "generic"

# The 32 ids of the owner override (same list as the header of evals/conversations_30.yaml).
IDS = ("filtered_search", "refine", "superlative", "best_value", "rent_vs_buy", "near_amenity", "project_facts",
       "single_attribute", "compare", "brand_partner", "country_overview", "site_confusion", "greeting",
       "thanks_goodbye", "identity", "capabilities", "vague_opener", "banter", "followup_reference", "topic_switch",
       "calculation", "currency", "price_not_published", "unrealistic_budget", "invented_or_false_premise",
       "adjacent", "investment_advice", "injection", "steering", "off_topic", "interest_handoff",
       "availability_booking")

# Code planner intent -> playbook id (works on the 0-call and 1-call paths).
INTENT_MAP = {
    "search": "filtered_search", "find_my_home": "filtered_search", "superlative": "superlative",
    "vague": "vague_opener", "project_info": "project_facts", "compare": "compare", "brand_partner": "brand_partner",
    "location_overview": "country_overview", "greeting": "greeting", "thanks": "thanks_goodbye",
    "goodbye": "thanks_goodbye", "ack": "thanks_goodbye", "identity": "identity", "banter": "banter",
    "off_topic": "off_topic", "adjacent": "adjacent", "steering": "steering", "advice": "investment_advice",
    "injection": "injection", "contact_sales": "interest_handoff", "calculation": "calculation",
    "general": GENERIC,
}

# Coarse `question_type` labels from the understanding call (contract section 3) -> playbook id. A question_type that
# is itself a playbook id is used as is. "factual" (the validate() default, also what a free model says when unsure)
# deliberately keeps the intent map instead of forcing project_facts: a search turn labelled "factual" is still a
# search. The other coarse labels match understanding.COARSE_QUESTION_TYPES.
QUESTION_TYPE_MAP = {
    "comparison": "compare", "recommendation": "filtered_search", "chitchat": "banter", "out_of_scope": "off_topic",
    "superlative": "superlative", "reference": "followup_reference", "followup": "followup_reference",
    "false_premise": "invented_or_false_premise", "not_in_data": "invented_or_false_premise",
    "advice": "investment_advice", "legal": "adjacent", "availability": "availability_booking",
    "booking": "availability_booking", "handoff": "interest_handoff", "meta": "identity", "meta_trust": "identity",
    "greeting": "greeting", "capabilities": "capabilities", "site_confusion": "site_confusion",
    "topic_switch": "topic_switch", "refine": "refine", "calculation": "calculation", "currency": "currency",
}

# Deterministic text cues that sharpen the intent map. Ordered: the first matching cue wins.
_CUES: list[tuple[str, tuple[str, ...] | None, re.Pattern]] = [
    ("availability_booking", None, re.compile(
        r"(?<![a-z])(still available|availab|in stock|book (a |an )?(viewing|visit|tour|appointment)|viewing|"
        r"reserve|reservation|site visit)(?![a-z])|احجز|حجز|معاينه|متاح|متوفر الحين")),
    ("rent_vs_buy", None, re.compile(r"(?<![a-z])(rent (or|vs\.?|versus) (buy|by)|buy (or|vs\.?|versus) rent|"
                                     r"renting (or|vs\.?|versus|better than) buying)(?![a-z])|اشتري ولا استاجر|"
                                     r"استاجر ولا اشتري|الايجار ولا الشراء")),
    ("best_value", None, re.compile(r"(?<![a-z])(best value|best deal|value for money|best price per|"
                                    r"good deal|bang for)(?![a-z])|افضل سعر|افضل قيمه|يستاهل سعره")),
    ("near_amenity", None, re.compile(r"(?<![a-z])(near|close to|next to|walking distance|beach|golf|pool|gym|"
                                      r"school|schools|metro|mall|amenit\w*)(?![a-z])|قريب من|مسبح|شاطئ|جولف|مدارس|مرافق")),
    ("currency", ("calculation",), re.compile(r"(?<![a-z])(convert|in (usd|dollars?|gbp|pounds?|euros?|eur|aed|sar))"
                                              r"(?![a-z])|بالدولار|باليورو|بالجنيه|حول")),
    ("capabilities", ("identity",), re.compile(r"(?<![a-z])(what can you do|how (does|do) (this|you) work|"
                                               r"help me with|can you help)(?![a-z])|وش تقدر|ماذا تستطيع")),
    ("topic_switch", None, re.compile(r"(?<![a-z])(switching topic|switch(ing)? topics?|change of topic|"
                                      r"forget (that|it)|something else|new question|different question)(?![a-z])|"
                                      r"خلنا من|موضوع ثاني|سؤال ثاني")),
]
_FIELD_Q = re.compile(r"(?<![a-z])(when|handover|hand over|complet\w*|status|where|located|location|how big|size|area)"
                      r"(?![a-z])|متى|التسليم|وين|اين|موقع|مساحه|الحاله")
_PRICE_Q = re.compile(r"(?<![a-z])(price|prices|cost|how much|starting)(?![a-z])|سعر|كم")
_REF_Q = re.compile(r"(?<![a-z])(first|second|third|last|that one|this one|the one|them|those|it|its)(?![a-z])|"
                    r"الاول|الثاني|الثالث|الاخير|هذا|هذي|هذه")
# Site confusion: a DarGlobal rental or a Wasalt/DarGlobal "same company" question.
_SITE_Q = re.compile(r"(?=.*(wasalt|وصلت))(?=.*(dar ?global|دار ?(جلوبال|غلوبال)))|"
                     r"(?=.*(dar ?global|دار ?(جلوبال|غلوبال)))(?=.*(rent|rental|lease|ايجار|استاجر))")


@dataclass(frozen=True)
class Entry:
    id: str
    examples: tuple[str, ...] = ()
    policy: tuple[str, ...] = ()
    chips_en: tuple[str, ...] = ()
    chips_ar: tuple[str, ...] = ()

    def chips(self, lang: str) -> list[dict]:
        src = self.chips_ar if lang == "ar" else self.chips_en
        return [{"label": c, "message": c} for c in src]


@dataclass
class Playbook:
    entries: dict[str, Entry] = field(default_factory=dict)

    def get(self, pid: str | None) -> Entry | None:
        return self.entries.get(pid or "") or self.entries.get(GENERIC)


_LIST_KEYS = ("examples", "policy", "chips_en", "chips_ar")


def parse(text: str) -> dict:
    """The strict YAML subset of playbook.yaml -> {"version": int, "entries": [dict, ...]}. Raises ValueError."""
    out: dict = {"entries": []}
    cur: dict | None = None
    key: str | None = None
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("version:"):
            out["version"] = int(s.split(":", 1)[1].strip())
            continue
        if s == "entries:":
            continue
        m = re.match(r"^-\s+id:\s*([a-z_]+)\s*$", s)
        if m:
            cur = {"id": m.group(1)}
            out["entries"].append(cur)
            key = None
            continue
        m = re.match(r"^([a-z_]+):\s*$", s)
        if m and cur is not None and m.group(1) in _LIST_KEYS:
            key = m.group(1)
            cur[key] = []
            continue
        if s.startswith("- ") and cur is not None and key:
            item = s[2:].strip()
            if not (item.startswith('"') and item.endswith('"')):
                raise ValueError(f"playbook.yaml line {n}: list items must be double-quoted strings")
            cur[key].append(json.loads(item))
            continue
        raise ValueError(f"playbook.yaml line {n}: unsupported syntax: {s[:60]}")
    return out


def load(path: str = PATH) -> Playbook:
    with open(path, encoding="utf-8") as f:
        data = parse(f.read())
    pb = Playbook()
    for e in data["entries"]:
        if e["id"] in pb.entries:
            raise ValueError(f"playbook.yaml: duplicate id {e['id']}")
        pb.entries[e["id"]] = Entry(e["id"], *(tuple(e.get(k) or ()) for k in _LIST_KEYS))
    return pb


try:
    PLAYBOOK = load()
except (OSError, ValueError) as exc:  # pragma: no cover - a broken file is caught by test_playbook.py
    log.error("playbook unavailable: %s", exc)
    PLAYBOOK = Playbook()


def select(intent: str | None, text: str = "", question_type: str | None = None, *, follow_up: bool = False,
           unknown: bool = False, reset: bool = False, refs: list | None = None, has_reference_context: bool = False,
           asked_field: str | None = None, price_published: bool | None = None) -> str:
    """The playbook id for one turn. Pure and deterministic: the same inputs always give the same id."""
    qt = (question_type or "").strip().lower()
    if qt in IDS:
        return qt
    if qt in QUESTION_TYPE_MAP:
        return QUESTION_TYPE_MAP[qt]
    if intent == "injection":
        return "injection"
    norm = normalize_text(text or "")
    if reset:
        return "topic_switch"
    if unknown:
        return "invented_or_false_premise"
    if _SITE_Q.search(norm) and intent not in ("calculation", "compare"):
        return "site_confusion"
    for pid, only, rx in _CUES:
        if only is not None and intent not in only:
            continue
        if rx.search(norm):
            return pid
    if refs or (has_reference_context and intent in ("project_info", "general", "compare")
                and _REF_Q.search(norm) and len(norm.split()) <= 8):
        return "compare" if intent == "compare" else "followup_reference"
    if intent == "project_info":
        if asked_field == "price" or (_PRICE_Q.search(norm) and not _FIELD_Q.search(norm)):
            return "price_not_published" if price_published is False else "single_attribute"
        if asked_field or (_FIELD_Q.search(norm) and len(norm.split()) <= 10):
            return "single_attribute"
        return "project_facts"
    if intent == "search" and follow_up:
        return "refine"
    return INTENT_MAP.get(intent or "", GENERIC)


GUIDANCE_RULES = ("Answer in the first sentence; lead with the name or the number.",
                  "Say what is missing in one clause, then offer the nearest thing that exists.",
                  "End with one concrete next step.",
                  "Reply in the user's language; keep project names in Latin script.")


def guidance(pid: str | None) -> str:
    """The <handling> block appended to the writer's system prompt. Guidance only: it never overrides the rules
    above it, is never a source of facts, and its text is never added to the allowed-number set."""
    e = PLAYBOOK.get(pid)
    if e is None or not e.policy:
        return ""
    lines = "\n".join(f"- {x}" for x in GUIDANCE_RULES + e.policy)
    return (f"\n<handling type=\"{e.id}\">\nGuidance for this kind of question. It never overrides the rules above "
            f"and is not a source of facts:\n{lines}\n</handling>")


def chips(pid: str | None, lang: str) -> list[dict]:
    e = PLAYBOOK.get(pid)
    return e.chips(lang) if e else []
