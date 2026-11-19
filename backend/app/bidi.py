"""Bidi isolation for Arabic answers: every Latin run (project names, units, amounts with a Latin currency) is wrapped
in a first-strong isolate (FSI U+2068 ... PDI U+2069) so it keeps its own order inside right-to-left prose. Sentence
punctuation, including the Arabic comma "،", always stays OUTSIDE the isolate. Mirrors frontend/lib/bidi.ts."""
from __future__ import annotations

import re

FSI, PDI = "\u2068", "\u2069"
_ARABIC = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")

_L = "A-Za-z\u00c0-\u024f"
_NUM = r"\d[\d,]*(?:\.\d+)?"
_CUR = r"(?:SAR|USD|AED|EUR|GBP|INR|OMR|QAR|BHD)"
_SCALE = r"(?:\s?(?:k|m|mn|bn|million|billion|thousand)(?![A-Za-z]))?"
_UNIT = r"(?:m\u00b2|m2|sqm|sq\s?ft)"
# Amounts that carry a Latin currency or unit: "$500,000", "€1.2m", "USD 500,000", "1,180,000 USD", "120 m²".
_AMOUNT = (rf"(?:[$\u00a3\u20ac\u20b9]\s?{_NUM}{_SCALE}|{_CUR}\s?{_NUM}{_SCALE}|{_NUM}{_SCALE}\s?{_CUR}(?![A-Za-z])"
           rf"|{_NUM}\s?{_UNIT}(?![A-Za-z0-9]))")
# A Latin run: name punctuation and digits inside, always ending on a letter or digit, so trailing punctuation stays
# outside; an ASCII ", " inside a name ("Neptune, Interiors by Mouawad") keeps the name in one run. A space may be followed by a Latin letter or a short number ("Aida 2"), never by a long amount.
_LATIN = (rf"(?:\d+(?:[&\-]\d+)?[\s\-]?)?[{_L}](?:[{_L}\d&'\u2019.@/:_\-\u2013]|\s(?=[{_L}&]|\d{{1,2}}(?![\d,.]))|,\s(?=[{_L}]))*"
          rf"[{_L}\d]|[{_L}]")
_RUN = re.compile(rf"{_AMOUNT}|{_LATIN}")
_ISOLATED = re.compile(rf"{FSI}[^{PDI}]*{PDI}")
_NOT_PUNCT = re.compile(r"[\s\.,\u060c\u061b:;!?\u061f]+$")


def isolate_latin(text: str) -> str:
    """Wrap every Latin run in FSI...PDI when `text` contains Arabic. Idempotent; already isolated spans are kept."""
    if not text or not _ARABIC.search(text):
        return text
    out, last = [], 0
    for iso in list(_ISOLATED.finditer(text)) + [None]:
        seg_end = iso.start() if iso else len(text)
        seg = text[last:seg_end]
        out.append(_RUN.sub(lambda m: FSI + m.group(0).rstrip() + PDI + (m.group(0)[len(m.group(0).rstrip()):]), seg))
        if iso:
            out.append(iso.group(0))
            last = iso.end()
    return "".join(out)
