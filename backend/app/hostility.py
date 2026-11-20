"""Hostility aimed at the concierge itself ("i will kill u", "f*** you", "you idiot"). Pure code, no model.

This is not the crisis detector: self-harm and threats against other people stay with safety.is_crisis(), which runs
first. A message caught here gets a calm, brief boundary and an offer to continue (template "hostile"), never the
crisis template and never a sales pitch. Teasing ("are you dumb", "r u stupid", "you suck", "انت غبي") is not
hostility: the planner routes it to banter, which answers good-humouredly.
"""
from __future__ import annotations

import re
import unicodedata

from .arabic import normalize_text

_YOU = r"(?:u|you|yu|ya|yuo|youu|this\s+bot|the\s+bot|this\s+(?:ai|thing|chatbot)|ur\s*self|yourself)"
_WILL = (r"(?:i\s*(?:'?ll|will|wil|wll|am\s+(?:going|gonna)\s+to|am\s+gonna|gonna|going\s+to|shall)|imma|ima|"
         r"i\s+want\s+to|i\s+wanna|i\s+wana)")
EN = [
    # threats at the assistant ("i will kill u"); "i will kill him" is a threat to a person: safety.is_crisis()
    rf"\b{_WILL}\s+(?:just\s+)?(?:kill|kil|murder|hurt|stab|shoot|beat|smash|destroy|hack|find)\s+{_YOU}\b",
    r"\b(?:kill|kys)\s+(?:ur\s*self|yourself|urself)\b|\bkys\b",
    rf"\b(?:f+u+c*k+|fk|fck|screw)\s+(?:off\b|{_YOU}\b)",
    r"\bf+\W?off\b|\bshut\s*(?:the\s+\w+\s+)?up\b|\bstfu\b",
    rf"\b(?:go\s+die|drop\s+dead|i\s+hate\s+{_YOU}|hope\s+{_YOU}\s+die)\b",
    # name-calling (not teasing questions)
    r"\b(?:you|u|ur|you'?re|youre|u\s*r)\s+(?:are\s+|r\s+)?(?:such\s+an?\s+|an?\s+|a\s+total\s+|a\s+fucking\s+)?"
    r"(?:idiot|moron|retard\w*|bitch|bastard|asshole|dickhead|piece\s+of\s+(?:shit|crap|garbage|trash))\b",
    r"\b(?:fucking|shitty)\s+(?:bot|ai|machine|assistant|chatbot|app)\b",
]
# Matched on normalize_text() output (alef forms folded, ة->ه, ى->ي).
AR = [
    r"(?:ساقتلك|بقتلك|راح\s*اقتلك|رح\s*اقتلك|اقتلك|بذبحك|اذبحك|ساذبحك|بموتك|راح\s*اذبحك)",
    r"(?:^|\s)(?:انت|انتي|يا)\s+(?:حمار|حيوان|كلب|حقير|زباله)(?:\s|$)",
    r"(?:اكرهك|انقلع|اسكت|انطم|تبا\s*لك|الله\s*ياخذك)",
]
ARABIZI = [r"\b(?:ba2tlak|ba2tolak|a2tlak|haqtlak|ha2tlak|bazba7ak)\b", r"\b(?:enta|inta|ya)\s+(?:7mar|hmar|kalb)\b"]

_RX_EN = [re.compile(p, re.I) for p in EN + ARABIZI]
_RX_AR = [re.compile(p) for p in AR]


def is_hostile_to_bot(text: str) -> bool:
    """True for a threat, profanity or name-calling aimed at the assistant (EN / AR / Arabizi)."""
    if not text:
        return False
    t = unicodedata.normalize("NFKC", text).lower().replace("’", "'")
    t = re.sub(r"(.)\1{2,}", r"\1\1", t)
    variants = {t, re.sub(r"[^\w\s']", " ", t)}
    if any(rx.search(v) for v in variants for rx in _RX_EN):
        return True
    norm = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", normalize_text(text))).strip()
    return any(rx.search(norm) for rx in _RX_AR)
