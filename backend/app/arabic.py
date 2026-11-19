"""Arabic normaliser + language detection (SPEC §8). Same function at index and query time."""
from __future__ import annotations

import re
import unicodedata

_DIACRITICS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")
_TATWEEL = "\u0640"
_ARABIC_CHAR = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")
_LATIN_CHAR = re.compile(r"[A-Za-z]")
_ARABIC_INDIC = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def normalize_arabic(text: str) -> str:
    """Strip diacritics/tatweel, unify alef forms, ى->ي, ة->ه, Arabic-Indic digits -> ASCII."""
    if not text:
        return ""
    t = _DIACRITICS.sub("", text).replace(_TATWEEL, "")
    t = re.sub("[أإآٱ]", "ا", t)
    t = t.replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي")
    t = t.translate(_ARABIC_INDIC)
    t = t.replace("٫", ".").replace("٬", ",").replace("،", ",").replace("؟", "?")
    return t


def normalize_text(text: str) -> str:
    """Full normalisation used for search keys: NFKC, Arabic normalisation, lowercase, collapse spaces."""
    t = unicodedata.normalize("NFKC", text or "")
    t = normalize_arabic(t).lower()
    return re.sub(r"\s+", " ", t).strip()


_TOKEN = re.compile(r"[a-z0-9]+|[\u0600-\u06FF]+")
_AR_PREFIXES = ("وال", "بال", "كال", "فال", "لل", "ال")


def tokenize(text: str) -> list[str]:
    """Tokens for BM25: normalised; Arabic definite-article / conjunction prefixes stripped."""
    out = []
    for tok in _TOKEN.findall(normalize_text(text)):
        if _ARABIC_CHAR.match(tok):
            for p in _AR_PREFIXES:
                if tok.startswith(p) and len(tok) - len(p) >= 2:
                    tok = tok[len(p):]
                    break
        out.append(tok)
    return out


def detect_lang(text: str, requested: str = "auto") -> str:
    if requested in ("en", "ar"):
        return requested
    ar = len(_ARABIC_CHAR.findall(text or ""))
    la = len(_LATIN_CHAR.findall(text or ""))
    if ar == 0:
        return "en"
    return "ar" if ar >= la * 0.5 else "en"
