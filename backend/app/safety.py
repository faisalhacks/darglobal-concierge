"""Crisis / self-harm detector. Pure code, no model, no cache: it runs before every other intent.

A false positive costs one gentle message; a false negative can cost far more, so the patterns lean towards
catching. Idioms ("dying to see the villa", "this price is killing me", "to die for") are not matched because every
pattern needs an intent phrase (want / going to / wish ...) or a self-directed object (myself, my life).
"""
from __future__ import annotations

import re
import unicodedata

from .arabic import normalize_text

HELPLINE_HOST = "findahelpline.com"  # the only host the safety template may name (see guardrails.SAFETY_HOSTS)

_INTENT = (r"(?:wann?a|want(?:ed)?\s*(?:to|2|ta)|wish\s+i\s+(?:could|was|were|would)|going\s+to|gonna|ready\s+to|"
           r"need\s+to|have\s+to|rather|plan(?:ning)?\s+to|trying\s+to|try\s+to|about\s+to|thinking\s+(?:of|about))")
_DIE = r"(?:di+e+|dye+|be\s+dead|not\s+(?:be\s+)?alive|not\s+wake\s+up|never\s+wake\s+up)"
_NOT_IDIOM = (r"(?!\s*(?:laughing|of\s+(?:laughter|embarrassment|boredom|shame)|"
              r"for\s+(?:this|that|the|a|an|those|these|such)\b))")
_SELF = r"(?:my\s*self|myself|me\s*self|mysef|mself)"

EN = [
    rf"\b{_INTENT}\s+(?:just\s+|really\s+|finally\s+)?{_DIE}\b{_NOT_IDIOM}",
    rf"\b(?:kill|kil|killing|kll|unalive|unaliving|off|hang|hanging|shoot|shooting|drown|stab|poison|cut|cutting|slit|"
    rf"hurt|hurting|harm|harming|injure|injuring|end|ending|starve)\s+{_SELF}\b",
    r"\bkms\b|\bself[\s-]?harm\w*|\bselfharm\w*|\bself[\s-]?injur\w*",
    r"\b(?:slit|cut|cutting)\s+my\s+(?:wrists?|arms?|veins?|thighs?)\b",
    r"\b(?:end|ending|take|taking|finish|finishing)\s+(?:my\s+(?:own\s+)?life|my\s+existence)\b",
    r"\bend(?:ing)?\s+it\s+all\b|\bnot\s+wake\s+up\s+(?:tomorrow|again)\b",
    r"\b(?:suicid\w*|sucid\w*|suicied\w*|suiside\w*|suiced\w*|sucide\w*)\b",
    r"\b(?:don'?t|dont|dnt|do\s+not|doesn'?t|no\s+longer|never)\s+(?:want|wanna|wana)\s+(?:to\s+)?"
    r"(?:live|be\s+alive|be\s+here|exist|go\s+on|wake\s+up)\b",
    r"\bno\s+(?:reason|point|purpose)\s+(?:to|in|for)\s+(?:live|living|life|go\s*on|going\s+on|being\s+alive|exist\w*)\b",
    r"\bnothing\s+(?:left\s+)?to\s+live\s+for\b|\bnot\s+worth\s+living\b|\bnot\s+worth\s+it\s+to\s+live\b",
    r"\b(?:better|best)\s+off\s+dead\b|\bbetter\s+off\s+without\s+me\b",
    r"\b(?:can'?t|cant|cannot)\s+go\s+on\b",
    r"\bwish\s+i\s+(?:was|were|would\s+be)\s+dead\b|\bwish\s+i\s+(?:had\s+)?never\s+(?:been\s+born|existed)\b",
    r"\b(?:overdos\w*|take\s+all\s+my\s+pills)\b.{0,20}\b(?:myself|on\s+purpose|to\s+die)\b",
    # intent to harm others
    rf"\b(?:{_INTENT}|i\s+will|i'?ll)\s+(?:just\s+)?(?:kill|murder|shoot|stab|strangle|hurt|beat\s+up)\s+"
    r"(?:someone|somebody|people|everyone|everybody|him|her|them|a\s+person|my\s+(?:wife|husband|ex|boss|neighbou?r|"
    r"family|parents|mother|father|brother|sister|kids|children|girlfriend|boyfriend))\b",
    r"\b(?:going\s+on\s+a|planning\s+a)\s+(?:shooting|killing\s+spree|massacre)\b",
]

# Arabizi / Latin-script Arabic (lowercased Latin text).
ARABIZI = [
    r"\b(?:ab[i3y]|abgh?a|abghi|abg[ai]|ab3a|ubi|ubghi|bghi|badi|baddi|bdi|3ayez|3ayz|3ayiz|nefsi|nifsi|nfsi)\s+"
    r"(?:a|e)?m[ou]{1,2}t\b(?!\s*(?:men\s+el\s*d7k|3ala|fi\b))",
    r"\bma\s*(?:a?b\w{0,4}|bgh\w*|b3a)\s+a?3[eiy]{1,2}s?h?\b",
    r"\b(?:antahir|bantahir|bantahr|antahar|intihar|antehar|bantihr|bantihar|ba2tol|ba2tel)\b",
    r"\b(?:ba|a|an)?[2qk]t[oe]l\s+n[ae]fs[i]?\b|\b(?:ba|a)?[2qk]tl\s+nfs[i]?\b",
    r"\b(?:akhalis|bakhalis|a5alis|ba5alis|bakhallis)\s+(?:7ayati|hayati|3ala\s+nafsi|ala\s+nafsi)\b",
    r"\b(?:a|ba)?(?:2|o|u)?(?:z|th|dh)i\s+nafsi\b|\bauzi\s+nafsi\b",
    r"\bta3bt\s+(?:men|min)\s+(?:el|al)?\s*(?:7ayat|hayat|dunya)\b",
]

# Arabic, matched on normalize_text() output (alef forms folded, ى->ي, ة->ه, ؤ->و, ئ->ي).
_AR_WANT = (r"(?:ابي|ابغي|ابغا|ابغ|ابا|ابى|اريد(?:\s+ان)?|بدي|عايز|عاوز|نفسي(?:\s+ان)?|ودي(?:\s+ان)?|حابب(?:\s+ان)?|"
            r"اتمني(?:\s+ان)?|ناوي(?:\s+ان)?|ببغي|راح|رح|سوف|بدك|مضطر\s+ان)")
AR = [
    rf"{_AR_WANT}\s*(?:اموت|اقتل\s+نفسي|انتحر|اخلص\s+(?:حياتي|علي\s+نفسي)|انهي\s+حياتي|اودع\s+الدنيا)"
    r"(?!\s*(?:من\s+الضحك|علي|في))",
    r"انتحار|بنتحر|(?:^|\s)(?:انتحر|ننتحر|انتحرت)(?:\s|$)",
    r"(?:ما|لا|مو|مب)\s*(?:عاد\s+)?(?:ابي|ابغي|ابغا|ابغ|ابا|اريد|ابى|بدي|ودي)\s*(?:ان\s+)?(?:اعيش|احيا|ابقي\s+حي|"
    r"ابقي\s+علي\s+قيد\s+الحياه|استمر\s+في\s+الحياه|اكمل\s+حياتي)",
    r"(?:اقتل|اذبح|اشنق|اجرح|اوذي|اذي|ايذي|اضر|اقطع|احرق|اغرق|انهي|اسمم)\s*نفسي|"
    r"(?:ايذاء|اذيه|قتل|جرح|ذبح|شنق)\s*(?:نفسي|النفس)|اذيت\s+نفسي|اتاذي|اذي\s+ذاتي|اوذي\s+ذاتي|"
    r"(?:بقتل|رح\s+اقتل|راح\s+اقتل|بذبح|بجرح|بوذي|بشنق)\s*نفسي",
    r"(?:لا\s+يوجد|ما\s+في|مافي|ما\s+عندي|ماعندي|لا\s+اجد|ما\s+عاد\s+في|ما\s+عاد\s+عندي)\s+(?:اي\s+)?"
    r"(?:سبب|امل|فايده)\s+(?:ل|عشان|علشان|لاجل|من\s+اجل)?\s*(?:اعيش|احيا|استمر|الحياه|اكمل)",
    r"(?:تعبت|زهقت|مليت|سئمت|كرهت|يئست)\s+(?:من\s+)?(?:الحياه|حياتي|العيش|الدنيا)",
    r"(?:الموت|اموت)\s+(?:احسن|افضل|اريح)\s+(?:لي|من\s+الحياه|من\s+العيش)|احسن\s+لي\s+(?:اموت|الموت)|"
    r"(?:ليتني|يا\s+ليتني)\s+(?:مت|ميت|اموت|ما\s+ولدت)",
    r"(?:ابي|ابغي|ابغا|اريد|ودي|ناوي|بدي)\s+(?:ان\s+)?(?:اقتل|اذبح|اضرب|اطعن)\s+(?:احد|شخص|واحد|ناس|الناس|"
    r"زوجتي|زوجي|مديري|جاري|امي|اخي|اختي|اهلي|طليقي|طليقتي)",
]

_RX_EN = [re.compile(p, re.I) for p in EN]
_RX_ARZ = [re.compile(p, re.I) for p in ARABIZI]
_RX_AR = [re.compile(p) for p in AR]
_REPEAT = re.compile(r"(.)\1{2,}")
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "@": "a", "$": "s"})


def is_crisis(text: str) -> bool:
    """True for suicidal ideation, self-harm or a stated intent to hurt someone (EN / AR / Arabizi, typos)."""
    if not text:
        return False
    t = unicodedata.normalize("NFKC", text).lower().replace("’", "'").replace("`", "'")
    t = re.sub(r"\s+", " ", _REPEAT.sub(r"\1\1", t))
    # "k i l l  m y s e l f" / "s.u.i.c.i.d.e": join single letters separated by space or punctuation
    joined = re.sub(r"(?<=\b\w)[\s.\-_*](?=\w\b)", "", t)
    variants = {t, joined, t.translate(_LEET)}
    for v in list(variants):
        variants.add(re.sub(r"[^\w\s']", " ", v))
        variants.add(re.sub(r"[^\w\s]", "", v))
    for v in variants:
        if any(rx.search(v) for rx in _RX_EN) or any(rx.search(v) for rx in _RX_ARZ):
            return True
    base = re.sub(r"[^\w\s]", " ", normalize_text(text))
    for rep in (r"\1\1", r"\1"):  # stretched letters: "اموووت" -> "امووت" / "اموت"
        norm = re.sub(r"\s+", " ", _REPEAT.sub(rep, base)).strip()
        if any(rx.search(norm) for rx in _RX_AR):
            return True
    return False
