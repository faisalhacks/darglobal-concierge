"""Code planner (SPEC §9): rules + entity extraction, no LLM.

Intents: project_info, compare, search, calculation, location_overview, brand_partner, contact_sales,
find_my_home, off_topic, injection, advice, general, plus conversation intents decided in code before retrieval:
greeting, thanks, goodbye, identity, ack (small talk) and vague (short query with nothing specific to look up).
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from .arabic import normalize_text
from .conversation import _VAGUE_WORDS, _INVEST, _LUXURY, _dist, compound_smalltalk, conversational_intent, is_vague, simple_arithmetic, vague_topic
from .conversation import Memory, has_reference, is_reset, validate_entity_ids
from .guardrails import is_injection
from .store import Store

# Canonical place name -> aliases (EN + AR, matched on normalised text).
PLACE_ALIASES: dict[str, list[str]] = {
    "Dubai": ["dubai", "dubay", "dubaii", "dubi", "دبي"],
    "Abu Dhabi": ["abu dhabi", "abudhabi", "ابوظبي", "ابو ظبي"],
    "Ras Al Khaimah": ["ras al khaimah", "rak", "راس الخيمه"],
    "United Arab Emirates": ["uae", "united arab emirates", "emirates", "الامارات", "الامارات العربيه المتحده",
                             "دوله الامارات"],
    "Riyadh": ["riyadh", "riyad", "ryadh", "riyadh city", "riadh", "riyaad", "الرياض", "رياض"],
    "Jeddah": ["jeddah", "jedda", "jeddha", "jiddah", "jidda", "jaddah", "jedah", "جده"],
    "Makkah": ["makkah", "mecca", "makka", "makah", "مكه"],
    "Madinah": ["madinah", "medina", "madina", "medinah", "المدينه المنوره", "المدينه"],
    "Dammam": ["dammam", "damam", "dammam city", "الدمام"],
    "Khobar": ["khobar", "al khobar", "الخبر"],
    "Saudi Arabia": ["saudi arabia", "saudi", "ksa", "السعوديه", "المملكه العربيه السعوديه", "المملكه"],
    "Muscat": ["muscat", "masqat", "muscut", "maskat", "مسقط"],
    "Oman": ["oman", "عمان", "سلطنه عمان"],
    "Doha": ["doha", "الدوحه"],
    "Qatar": ["qatar", "قطر", "دوله قطر"],
    "Bahrain": ["bahrain", "البحرين"],
    "London": ["london", "لندن"],
    "United Kingdom": ["uk", "united kingdom", "england", "britain", "بريطانيا", "المملكه المتحده"],
    "Marbella": ["marbella", "ماربيا", "ماربيلا"],
    "Spain": ["spain", "españa", "espana", "اسبانيا", "اسبانيه"],
    "Benahavís": ["benahavis", "benahavís", "بيناهافيس"],
    "Cortesin": ["cortesin", "كورتيسين"],
    "Simaisma": ["simaisma", "سميسمه"],
    "Maldives": ["maldives", "المالديف"],
    "Bosnia": ["bosnia", "البوسنه"],
    "Greece": ["greece", "اليونان"],
}

# Arabic display names (proper spelling, not the normalised search form).
PLACE_AR = {
    "Dubai": "دبي", "Abu Dhabi": "أبوظبي", "Ras Al Khaimah": "رأس الخيمة", "United Arab Emirates": "الإمارات",
    "Riyadh": "الرياض", "Jeddah": "جدة", "Makkah": "مكة المكرمة", "Madinah": "المدينة المنورة", "Dammam": "الدمام",
    "Khobar": "الخبر", "Saudi Arabia": "السعودية", "Muscat": "مسقط", "Oman": "عُمان", "Doha": "الدوحة",
    "Qatar": "قطر", "Bahrain": "البحرين", "London": "لندن", "United Kingdom": "المملكة المتحدة",
    "Marbella": "ماربيا", "Spain": "إسبانيا", "Al Khobar": "الخبر", "Simaisma": "سميسمة", "Maldives": "المالديف", "Bosnia": "البوسنة", "Greece": "اليونان",
}


def place_display(name: str | None, lang: str) -> str:
    if not name:
        return ""
    if lang != "ar":
        return name
    return PLACE_AR.get(name) or next((PLACE_AR[k] for k in PLACE_AR if k.lower() == name.lower()), name)


CURRENCIES = {
    "aed": "AED", "dirham": "AED", "dirhams": "AED", "درهم": "AED",
    "sar": "SAR", "riyal": "SAR", "riyals": "SAR", "ريال": "SAR", "sr": "SAR",
    "usd": "USD", "dollar": "USD", "dollars": "USD", "$": "USD", "دولار": "USD",
    "omr": "OMR", "qar": "QAR", "bhd": "BHD",
    "gbp": "GBP", "£": "GBP", "pound": "GBP", "pounds": "GBP", "sterling": "GBP", "استرليني": "GBP",
    "eur": "EUR", "€": "EUR", "euro": "EUR", "euros": "EUR", "يورو": "EUR",
    "inr": "INR", "₹": "INR", "rupee": "INR", "rupees": "INR", "روبيه": "INR",
}

_AR_NUM_WORDS = {"غرفه": 1, "غرفتين": 2, "غرفتان": 2}


@dataclass
class Entities:
    project_ids: list[str] = field(default_factory=list)
    city: str | None = None
    country: str | None = None
    place: str | None = None
    budget_min: float | None = None
    budget_max: float | None = None
    beds: int | None = None
    currency: str | None = None
    listing_type: str | None = None
    property_type: str | None = None
    brand: str | None = None
    site: str | None = None
    handover_year: int | None = None  # "handover 2027 projects"
    baths: int | None = None
    furnished: bool = False
    area_m2: float | None = None  # "1500 sqft" -> 139.4 (converted), "120 sqm" -> 120
    sort: str | None = None  # "price_asc" for cheap / affordable / lowest price

    def key(self) -> str:
        return "|".join(map(str, [sorted(self.project_ids), self.city, self.country, self.budget_min, self.budget_max,
                                  self.beds, self.currency, self.listing_type, self.property_type, self.brand, self.site,
                                  self.area_m2, self.sort]))

    def listing_signal(self) -> bool:
        """Anything that only a listing search answers: bedrooms, a budget, a size, a cheapest-first sort."""
        return (self.beds is not None or self.budget_max is not None or self.budget_min is not None
                or self.area_m2 is not None or self.sort is not None or self.baths is not None or self.furnished)


@dataclass
class Plan:
    intent: str
    entities: Entities
    ambiguous: bool = False
    follow_up: bool = False
    unknown: str | None = None  # a named project/place the user asked about that is not in the dataset
    unknown_place: bool = False  # `unknown` was named as a place ("projects in Tokyo"), not as a project
    text: str | None = None  # rewritten message for a follow-up ("And if it was 150 m2?" -> full calculation)
    step: int = 0  # find-my-home step (1 = ask place, 2 = ask budget, 3 = ask purpose, 4 = shortlist)
    topic: str | None = None  # vague: luxury | invest | ptype | generic
    adjacent: bool = False  # the message also asks a property-adjacent question (visa, finance, tax ...)
    adjacent_topic: str | None = None  # visa | finance | tax | ownership | living
    refs: list[str] = field(default_factory=list)  # ids resolved from Memory.last_entities ("the second one")
    memory: Memory | None = None  # the stateless conversation memory this plan was built with (history present)
    question_type: str | None = None  # from the understanding call, when it ran (playbook selection, trace)


# ---------------- existence gate (SPEC §0 never invent, R7 traps) ----------------
_NAMED_EN = re.compile(r"\b(?:project|development|tower|building|compound|community|villas?|residences?)\s+"
                       r"(?:called|named)\s+[\"'“]?([a-z0-9][a-z0-9' -]{1,40}?)[\"'”]?"
                       r"(?=\s+(?:in|and|at|with|located|by|that|which)\b|\s*[?,.!]|$)", re.I)
_NAMED_AR = re.compile(r"(?:مشروع|مشروعا|برج|مجمع)\s+(?:اسمه|يسمي|باسم|يدعي)\s+(.{2,40}?)(?=\s+(?:في|و)\s|\s*و?سعر|[?,.!]|$)")
_ABOUT_EN = re.compile(r"\b(?i:tell me about|what about|info(?:rmation)? (?:on|about)|details (?:on|of|about)|"
                       r"what is|what's)\s+(?i:the\s+)?([A-Z][\w'&-]*(?:\s+[A-Z0-9][\w'&-]*){1,5})")
_PROPERTY_EN = re.compile(r"\b((?:[A-Z][\w'&-]+\s+){1,4}(?:Residences?|Towers?|Villas|Heights|Palace|Gardens|Bay|Hills|"
                          r"Estates?|Mansions|Plaza|Lagoon|Island|Resort|Penthouses?|Lofts?|Suites|Court|Point|Collection)"
                          r"(?:\s+[A-Z][\w'&-]+){0,2})\b")
_PROJECT_AR = re.compile(r"(?:سعر|عن|تفاصيل|موقع|تسليم)\s+مشروع\s+(.{2,40}?)(?=\s+(?:في|ب|و)\s|\s*[?,.!]|$)")
_PLACE_EN = re.compile(r"\b(?:in|at|near|around)\s+(?:the\s+|your\s+|a\s+)?([A-Z][a-z]{2,}(?:\s+[A-Z][a-zA-Z0-9]{1,})*)")
_NOT_PLACES = {"english", "arabic", "sar", "aed", "usd", "january", "february", "march", "april", "may", "june",
               "july", "august", "september", "october", "november", "december", "total", "cash", "installments"}
UNPUBLISHED = [
    ("mortgage_rate", r"(mortgage|interest|financing|finance)\s+(interest\s+)?rates?|rates?\s+(of|for)\s+(mortgage|interest)"
                      r"|apr\b|سعر الفائده|نسبه الفائده|نسبه التمويل"),
    ("cancellation", r"(?<![a-z])(cancel|cancell?ed|cancell?ation|scrapped|abandoned)(?![a-z])|الغاء|الغي|الغيت"),
    ("units_sold", r"units?\s+(have\s+|has\s+)?(been\s+|already\s+)?sold|how many (units|apartments|villas) (are|were) sold"
                   r"|how many (units|apartments|villas|homes)\b.{0,80}\b(sold|left|remaining|available)\b"
                   r"|كم (وحده|شقه|فيلا).{0,40}(بيع|بيعت|مباعه|متبقيه)"),
]


def unpublished_topic(message: str) -> str | None:
    norm = normalize_text(message)
    return next((k for k, rx in UNPUBLISHED if re.search(rx, norm)), None)


def _known_name(name: str, store: Store) -> bool:
    n = normalize_text(name).strip(" -'\"")
    if len(n) < 3:
        return True
    for p in store.projects:
        for alias in project_aliases(p):
            if n in alias or alias in n or difflib.SequenceMatcher(None, n, alias).ratio() >= 0.8:
                return True
    for x in store.listings:
        if n and n in normalize_text(x.get("title") or ""):
            return True
    # A collected page's own title ("Buying Real Estate in Saudi Arabia 2026") is in the data, not an unknown name.
    for pg in getattr(store, "pages", None) or []:
        if n and n in normalize_text(pg.get("title") or ""):
            return True
    return False


def _known_place(word: str, store: Store) -> bool:
    n = normalize_text(word)
    first = n.split()[0] if n else n
    if not n or n in _NOT_PLACES or first in _NOT_PLACES:
        return True
    aliases = {a for al in PLACE_ALIASES.values() for a in al}
    vals = {normalize_text(v) for r in store.projects + store.listings
            for v in (r.get("city"), r.get("country"), r.get("district")) if v}
    if any(n == a or n.startswith(a + " ") or a.startswith(n) for a in aliases | vals):
        return True
    if any(t in ("wasalt", "darglobal", "dar") for t in n.split()):
        return True
    return _known_name(word, store)


def unknown_entity(message: str, norm: str, ent: Entities, store: Store) -> str | None:
    """A project or place the user names explicitly that the dataset does not contain. Answering such a question
    with nearby real data reads as confirmation, so the planner routes it to a not-found template instead."""
    return unknown_entity_kind(message, norm, ent, store)[0]


def unknown_entity_kind(message: str, norm: str, ent: Entities, store: Store) -> tuple[str | None, bool]:
    """(name, is_place) for `unknown_entity`; is_place is True when the name was given as a place ("in Tokyo")."""
    name = _unknown_name(message, norm, ent, store)
    if name is None:
        return None, False
    return name, any(m.group(1).strip() == name for m in _PLACE_EN.finditer(message or ""))


def _unknown_name(message: str, norm: str, ent: Entities, store: Store) -> str | None:
    raw = re.sub(r"\s+", " ", message or "").strip()  # keep the user's casing for the reply
    for rx, src in ((_NAMED_EN, raw), (_NAMED_AR, norm)):
        m = rx.search(src)
        if m and not _known_name(m.group(1), store):
            return m.group(1).strip()
    for m in _PROPERTY_EN.finditer(raw):  # "Obsidian Palm Residences", "Zephyr Lagoon Towers"
        name = m.group(1).strip()
        if not ent.project_ids and not _known_name(name, store) and not _known_place(name, store):
            return name
    m = _PROJECT_AR.search(norm)  # "ما سعر مشروع نخيل الاوبسيديان في مسقط"
    if m and not ent.project_ids:
        cand = m.group(1).strip()
        if cand and not _is_generic(cand) and not _known_name(cand, store) and not _known_place(cand, store):
            return cand
    if ent.project_ids or ent.city or ent.country:
        return None
    m = _ABOUT_EN.search(raw)
    if m and not _known_place(m.group(1), store):
        return m.group(1).strip()
    for m in _PLACE_EN.finditer(message or ""):
        cand = m.group(1).strip()
        if not _known_place(cand, store):
            return cand
    return None


_AR_PROCLITIC = r"(?:[وفبلك]|وب|ول|فب)?"


def _has(norm: str, words) -> bool:
    return any(re.search(rf"(?<![\w]){re.escape(w)}(?![\w])", norm) for w in words)


def _has_place(norm: str, alias: str) -> bool:
    """Alias match that also accepts Arabic proclitics (و/ف/ب/ل/ك) glued to the word, e.g. "بدبي", "بالرياض"."""
    if re.search(r"[\u0600-\u06FF]", alias):
        a = re.escape(alias)
        if alias.startswith("ال"):  # "بالرياض" / "للرياض": the proclitic absorbs or replaces the article
            a = rf"(?:{a}|{re.escape(alias[2:])})"
        return bool(re.search(rf"(?<![\w]){_AR_PROCLITIC}{a}(?![\w])", norm))
    return _has(norm, [alias])


# ---------------- entity extraction ----------------
def parse_amount(num: str, suffix: str | None) -> float | None:
    try:
        v = float(num.replace(",", ""))
    except ValueError:
        return None
    s = (suffix or "").lower().strip()
    if s in ("k", "thousand", "الف", "آلاف", "الاف"):
        v *= 1_000
    elif s in ("m", "mn", "million", "millions", "مليون", "ملايين"):
        v *= 1_000_000
    elif s in ("b", "bn", "billion", "مليار"):
        v *= 1_000_000_000
    return v


_AMOUNT = r"(?<![a-z0-9.,])(\d[\d,]*(?:\.\d+)?)\s*(k|m|mn|million|millions|thousand|bn|billion|مليون|ملايين|الف|الاف|مليار)?(?![a-z])"


def _ar_amount_words(norm: str) -> str:
    """"أقل من مليون" -> "أقل من 1 مليون", "مليونين" -> "2 مليون", "نص مليون" -> "500000"; digits already ASCII."""
    t = re.sub(r"(?:نص|نصف) مليون", "500000", norm)
    t = re.sub(r"مليونين|مليونان", "2 مليون", t)
    t = re.sub(r"(?<![\d.,]\s)(?<![\d.,])(?<!\d )(مليون|الف)(?![\w])", r"1 \1", t)
    return re.sub(r"(\d)\s+(\d)", r"\1\2", t)


def extract_budget(norm: str) -> tuple[float | None, float | None]:
    norm = _ar_amount_words(norm)
    lo = hi = None
    m = re.search(rf"(under|below|less than|up to|upto|max|maximum|within|budget(?:\s+(?:of|is|around|about|approx\w*|roughly))?|اقل من|تحت|حتى|حتي|بحدود|في حدود|ميزانيتي|ميزانيه)\s*(?:[a-z$£€]{{0,4}}\s*)?{_AMOUNT}", norm)
    if m:
        hi = parse_amount(m.group(2), m.group(3))
    lo_src = re.sub(r"(?:اقل|ادني|اقصي) من", " ", norm)  # "أقل من مليون" is a maximum, not "from a million"
    m = re.search(rf"(over|above|more than|at least|min|minimum|from|اكثر من|فوق|(?<![\w])من)\s*(?:[a-z$£€]{{0,4}}\s*)?{_AMOUNT}", lo_src)
    if m and not re.search(r"\d\s*%", lo_src[m.start():m.end() + 2]):
        lo = parse_amount(m.group(2), m.group(3))
    m = re.search(rf"between\s*{_AMOUNT}\s*(?:and|-|to)\s*{_AMOUNT}", norm)
    if m:
        lo, hi = parse_amount(m.group(1), m.group(2)), parse_amount(m.group(3), m.group(4))
    return lo, hi


_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "single": 1, "double": 2}
_BED_WORD = r"(?:beds?|bedrooms?|bedroomed|bed rooms?|br|bd|bdr|bdrm|bhk|b/r|rooms?|غرف|غرفه نوم|غرف نوم)"


def extract_beds(norm: str) -> int | None:
    m = re.search(rf"(?<![\d.,])(\d{{1,2}})\s*[- ]?\s*{_BED_WORD}(?![a-z])", norm)
    if m:
        return int(m.group(1))
    m = re.search(rf"(?<![a-z])(one|two|three|four|five|six|single|double)[- ]?{_BED_WORD}(?![a-z])", norm)
    if m:
        return _NUM_WORDS[m.group(1)]
    if re.search(r"(?<![a-z])(studio|\d\s*rk)(?![a-z])|استوديو", norm):  # "1 RK" (room + kitchen) is a studio
        return 0
    for w, n in _AR_NUM_WORDS.items():
        if w in norm:
            return n
    return None


_SQFT = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(sq\.?\s*ft|sqft|square f(?:ee|oo)t|ft2|ft²)(?![a-z])")
_SQM = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(sqm|sq\.?\s*m|m2|m²|square met(?:er|re)s?|متر مربع|م2)(?![a-z])")
_CHEAP = re.compile(r"(?<![a-z])(cheap|cheapest|affordable|low[- ]?cost|lowest price|inexpensive|economical)"
                    r"(?![a-z])|رخيص|ارخص|اقتصادي|بسعر مناسب")


def extract_area(norm: str) -> float | None:
    m = _SQFT.search(norm)
    if m:
        return round(float(m.group(1).replace(",", "")) * 0.092903, 1)
    m = _SQM.search(norm)
    if m:
        return float(m.group(1).replace(",", ""))
    return None


def extract_currency(norm: str) -> str | None:
    for tok, cur in CURRENCIES.items():
        if tok in ("$", "£", "€"):
            if tok in norm:
                return cur
        elif re.search(rf"(?<![\w]){re.escape(tok)}(?![\w])", norm):
            return cur
    return None


def extract_places(norm: str, store: Store) -> tuple[str | None, str | None, str | None]:
    """Returns (city, country, display_place). Alias -> canonical -> matched against DB columns."""
    cities = {normalize_text(p.get("city") or ""): p.get("city") for p in store.projects + store.listings if p.get("city")}
    countries = {normalize_text(p.get("country") or ""): p.get("country") for p in store.projects if p.get("country")}
    found_city = found_country = place = None
    # longest aliases first so "abu dhabi" wins over shorter tokens
    pairs = sorted(((a, canon) for canon, al in PLACE_ALIASES.items() for a in al), key=lambda x: -len(x[0]))
    for alias, canon in pairs:
        if _has_place(norm, alias):
            key = normalize_text(canon)
            if key not in cities and key not in countries:
                # DB spelling may differ ("Al Khobar" vs "Khobar")
                key = next((k for k in cities if k.endswith(" " + key) or k.startswith(key + " ")), key)
            if key in cities and not found_city:
                found_city, place = cities[key], place or cities[key]
            elif key in countries and not found_country:
                found_country, place = countries[key], place or canon
            elif not place:
                place = canon
    # DB values not in the alias table
    for key, val in cities.items():
        if not found_city and len(key) >= 3 and _has(norm, [key]):
            found_city, place = val, place or val
    for key, val in countries.items():
        if not found_country and len(key) >= 3 and _has(norm, [key]):
            found_country, place = val, place or val
    return found_city, found_country, place


_GENERIC_NAME_TOKENS = {"the", "tower", "towers", "residences", "residence", "by", "project", "dar", "global",
                        "darglobal", "and", "of", "at", "in", "for", "sale", "rent", "villa", "villas", "apartment",
                        "apartments", "floors", "compound", "مشروع", "برج", "ابراج", "فلل", "فيلا", "للبيع", "للايجار",
                        "شقق", "شقه", "ادوار", "دور", "و", "-", "مجمع", "سكني"}


def _is_generic(alias: str) -> bool:
    toks = [t for t in re.split(r"[\s\-–]+", alias) if t]
    return all(t in _GENERIC_NAME_TOKENS or t.isdigit() for t in toks)


# Arabic spellings users type for DarGlobal projects whose rows carry no name_ar. Query matching only: they are never
# shown as a project name (cards and prose use the published names).
PROJECT_QUERY_ALIASES: dict[str, list[str]] = {
    "dg-da-vinci-tower-interiors-by-pagani": ["برج دافنشي", "برج دا فينشي", "دافنشي", "دا فينشي"],
    "dg-the-astera-interiors-by-aston-martin": ["ذا استيرا", "استيرا", "ذي استيرا", "استون مارتن"],
    "dg-w-residences": ["دبليو ريزيدنسز", "دبليو رزيدنس", "مساكن دبليو"],
    "dg-trump-tower-jeddah": ["ترامب تاور جده", "برج ترامب جده", "ترمب تاور جده", "برج ترمب جده", "trump tower jedda"],
    "dg-neptune-interiors-by-mouawad": ["نبتون", "نيبتون", "نبتون معوض"],
    "dg-marriott-residences": ["ماريوت عايده", "ماريوت ريزيدنسز", "مساكن ماريوت", "ماريوت"],
    "dg-aida": ["عايده", "ايدا", "عايدة"],
    "dg-les-vagues-by-elie-saab": ["لي فاغ", "ليه فاغ", "لي فاج", "لي فاغ ايلي صعب", "ايلي صعب"],
    "dg-tierra-viva-design-inspired-by-automobili-lamborghini": ["تييرا فيفا", "تيرا فيفا", "تيارا فيفا"],
    "dg-urban-oasis-by-missoni": ["اوربان اواسيس", "اوربان اوايسس", "ميسوني"],
    "dg-trump-plaza-jeddah": ["ترامب بلازا جده", "ترامب بلازا"],
    "dg-the-mulliner": ["ذا مولينر", "مولينر"],
    "dg-trump-international-hotel-and-tower-dubai": ["برج ترامب دبي", "فندق وبرج ترامب الدولي دبي", "ترامب دبي"],
}


def project_aliases(p: dict) -> list[str]:
    out = [normalize_text(a) for a in PROJECT_QUERY_ALIASES.get(p.get("id") or "", [])]
    for k in ("name_en", "name_ar"):
        v = p.get(k)
        if not v:
            continue
        n = normalize_text(v)
        cands = [n, n.split(" - ")[0].strip(), n.split(", ")[0].strip(),
                 re.split(r"\s+(?:interiors by|design inspired by|by)\s+", n)[0].strip()]
        cands += [re.sub(r"^(the|مشروع)\s+", "", c) for c in cands]
        for c in cands:
            c = re.sub(r"\s+", " ", c).strip(" -")
            if len(c) >= 3 and not _is_generic(c):
                out.append(c)
    return list(dict.fromkeys(out))


def _ar_prefixed(norm: str, idx: int, alias: str) -> bool:
    """An Arabic name glued to a one-letter prefix ("ونبتون" = "and Neptune", "لنبتون", "بنبتون") still names it."""
    return (idx >= 1 and norm[idx - 1] in "ولبف" and "؀" <= alias[0] <= "ۿ"
            and (idx == 1 or not norm[idx - 2].isalnum()))


def extract_projects(norm: str, store: Store) -> list[str]:
    hits: list[tuple[int, str]] = []
    words = norm.split()
    for p in store.projects:
        best = None
        for alias in project_aliases(p):
            idx = norm.find(alias)
            if idx >= 0 and (idx == 0 or not norm[idx - 1].isalnum() or _ar_prefixed(norm, idx, alias)):
                best = idx if best is None else min(best, idx)
                continue
            # fuzzy: compare alias against same-length word windows. A one-word alias needs >= 6 letters and a
            # closer match ("area" must not match the project "Marea").
            n = len(alias.split())
            if n == 1 and (alias in _GENERIC_NAME_TOKENS or len(alias) < 6):
                continue
            for i in range(0, max(len(words) - n + 1, 0)):
                window = " ".join(words[i:i + n])
                if len(window) >= 4 and difflib.SequenceMatcher(None, window, alias).ratio() >= (0.86 if n > 1 else 0.92):
                    pos = norm.find(window)
                    best = pos if best is None else min(best, pos)
                    break
        if best is not None:
            span = max((len(a) for a in project_aliases(p) if norm.find(a) == best), default=0)
            hits.append((best, -span, p["id"]))
    hits.sort()
    # "Amour Sans Detour 2" also contains "Amour Sans Detour": drop a match that lies inside a longer one.
    spans = [(pos, pos - neg, pid) for pos, neg, pid in hits]
    kept = [pid for s0, e0, pid in spans
            if not any(s1 <= s0 and e0 <= e1 and (e1 - s1) > (e0 - s0) for s1, e1, _ in spans)]
    return list(dict.fromkeys(kept))


_BARE_MONEY = re.compile(
    r"(?:[$£€]|usd|sar|aed|riyals?|ريال|درهم|دولار)\s*(\d[\d,]*(?:\.\d+)?)\s*(k|m|mn|million|مليون|الف)?(?![a-z])"
    r"|(?<![a-z0-9.,])(\d[\d,]*(?:\.\d+)?)\s*(k|m|mn|million|مليون|الف)(?![a-z])")


def extract_entities(text: str, store: Store) -> Entities:
    norm = normalize_text(text)
    e = Entities()
    e.project_ids = extract_projects(norm, store)
    e.city, e.country, e.place = extract_places(norm, store)
    e.area_m2 = extract_area(norm)
    # a size is not a budget: "1500 sqft" must not read as "from 1500"
    e.budget_min, e.budget_max = extract_budget(_SQM.sub(" ", _SQFT.sub(" ", norm)))
    e.beds = extract_beds(norm)
    if _CHEAP.search(norm):
        e.sort = "price_asc"
    m = re.search(r"(?<![\d.,])(\d{1,2})\s*[- ]?\s*(baths?|bathrooms?|bathroms?|bathrms?|ba|wc|حمام|حمامات|دوره مياه)(?![a-z])", norm)
    if m:
        e.baths = int(m.group(1))
    if re.search(r"(?<![a-z])(furnished|furnish)(?![a-z])|مفروش", norm) and not re.search(r"unfurnished|غير مفروش", norm):
        e.furnished = True
    m = re.search(r"(?<![a-z])(handover|hand over|completion|completing|delivery|ready|ready by|تسليم|التسليم)\D{0,25}"
                  r"(20[2-4]\d)|(20[2-4]\d)\D{0,15}(handover|completion|delivery|تسليم)", norm)
    if m:
        e.handover_year = int(m.group(2) or m.group(3))
        if e.budget_min == e.handover_year or e.budget_max == e.handover_year:
            e.budget_min = e.budget_max = None
    e.currency = extract_currency(norm)
    if _has(norm, ["rent", "rental", "rentals", "renting", "for rent", "to rent", "lease", "leasing", "to let",
                   "yearly rent", "monthly rent", "monthly", "per month", "yearly", "per year", "annual rent", "شهري", "ايجار", "للايجار", "استئجار", "استاجر", "اجار"]):
        e.listing_type = "rent"
    elif _has(norm, ["buy", "buying", "for sale", "sale", "purchase", "purchasing", "own", "to own", "ownership",
                     "للبيع", "شراء", "بيع", "اشتري", "تملك", "للشراء", "للتملك", "ابي اشتري", "ابغي اشتري"]):
        e.listing_type = "buy"
    for ptype, words in (("villa", ["villa", "villas", "فيلا", "فلل", "فيلات"]),
                         ("apartment", ["apartment", "apartments", "apt", "apts", "flat", "flats", "condo", "شقه", "شقق"]),
                         ("townhouse", ["townhouse", "townhouses", "تاون هاوس"]),
                         ("penthouse", ["penthouse", "penthouses", "بنتهاوس"]),
                         ("land", ["land", "plot", "plots", "lands", "ارض", "اراضي"]),
                         ("duplex", ["duplex", "duplexes", "دوبلكس"]),
                         ("office", ["office", "offices", "office space", "مكتب", "مكاتب"]),
                         ("showroom", ["showroom", "showrooms", "shop", "shops", "retail", "معرض", "محل"]),
                         ("warehouse", ["warehouse", "warehouses", "مستودع", "مستودعات"])):
        if _has(norm, words):
            e.property_type = ptype
            break
    if e.property_type is None:  # typos: "appartment", "vila", "apartmnt", "penthous"
        for tok in re.findall(r"[a-z]{4,}", norm):
            for ptype, word in (("apartment", "apartment"), ("apartment", "apartments"), ("villa", "villa"),
                                ("villa", "villas"), ("townhouse", "townhouse"), ("penthouse", "penthouse")):
                if tok != word and abs(len(tok) - len(word)) <= 2 and _dist(tok, word) <= (1 if len(word) <= 6 else 2):
                    e.property_type = ptype
                    break
            if e.property_type:
                break
    if e.budget_max is None and e.budget_min is None and e.property_type is not None:
        # "$500k apartment", "villa 2m riyal", "1.5 million dollars apartment": a bare money amount next to a
        # property word is a ceiling (sizes are removed first, so "120 m2" is never read as 120 million)
        m = _BARE_MONEY.search(_SQM.sub(" ", _SQFT.sub(" ", norm)))
        if m:
            e.budget_max = parse_amount(m.group(1) or m.group(3), m.group(2) or m.group(4))
    if _has(norm, ["wasalt", "وصلت"]):
        e.site = "Wasalt"
    elif _has(norm, ["darglobal", "dar global", "دار جلوبال", "دار غلوبال"]):
        e.site = "DarGlobal"
    brands = {normalize_text(p["brand_partner"]): p["brand_partner"] for p in store.projects if p.get("brand_partner")}
    for key, val in sorted(brands.items(), key=lambda kv: -len(kv[0])):
        if len(key) >= 3 and key in norm:
            e.brand = val
            break
    return e


# ---------------- intent rules ----------------
ADVICE = [r"\b(better|best|smarter)\b.{0,50}\b(for )?invest", r"\binvest\w*\b.{0,30}\b(better|best)\b", r"\bguarantee", r"\broi\b", r"return on investment", r"\bgood investment\b", r"\bbest investment\b",
          r"should i (buy|invest)", r"\bwill (the )?(prices?|values?|it) (rise|go up|increase|appreciate)",
          r"capital (appreciation|gain)", r"\bprofit\b", r"\bworth investing\b", r"\bis it a good time\b",
          r"\byields?\b", r"\bwhat will (the )?(price|value|prices|values)\b", r"\bwill .{0,60}\b(be worth|appreciate)\b",
          r"\b(price|value)s? .{0,40}\bin 20[3-9]\d\b",
          r"ضمان", r"مضمون", r"عائد", r"هل استثمر", r"استثمار جيد", r"افضل استثمار", r"ربح", r"هل اشتري"]
CONTACT = [r"\bcontact\b", r"\bcall me\b", r"\bbook (a )?(viewing|visit|tour|appointment)", r"\bsales (team|agent|office)",
           r"\bspeak (to|with) (a |an )?(human|agent|person|someone)", r"\bphone number\b", r"\bwhatsapp\b",
           r"\bget in touch\b", r"\b(talk|speak|chat) (to|with) (the |a |your )?sales\b", r"\bsales (contact|people)\b",
           r"\breach (the )?sales\b", r"\b(talk|speak|chat) (to|with) (a |an |the |your )?(human|agent|person|someone|"
           r"advisor|adviser|representative|real person)\b", r"^(i'?m|i am) interested\b", r"\bregister (my )?interest\b",
           r"\bcall ?back\b", r"^(human|agent|advisor|adviser)( please)?\??$",
           r"\b(advisor|adviser|sales agent|real estate agent)\b", r"\bbook\b.{0,20}\b(viewing|visit|tour|call|meeting)\b",
           r"(التحدث|اتحدث|اكلم|تكلم|كلم)\s+(مع|الي)?\s*(مستشار|موظف|شخص|احد|المبيعات)", r"مستشار", r"موظف مبيعات", r"تواصل", r"اتصل", r"رقم الهاتف", r"حجز (موعد|معاينه|زياره)", r"فريق المبيعات",
           r"التحدث (مع|الي) (فريق )?المبيعات"]
CALC = [r"\b(monthly payments?|mortgage|emi|loan)\b.{0,60}\d|\d.{0,60}\b(monthly payments?|mortgage|emi|loan)\b",
        r"\d\s*%\s*(down|deposit|upfront|مقدم|دفعه)", r"(down ?payment|deposit|دفعه مقدمه|مقدم)",
        r"per (m2|sqm|square met)", r"price per", r"سعر المتر", r"\binstall?ments?\b", r"اقساط|قسط",
        r"\bconvert\b", r"(حول|تحويل)\s.*\s(الي|ب)", r"\bin (usd|aed|sar|dollars|dirhams|riyals)\b"]
OFF_TOPIC = [r"\b(write|give|generate|create|show)\b.{0,25}\b(code|python|javascript|java|script|function|sql|html|program)\b",
             r"^\s*(what('?s| is)\s*)?[\d\s+\-*/().^=x]+\??\s*$", r"\bweather\b", r"\brestaurants?\b", r"\bjoke\b", r"\bpoem\b", r"\brecipe\b",
             r"\bfootball\b|\bsoccer\b|\bcricket\b", r"\bpresident\b", r"\bhomework\b", r"\btranslate\b",
             r"\bwho (won|is the)\b", r"\bbitcoin\b|\bcrypto\b|\bstock(s)?\b", r"\bmovie\b|\bsong\b",
             r"اكتب (لي )?(كود|برنامج|قصيده)", r"نكته", r"قصيده", r"الطقس", r"مطعم", r"كره القدم", r"وصفه طبخ", r"بايثون"]
COMPARE = [r"\bcompare\b", r"\bcomparison\b", r"\bvs\.?\b", r"\bversus\b", r"\bdifference between\b",
           r"قارن", r"مقارنه", r"الفرق بين"]
SEARCH = [r"\b(apartment|apartments|flat|flats|villa|villas|townhouse|penthouse|studio|listing|listings|homes?|properties|property)\b.{0,40}\b(in|under|below|for)\b",
          r"\b\d+\s*[- ]?(bed|beds|bedroom|br)\b", r"\b(for rent|for sale|to rent)\b", r"\bunder\s*\d",
          r"شقق|شقه|فيلا|فلل|للايجار|للبيع|عقارات"]
LOCATION = [r"\bprojects?\b", r"\bproyectos?\b", r"\bdevelopments?\b", r"\bwhat (do you have|is available)\b", r"\bwhere\b",
            r"\bwhat (does|do) [a-z ]{2,20} have\b", r"\bwhat('s| is) (there|available)\b",
            r"مشاريع|مشروع|ماذا لديكم|المتوفره|المتوفر"]
BRAND = [r"\bbranded\b", r"\bbrand partners?\b", r"\bpartners?\b", r"\bpartnership",
         r"علامات تجاريه|العلامات التجاريه|علامه تجاريه|شركاء|الشركاء"]
PROJECT_WORDS = [r"\bprojects?\b", r"\bdevelopments?\b", r"مشاريع|مشروع"]
FMH = [r"\bfind (me )?(a |my )?home\b", r"\bhelp me (find|choose)\b", r"ساعدني (في|علي) (ايجاد|اختيار|العثور)",
       r"ابحث لي عن منزل"]
# Steering by protected traits (nationality, religion, ethnicity, gender, family status): decline politely and offer
# neutral published facts instead (fair-housing style; evals S01-S05).
_TRAITS = (r"(indians?|arabs?|muslims?|non-?muslims?|christians?|jews|jewish|hindus?|westerners?|europeans?|british|"
           r"pakistanis?|russians?|chinese|filipinos?|africans?|americans?|white|black|asians?)")
STEERING = [rf"\b(people like me|lots of|mostly|only|among|majority|full of|no)\b.{{0,40}}\b{_TRAITS}\b",
            rf"\b{_TRAITS}\b.{{0,40}}\b(live|living|reside|community|neighbou?rhoods?|areas?)\b.{{0,40}}\b(only|lots|most|many|where)\b",
            r"\bhow many (westerners|indians|arabs|foreigners|muslims|christians|expats)\b",
            r"\bwhere (non-?)?(muslims|christians|foreigners|westerners)\b",
            r"\b(single (woman|women|man|men)|married couples?|family status|bachelors?)\b.{0,80}\b(better|filter|best|only|rank|versus|vs)\b",
            r"\b(filter|rank|sort|choose)\b.{0,40}\b(religion|ethnicity|nationality|race|family status|gender)\b",
            r"لا يسكنها|لا يسكنه|فقط للعرب|للعرب فقط|للمسلمين فقط|بدون اجانب|غير المسلمين|حسب الجنسيه|حسب الدين"]
GREETING = [r"^(hi|hello|hey|salam|good (morning|evening|afternoon)|greetings)\b[!. ]*$",
            r"^(مرحبا|اهلا|السلام عليكم|صباح الخير|مساء الخير)[!. ]*$"]
FOLLOW_UP = [r"^(and |what about |how about )?(the )?(price|prices|cost|handover|status|location|size|area|amenities|units?|"
             r"payment plan|completion|when)\b", r"\b(it|its|it's|this one|that one|this project|that project)\b",
             r"^(وماذا عن|ماذا عن|كم|متى|و?السعر|و?الاسعار|التسليم)", r"(هذا المشروع|ذلك المشروع)"]


PLACE_BROWSE = [r"(?<![a-z])any(thing)?(?![a-z])", r"(?<![a-z])what can i (buy|rent)(?![a-z])", r"(?<![a-z])rentals?(?![a-z])", r"(?<![a-z])for (sale|rent)(?![a-z])",
                r"(?<![a-z])what (do you have|is there)(?![a-z])", r"عندكم|لديكم|للايجار|للبيع"]


def question_is_info(norm: str) -> bool:
    """Questions about rules/processes in a place ("how do auctions work in Riyadh") are not browsing."""
    return bool(re.search(r"(?<![a-z])(how|why|rules?|laws?|process|tax|fees?|mortgage|interest)(?![a-z])|كيف|لماذا|قوانين|رسوم", norm))


def _any(patterns, norm: str) -> bool:
    return any(re.search(p, norm) for p in patterns)


def _fmh_step(history: list[dict] | None) -> int:
    """Stateless find-my-home: the step is read from the last assistant turn (one of the three fixed questions)."""
    from . import templates
    last = next((h.get("content") or "" for h in reversed(history or []) if h.get("role") == "assistant"), "")
    for step, key in ((2, "fmh_q1"), (3, "fmh_q2"), (4, "fmh_q3")):
        if any(templates.t(key, lg) in last for lg in ("en", "ar")):
            return step
    return 0


def _last_user(history: list[dict] | None) -> str | None:
    return next((h.get("content") for h in reversed(history or []) if h.get("role") == "user" and h.get("content")),
                None)


_ORDINALS = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "fourth": 3, "4th": 3, "last": -1,
             "frist": 0, "firts": 0, "fisrt": 0, "secnd": 1, "scond": 1, "thrid": 2, "الاول": 0, "الثاني": 1, "الثالث": 2, "الرابع": 3, "الاخير": -1}
_ORDINAL = re.compile(r"(?<![\w])(first|frist|firts|fisrt|1st|second|secnd|scond|2nd|third|thrid|3rd|fourth|4th|last|الاول|الثاني|الثالث|الرابع|الاخير)"
                      r"(?![\w])(?:\s+(?:one|project|ones?|المشروع|مشروع))?")
_CHEAPER = re.compile(r"(?<![a-z])(cheaper|cheapest|less expensive|lower price|more affordable)(?![a-z])|ارخص|اقل سعر")
_AREA = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(m2|m²|sqm|sq\.? ?m|square met(?:er|re)s?|م2|متر(?: مربع)?)", re.I)
_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_CONTINUE = re.compile(r"^(and|what about|how about|also|then|و|وماذا عن|ماذا عن|طيب)(?![\w])|^و(?=\S)")


def _calc_follow_up(message: str, history: list[dict] | None, store: Store) -> str | None:
    """"And if it was 150 m2?" after a calculation: the previous request with the changed figure substituted."""
    prev = _last_user(history)
    if not prev or not (_AREA.search(message) or _PCT.search(message)):
        return None
    if plan(prev, store).intent != "calculation":
        return None
    out = prev
    m_new, m_old = _AREA.search(message), _AREA.search(prev)
    if m_new and m_old:
        out = out[:m_old.start(1)] + m_new.group(1) + out[m_old.end(1):]
    p_new, p_old = _PCT.search(message), _PCT.search(out)
    if p_new and p_old:
        out = out[:p_old.start(1)] + p_new.group(1) + out[p_old.end(1):]
    return out if out != prev else None


# ---------------- currency follow-ups: "how much is that in dollars", "in USD?", "بالدولار" ----------------
_FX_TARGET_EN = re.compile(r"(?<![a-z])(?:in|into|to)\s+(usd|dollars?|eur|euros?|gbp|pounds?|sterling|inr|rupees?|aed|"
                           r"dirhams?|sar|riyals?|qar|omr|bhd)(?![a-z])|(?<![a-z])in\s+([$\u20ac\u00a3\u20b9])")
_FX_TARGET_AR = re.compile(r"(?<![\w])\u0648?(?:\u0628|\u0644)?(?:\u0627\u0644)?(\u062f\u0648\u0644\u0627\u0631|\u064a\u0648\u0631\u0648|"
                           r"\u0627\u0633\u062a\u0631\u0644\u064a\u0646\u064a|\u0631\u0648\u0628\u064a\u0647|\u062f\u0631\u0647\u0645|\u0631\u064a\u0627\u0644)(?![\w])")
_FX_ASK = re.compile(r"how much|what|that|\bit\b|this|price|cost|convert|equal|worth|\u0643\u0645|\u0630\u0644\u0643|\u0647\u0630\u0627|"
                     r"\u0627\u0644\u0633\u0639\u0631|\u062d\u0648\u0644|\u062a\u062d\u0648\u064a\u0644|\u064a\u0633\u0627\u0648\u064a|\u0645\u0627")
_MONEY_IN_TEXT = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*(k|m|mn|million|\u0645\u0644\u064a\u0648\u0646|\u0627\u0644\u0641)?\s*"
    r"(sar|aed|usd|qar|omr|bhd|eur|gbp|inr|\u0631\.\u0633|\u062f\.\u0627|\u0631\u064a\u0627\u0644|\u062f\u0631\u0647\u0645|\u062f\u0648\u0644\u0627\u0631)(?![a-z])"
    r"|(sar|aed|usd|qar|omr|bhd|eur|gbp|inr|[$\u20ac\u00a3\u20b9])\s*(\d[\d,]*(?:\.\d+)?)\s*(k|m|mn|million|\u0645\u0644\u064a\u0648\u0646|\u0627\u0644\u0641)?(?![a-z])")
_CUR_WORD_CODE = {"\u0631.\u0633": "SAR", "\u062f.\u0627": "AED", "\u0631\u064a\u0627\u0644": "SAR", "\u062f\u0631\u0647\u0645": "AED",
                  "\u062f\u0648\u0644\u0627\u0631": "USD", "$": "USD", "\u20ac": "EUR", "\u00a3": "GBP", "\u20b9": "INR"}


def fx_target(norm: str) -> str | None:
    """The currency a follow-up asks to see the amount in, or None."""
    m = _FX_TARGET_EN.search(norm)
    if m:
        return CURRENCIES.get(m.group(1) or m.group(2))
    m = _FX_TARGET_AR.search(norm)
    return CURRENCIES.get(m.group(1)) if m else None


def last_price_in(history: list[dict] | None, store: Store) -> tuple[float, str] | None:
    """The last price mentioned in the conversation (newest turn first, last figure within a turn), else the
    published "price from" of the last project named. (amount, currency) or None."""
    for turn in reversed(history or []):
        norm = normalize_text(turn.get("content") or "")
        last = None
        for m in _MONEY_IN_TEXT.finditer(norm):
            if m.group(1):
                num, suf, cur = m.group(1), m.group(2), m.group(3)
            else:
                cur, num, suf = m.group(4), m.group(5), m.group(6)
            v = parse_amount(num, suf)
            cur = _CUR_WORD_CODE.get(cur) or cur.upper()
            if v:
                last = (v, cur)
        if last:
            return last
    for turn in reversed(history or []):
        ids = extract_projects(normalize_text(turn.get("content") or ""), store)
        for pid in ids:
            p = store.project_by_id(pid)
            if p and p.get("price_from_amount") and p.get("price_from_currency"):
                return float(p["price_from_amount"]), str(p["price_from_currency"]).upper()
    return None


FX_NO_PRICE = "__fx_no_price__"


def fx_follow_up(message: str, history: list[dict] | None, store: Store, last_entities: list[str] | None = None) -> str | None:
    """"How much is that in dollars?" / "in USD?" / "\u0628\u0627\u0644\u062f\u0648\u0644\u0627\u0631": a conversion request without an
    amount. Returns the full request ("convert 1180000 SAR to USD") built from the last price in the conversation."""
    norm = normalize_text(message)
    if re.search(r"\d", norm) or len(norm.split()) > 10:
        return None
    target = fx_target(norm)
    if not target or not (_FX_ASK.search(norm) or len(norm.split()) <= 4):
        return None
    price = last_price_in(history, store) if history else None
    if not price:  # "show these prices in INR" after cards with no price in the prose: the first carried price
        for i in validate_entity_ids(last_entities or [], store):
            r = store.project_by_id(i) or store.listing_by_id(i)
            amt = r and (r.get("price_from_amount") or r.get("price_amount"))
            cur = r and (r.get("price_from_currency") or r.get("price_currency"))
            if amt and cur:
                price = (float(amt), str(cur).upper())
                break
    if not price:
        # "Show these prices in INR" with nothing priced on screen: ask for a price instead of a dead end.
        if _FX_ASK.search(norm) or re.search(r"\b(prices?|cost|amount)\b|اسعار|سعر", norm):
            return f"{FX_NO_PRICE} {target}"
        return None
    amount, src = price
    return f"convert {amount:.0f} {src} to {target}"


def _ambiguous_names(message: str, store: Store) -> list[list[str]]:
    """For "aida vs trump tower": each side's candidate project ids when the name matches several projects."""
    norm = normalize_text(message)
    parts = re.split(r"\s+(?:vs\.?|versus|or|and|و|مقابل|مع)\s+|\s+و(?=[؀-ۿ])|\bcompare\b|قارن بين|قارن|بين", norm)
    out = []
    for part in (p.strip(" ?.,") for p in parts):
        if len(part) < 3:
            continue
        ids = [p["id"] for p in store.projects
               if any(part in a or (len(a) >= 4 and a in part) for a in project_aliases(p))]
        if ids:
            out.append(ids)
    return out if len(out) >= 2 else []


# ---------------- property-adjacent topics (visa, finance, tax, ownership rules, living costs) ----------------
# Outside the dataset but not off-topic: the concierge says so honestly, names the official bodies and offers the human
# route. Patterns run on normalize_text() output (Arabic letters folded: ة->ه, أ/إ->ا, ى->ي) and tolerate typos.
_NATIONALITIES = (r"(indian|pakistani|bangladeshi|sri lankan|nepali|filipino|british|american|canadian|australian|egyptian|"
                  r"nigerian|chinese|russian|turkish|iranian|lebanese|jordanian|syrian|sudanese|kenyan|european|german|"
                  r"french|italian|spanish|irish|south african|ukrainian)")
# Buying from abroad / as a given nationality: an eligibility question the data cannot answer (never "everyone can buy").
_ELIGIBILITY = [r"\b(buy|purchase|own|invest)\w*\b.{0,15}\bfrom\s+(abroad|overseas|outside|remotely|afar|(?!dar\b|darglobal|wasalt|you\b|your\b|the\b|a\b|an\b|this\b|that\b|them\b|it\b|my\b|our\b|here\b|there\b|home\b|now\b|scratch\b|plan\b|off\b)[a-z]{3,})",
                r"\bnris?\b", r"\bnon[- ]?resident (indian|national|citizen)s?\b",
                r"\b(overseas|international|foreign|remote|offshore)\s+(buyers?|investors?|purchas\w+|nationals?|clients?)\b",
                r"\b(buy|purchase|own|invest)\w*\b.{0,40}\b(without (visiting|travel\w*|being (there|present))|remotely|while (living|abroad|overseas))\b",
                r"\b(i am|i'm|im|as|being)\s+(an?\s+)?" + _NATIONALITIES + r"\b.{0,60}\b(buy|purchase|own|invest)\w*\b",
                r"\b(buy|purchase|own|invest)\w*\b.{0,60}\b(as|being|if i am|if i'm)\s+(an?\s+)?" + _NATIONALITIES + r"\b",
                r"\b" + _NATIONALITIES + r"\s+(nationals?|citizens?|passports?|buyers?|investors?|residents?)\b.{0,40}\b(buy|purchase|own|invest|allowed|eligible)\w*\b",
                r"\b(eligib\w+|allowed|permitted)\b.{0,30}\b(buy|purchase|own|invest)\w*\b",
                r"\b(buy|purchase|own|invest)\w*\b.{0,30}\b(eligib\w+|allowed|permitted)\b"]
_ELIG_RX = re.compile("|".join(_ELIGIBILITY))


_CUR_OR_METHOD = (r"(inr|rupees?|usd|dollars?|eur|euros?|gbp|pounds?|aed|dirhams?|sar|riyals?|cash|crypto\w*|bitcoin|btc|usdt|"
                  r"cards?|credit cards?|debit cards?|cheques?|checks?|bank transfers?|wire|upi|western union|paypal|"
                  r"foreign currenc\w+|other currenc\w+|my currency|local currency|multiple currenc\w+)")
ADJACENT_TOPICS: dict[str, list[str]] = {
    # payment methods / accepted currencies: not in the data; the sales team confirms. Narrow on purpose: "down payment",
    # "monthly payment" and "payment plan" stay with the calculator and the project facts.
    "payment": [r"\b(pay|paying|payment|payments|paid|settle)\b.{0,30}\b(in|with|using|by|via|through)\b\s*(an?\s+)?" + _CUR_OR_METHOD + r"\b",
                r"\baccept\w*\b.{0,30}\b(" + _CUR_OR_METHOD + r"|payments?|currenc\w+)\b",
                r"\b(payment|accepted) (methods?|options?|currenc\w+|modes?)\b", r"\bwhich currenc\w+.{0,25}\b(pay|accept)\w*\b",
                r"\b(can|could|may) (i|we) pay\b", r"\bhow (do|can|should) (i|we) pay\b", r"\bcrypto(currency)?\b",
                r"\bbitcoin\b",
                r"(?<![\w])(?:ب|ل)?الدفع(?![\w])", r"طرق الدفع", r"وسايل الدفع", r"وسائل الدفع", r"تقبلون", r"كريبتو"],
    "visa": [r"\bvi[sz]a+s?\b", r"\bvisas\b", r"\bresiden(cy|ce|t|ts)\b", r"\bresidence (permit|card|visa)\b",
             r"\bi[qck]+a+m+a+h?\b", r"\bgolden (visa|residen\w*)\b", r"\bpremium residen\w*\b", r"\bgreen card\b",
             r"\bwork permit\b", r"\bcitizenship\b", r"\bimmigration\b", r"\bpassport\b",
             r"تاشير", r"اقامه", r"الاقامه", r"فيزا", r"جنسيه", r"الهجره", r"بطاقه خضراء"],
    "finance": [r"\bmor?t?gag\w*\b", r"\bmortage\w*\b", r"\bloans?\b", r"\bfinanc\w+\b", r"\bfinnanc\w+\b",
                r"\binterest rates?\b", r"\blend(er|ing)\b", r"\bbank (loan|finance)\b",
                r"تمويل", r"رهن", r"قرض", r"قروض", r"سعر الفايده", r"نسبه الفايده"],
    "tax": [r"\btax(es|ation)?\b", r"\bvat\b", r"\bfees?\b", r"\bstamp duty\b", r"\bzakat\b", r"\bcapital gains?\b",
            r"\btransfer (fee|cost)s?\b", r"\bregistration (fee|cost)s?\b",
            r"ضريب", r"رسوم", r"زكاه"],
    "ownership": [*_ELIGIBILITY, r"\blegal(ly)?\b", r"\blaws?\b", r"\bregulations?\b", r"\bfreehold\b", r"\bleasehold\b",
                  r"\bforeign(er|ers)?\b.{0,40}\b(own|ownership|buy|purchase)\w*\b",
                  r"\b(own|ownership|buy|purchase)\w*\b.{0,40}\bforeign(er|ers)?\b", r"\bnon[- ]?residents?\b",
                  r"\bcan (a )?(foreigners?|expats?|non[- ]?residents?) (buy|own)\b", r"\bproperty ownership\b",
                  r"تملك الاجانب", r"تملك", r"للاجانب", r"للأجانب", r"قانون", r"قانوني", r"تشريع"],
    "living": [r"\bschools?\b", r"\bcost of living\b", r"\bliving costs?\b", r"\bhealth ?care\b", r"\bhospitals?\b",
               r"\bexpat(s|riate)?\b", r"\bquality of life\b", r"\bsafe(ty)? (to live|for families)\b",
               r"\b(weather|climate)\b.{0,40}\b(live|living|move|relocat\w*)\b",
               r"مدارس", r"مدرسه", r"تكلفه المعيشه", r"غلاء المعيشه", r"رعايه صحيه", r"مستشفي", r"مستشفيات"],
    # "I am planning to relocate to ..." is a statement of intent, not yet a question: see adjacent_topic()
    "relocate": [r"\brelocat\w*\b", r"\breloc\b", r"\b(moving|move|migrat\w*|emigrat\w*) (to|abroad)\b", r"\bmoving\b",
                 r"الانتقال", r"انتقل", r"اهاجر"],
}
_RELOCATE_QUESTION = re.compile(r"\?|؟|^(how|what|which|where|when|can|could|do|does|should|is|are|will)\b|"
                                r"^(هل|كيف|ما|اين|متي|اي)\b|\b(need|help|process|steps|logistics|require\w*|procedure)\b|"
                                r"يلزم|اساعد|خطوات|اجراءات")
_NEAR_SCHOOL = re.compile(r"\b(near|close to|next to|nearby|around|walking distance)\s+(the\s+|a\s+|good\s+)?schools?\b")
_WEATHER_ONLY = re.compile(r"\b(weather|climate)\b|الطقس|المناخ")


def adjacent_topic(norm: str) -> str | None:
    """The property-adjacent topic a message asks about (first match in priority order), or None."""
    t = _NEAR_SCHOOL.sub(" ", norm)
    for topic, pats in ADJACENT_TOPICS.items():
        if any(re.search(p, t) for p in pats):
            if topic == "relocate":
                # a plain statement ("ok, i am planning to relocate to") gets a warmer opening than a question
                # about relocating ("how do I relocate my family"); both are answered as adjacent topics
                return "living" if _RELOCATE_QUESTION.search(t.strip()) else "relocate"
            return topic
    return None


def _property_request(norm: str, ent: "Entities") -> bool:
    """True when the message also asks for properties (a project, a listing filter, a place to browse)."""
    if ent.project_ids or ent.listing_signal() or ent.property_type:
        return True
    # "relocating to Riyadh, budget around 2 million SAR, what can we get?": a stated budget with a place is a search
    return bool((ent.city or ent.country) and (_any(SEARCH, norm) or _any(LOCATION, norm) or _any(PLACE_BROWSE, norm)
                                              or re.search(r"(?<![a-z])budget(?![a-z])|ميزاني|what can (i|we) get", norm)))


BANTER = [r"\b(are|r) (you|u|ya) (so |really |just |a bit )?(dumb|stupid|useless|slow|silly|an? idiot|bad|broken|"
          r"a bot|a robot|an? ai|human|real|a person|a machine)\b",
          r"\b(you|u|ya|ur)(?:'?re| are| r)? (so |really |such an? )?(dumb|stupid|useless|an idiot|idiot|rubbish|"
          r"terrible|worthless|silly|trash)\b",
          r"\b(you|u|ya) (do ?n'?t|dont|cant|can'?t|do not|cannot) (even )?(know|understand|get|count|do|add|calculate|"
          r"answer)\b",
          r"\bcan (you|u) (even )?(do|count|add|calculate|solve)\b.{0,12}\b(math|maths|sums?|arithmetic|counting)\b",
          r"\b(basic|simple|easy) (math|maths|sums?|arithmetic)\b",
          r"\bwhy (can'?t|cant|won'?t|wont|do ?n'?t|dont|are ?n'?t) (you|u)\b.{0,15}\b(answer|reply|help|know|respond)\b",
          r"\b(worst|bad|stupid|useless|dumb) (bot|chatbot|assistant|ai)\b", r"\byou suck\b",
          r"^(are|r) (you|u) (a )?(human|real|bot|robot|ai)\??$", r"\bdo you (even )?(know|get) (math|maths)\b",
          r"انت غبي|انت غبيه|يا غبي|غبي|انت فاشل|فاشل|عديم الفايده|انت بوت|هل انت (بوت|روبوت|انسان|بشر|ذكاء)|"
          r"انت (انسان|بشر|روبوت)|ما تعرف (تحسب|حساب)|لا تعرف (تحسب|الحساب)|لا تعرف|ما تعرف|ما تفهم|لا تفهم|"
          r"هل تجيد الحساب|تعرف (تحسب|حساب|رياضيات)|لماذا لا تجيب|ليش ما تجاوب|لماذا لا تجاوب"]


# ---------------- superlatives ("most expensive one??", "الأرخص"): sort the carried set by one field ----------------
_SUPER_RX = {
    "price_desc": re.compile(r"(?<![a-z])(most\s+exp\w*|exp[ae]n\w*sive|priciest|pricest|most\s+pric\w*|most\s+costly|"
                             r"highest[- ]?pric\w*|top[- ]?pric\w*)(?![a-z])|(?<![\w])(?:ال)?اغلي(?![\w])"),
    "price_asc": re.compile(r"(?<![a-z])(cheapest|cheapst|cheapes|lowest[- ]?pric\w*|least\s+exp\w*)(?![a-z])|"
                            r"(?<![\w])(?:ال)?ارخص(?![\w])|(?<![\w])اقل\s+سعر"),
    "area_desc": re.compile(r"(?<![a-z])(biggest|largest|most\s+spacious|bigest|largets)(?![a-z])|"
                            r"(?<![\w])(?:ال)?(اكبر|اوسع)(?![\w])"),
    "area_asc": re.compile(r"(?<![a-z])(smallest|tiniest|smallet)(?![a-z])|(?<![\w])(?:ال)?اصغر(?![\w])"),
    "newest": re.compile(r"(?<![a-z])(newest|latest|most\s+recent)(?![a-z])|(?<![\w])(?:ال)?احدث(?![\w])"),
}


def superlative(norm: str) -> str | None:
    for k, rx in _SUPER_RX.items():
        if rx.search(norm):
            return k
    return None


_CTX_FIELDS = ("property_type", "city", "country", "listing_type", "site", "beds", "brand")
# Intents whose entities describe a property request; small talk, calculations and guard intents never feed memory.
_MEMORY_INTENTS = ("search", "location_overview", "brand_partner", "project_info", "compare", "superlative", "vague",
                   "general", "find_my_home")
_LISTING_ONLY = ("property_type", "beds", "budget_max", "currency", "listing_type")


def carried_context(history: list[dict] | None, store: Store, last_entities: list[str] | None = None,
                    reset: bool = False) -> Memory:
    """Stateless Memory (docs/CONTRACT_QUALITY.md §1), rebuilt from the client's history on every request.

    Each earlier user turn is re-planned in code (no history, no model) and merged oldest to newest: an explicit
    new value wins, a new country clears the city, a reset phrase ("forget that", "something else") clears
    everything, and a projects-level turn ("projects in Dubai") drops the listing-only filters. `last_entities` are
    ids only, validated against the store; without them the ids come from the project names in the last assistant
    turn (server-side text, in order of mention). `reset=True` (from the understanding call) clears everything.
    """
    mem = Memory()
    if reset:
        mem.clear()
        return mem
    turns = list(history or [])
    for turn in [h for h in turns if h.get("role") == "user"][-6:]:
        m = turn.get("content") or ""
        norm = normalize_text(m)
        if not norm:
            continue
        if is_reset(norm):
            mem.clear()
            mem.reset = False  # cleared in the past; `reset` reports this request only
        pe = plan(m, store, None, {"_skip_adjacent": True})
        mem.last_intent = pe.intent
        if pe.intent not in _MEMORY_INTENTS:
            continue
        e = pe.entities
        got = {k: getattr(e, k, None) for k in _CTX_FIELDS + ("budget_max", "currency")}
        got = {k: v for k, v in got.items() if v is not None}
        if not got:
            continue
        explicit = _any(PROJECT_WORDS, norm) or got.get("site") == "DarGlobal" or pe.intent == "brand_partner"
        cont = bool(_CONTINUE.search(norm)) and not explicit
        if pe.intent == "superlative":
            proj = pe.text == "projects"
        elif cont:
            proj = mem.projects_level  # "and in Oman?": the same request in a new place, the level is kept
        else:
            proj = (pe.intent in ("location_overview", "brand_partner") and "property_type" not in got
                    or got.get("site") == "DarGlobal")
        if proj and not cont and not any(k in got for k in _LISTING_ONLY):
            for k in _LISTING_ONLY:
                setattr(mem, k, None)
        mem.merge(got)
        mem.projects_level = proj
    ids = validate_entity_ids(last_entities or [], store)
    if not ids:
        last_a = next((h.get("content") or "" for h in reversed(turns) if h.get("role") == "assistant"), "")
        ids = extract_projects(normalize_text(last_a), store)[:6] if last_a else []
    mem.last_entities = ids
    return mem


def _fill_from(ent: Entities, src, keys) -> None:
    """Fill the empty fields of `ent` from `src` (an Entities or a Memory). A new country in the current message
    never inherits the remembered city (or place)."""
    country_changed = bool(ent.country) and normalize_text(ent.country or "") != normalize_text(
        getattr(src, "country", None) or "")
    for k in keys:
        if k in ("city", "place") and country_changed:
            continue
        if getattr(ent, k, None) in (None, False) and getattr(src, k, None) is not None:
            setattr(ent, k, getattr(src, k))


def plan(message: str, store: Store, history: list[dict] | None = None, flags: dict | None = None,
         last_entities: list[str] | None = None) -> Plan:
    """`last_entities`: ids of the cards shown on the previous turn (client-sent, validated in carried_context)."""
    pl = _plan(message, store, history, flags, last_entities)
    return pl


def _plan(message: str, store: Store, history: list[dict] | None, flags: dict | None,
          last_entities: list[str] | None) -> Plan:
    flags = flags or {}
    norm = normalize_text(message)
    ent = extract_entities(message, store)
    _mem: list[Memory] = []

    def memory() -> Memory:
        """Built once, only on the branches that use it (history present); a reset phrase now clears it."""
        if not _mem:
            _mem.append(carried_context(history, store, last_entities, reset=is_reset(norm)))
        return _mem[0]

    def done(p_: Plan) -> Plan:
        if _mem:
            p_.memory = _mem[0]
        return p_

    if is_injection(message):
        return Plan("injection", ent)
    if flags.get("FF_FIND_MY_HOME") and history:
        step = _fmh_step(history)
        if step:
            return Plan("find_my_home", ent, step=step)
    cmp_ = compound_smalltalk(message)  # "4+7, what is ur name": the sum and the small talk, both answered
    if cmp_ and not ent.project_ids:
        return Plan(cmp_[1], ent, text="compound")
    if _any(BANTER, norm) and not ent.project_ids and not _property_request(norm, ent):
        return Plan("banter", ent)
    conv = conversational_intent(message)  # "hye", "salam", "thanks!", "who r u", "ok" (whole message only)
    if conv:
        return Plan(conv, ent)
    if simple_arithmetic(message):  # "34 plus sevn is ?": a harmless sum, answered in code, then the presenter pivot
        return Plan("off_topic", ent)
    if _any(STEERING, norm):
        return Plan("steering", ent)
    if _any(GREETING, norm):
        return Plan("greeting", ent)
    if _any(ADVICE, norm):
        return Plan("advice", ent)
    # "act as my property advisor and shortlist ..." is a search request, not a request to be put in touch
    if _any(CONTACT, norm) and not re.search(r"\bact as\b|\bshortlist\b|\brole ?play\b", norm):
        return Plan("contact_sales", ent)
    # "2 bed in AED under 2m" is a listing search with a currency, not a conversion
    listing_like = ent.beds is not None and not re.search(
        r"%|convert|حول|تحويل|down|deposit|instal|per m|mortgage|loan|monthly payment|مقدم|قسط|اقساط", norm)
    has_money = not listing_like and bool(re.search(r"\d", norm)) and (ent.currency is not None or re.search(r"\d\s*%|\d\s*(m|k|million|مليون)\b", norm))
    if _any(CALC, norm) and has_money:
        return Plan("calculation", ent)
    adj = None if flags.get("_skip_adjacent") else adjacent_topic(norm)
    if adj == "finance" and unpublished_topic(message) == "mortgage_rate" and (ent.project_ids or ent.site):
        adj = None  # "mortgage rate for <project / Wasalt>": the existing not-published answer stays
    if adj and not (_any(CALC, norm) and re.search(r"\d", norm) and not _property_request(norm, ent)) and not re.search(
            r"^(what('?s| is| would be)? ?(the |my )?)?(monthly payments?|mortgage (payment|calculator)|emi|"
            r"loan (payment|calculator)|instal?ments?|القسط الشهري|حاسبه التمويل)\??$", norm):
        pure = (adj == "payment" or (adj == "ownership" and _ELIG_RX.search(norm))) and not (
            ent.project_ids or ent.city or ent.country or ent.property_type or ent.listing_signal())
        if not pure and _property_request(norm, ent):  # mixed: the property part is answered normally, the note is added
            sub = plan(message, store, history, {**flags, "_skip_adjacent": True})
            if sub.intent not in ("general", "vague", "off_topic"):
                sub.adjacent, sub.adjacent_topic = True, adj
                return sub
        return Plan("adjacent", ent, adjacent=True, adjacent_topic=adj)
    if _any(OFF_TOPIC, norm) and not ent.project_ids:
        return Plan("off_topic", ent)
    if _any(CALC, norm) and re.search(r"\d", norm) and not listing_like:
        return Plan("calculation", ent)
    if re.search(r"^(what('?s| is| would be)? ?(the |my )?)?(monthly payments?|mortgage (payment|calculator)|emi|"
                 r"loan (payment|calculator)|instal?ments?|القسط الشهري|حاسبه التمويل)\??$", norm):
        return Plan("calculation", ent)  # no figures yet: the calculator asks for them

    fx = fx_follow_up(message, history, store, last_entities)
    if fx:
        return Plan("calculation", extract_entities(fx, store), follow_up=True, text=fx)
    if history:
        merged = _calc_follow_up(message, history, store)
        if merged:
            return Plan("calculation", extract_entities(merged, store), follow_up=True, text=merged)

    unknown, is_place = unknown_entity_kind(message, norm, ent, store)
    if unknown:
        return Plan("general", ent, unknown=unknown, unknown_place=is_place)

    sup = superlative(norm)
    if sup and not ent.project_ids and len(norm.split()) <= 9:
        mem = memory() if history else Memory()
        ctx = {k: getattr(mem, k) for k in _CTX_FIELDS if getattr(mem, k, None) is not None}
        if ent.country and normalize_text(ent.country) != normalize_text(mem.country or ""):
            ctx.pop("city", None)  # a new country clears the remembered city
        proj_ctx = mem.projects_level
        own = ent.property_type or ent.city or ent.country or ent.listing_type or ent.site
        if sup != "price_asc" or ctx or own and history:
            for k, v in ctx.items():
                if getattr(ent, k, None) is None:
                    setattr(ent, k, v)
            ent.sort = sup
            pl = Plan("superlative", ent, follow_up=bool(ctx), topic=sup)
            pl.text = "projects" if (ent.site == "DarGlobal" or (proj_ctx and not ent.property_type)
                                     or _any(PROJECT_WORDS, norm)) else "listings"
            return done(pl)

    if history and not ent.project_ids:
        prev = _last_user(history)
        prev_plan = plan(prev, store) if prev else None
        if prev and _CONTINUE.search(normalize_text(prev)):
            # The previous user turn was itself a continuation ("what about Jeddah"): its standalone plan is a bare
            # place question, so plan it against the history before it ("and Madinah?" then keeps type and beds).
            idx = max((i for i, t_ in enumerate(history) if t_.get("role") == "user"), default=0)
            if idx > 0:
                prev_plan = plan(prev, store, history[:idx])
        # "What is its price?" after asking about a name that is not in the data: still not in the data.
        if prev_plan and prev_plan.unknown and _any(FOLLOW_UP, norm):
            return Plan("general", ent, follow_up=True, unknown=prev_plan.unknown,
                        unknown_place=prev_plan.unknown_place)
        # "And in Dubai?" / "Only DarGlobal ones please": same question, new place or site filter.
        short = len(norm.split()) <= 6
        # "the second one", "tell me about the first": the n-th project named in the last assistant turn
        m_ord = _ORDINAL.search(norm)
        if short and m_ord and not _any(COMPARE, norm):  # "compare the first and the third" is below
            # Memory.last_entities: the client's card ids (validated) or, without them, the project names in the
            # last assistant turn in order of mention.
            ids = memory().last_entities
            k = _ORDINALS[m_ord.group(1)]
            if ids and (k == -1 or k < len(ids)):
                rid = ids[k]
                if store.project_by_id(rid):
                    ent.project_ids = [rid]
                    return done(Plan("project_info", ent, follow_up=True, refs=[rid]))
                # A listing card: the id is resolved; answering it is the answer layer's job.
                return done(Plan("general", ent, follow_up=True, refs=[rid]))
        if prev_plan and short and prev_plan.intent == "search" and not is_reset(norm) and (
                ent.sort or _CHEAPER.search(norm) or ent.beds is not None or ent.budget_max is not None):
            # "cheaper ones?", "only 3 beds", "under 1M": the previous search with one filter changed; anything
            # the previous message did not say comes from the conversation memory.
            keys = ("city", "country", "place", "listing_type", "beds", "budget_min", "budget_max", "currency",
                    "property_type", "baths", "area_m2")
            _fill_from(ent, prev_plan.entities, keys)
            _fill_from(ent, memory(), keys)
            if _CHEAPER.search(norm):
                ent.sort = "price_asc"
            return done(Plan("search", ent, follow_up=True))
        if prev_plan and short and prev_plan.intent in ("location_overview", "search", "brand_partner"):
            pe = prev_plan.entities
            if (ent.city or ent.country) and _CONTINUE.search(norm) and not is_reset(norm):
                # "what about Jeddah": same request in a new place; type, budget, beds and buy/rent are kept.
                keys = ("listing_type", "beds", "budget_min", "budget_max", "currency", "property_type", "site",
                        "brand")
                _fill_from(ent, pe, keys)
                _fill_from(ent, memory(), keys)
                return done(Plan(prev_plan.intent, ent, follow_up=True))
            if ent.site and not (ent.city or ent.country):
                ent.city, ent.country, ent.place = pe.city, pe.country, pe.place
                ent.listing_type = ent.listing_type or pe.listing_type
                intent = "location_overview" if ent.site == "DarGlobal" else prev_plan.intent
                return Plan(intent, ent, follow_up=True)

    follow_up = False
    if not ent.project_ids and history and _any(COMPARE, norm) and has_reference(norm):
        # "compare them", "compare the first and the third": projects shown on the previous turn
        projs = [i for i in memory().last_entities if store.project_by_id(i)]
        picks = [projs[k] for k in (_ORDINALS[m.group(1)] for m in _ORDINAL.finditer(norm))
                 if projs and (k == -1 or k < len(projs))]
        picks = list(dict.fromkeys(picks)) if len(set(picks)) >= 2 else projs[:2]
        if len(picks) >= 2:
            ent.project_ids = picks[:2]
            return done(Plan("compare", ent, follow_up=True, refs=picks[:2]))
    if not ent.project_ids and history and _any(FOLLOW_UP, norm):
        for turn in reversed(history[-8:]):
            ids = extract_projects(normalize_text(turn.get("content") or ""), store)
            if ids:
                ent.project_ids = ids[:2]
                follow_up = True
                break

    versus_ar = bool(re.search(r"(?<![\w])مقابل(?![\w])", norm)) and len(ent.project_ids) >= 2  # "X مقابل Y"
    if (_any(COMPARE, norm) or versus_ar) and (ent.project_ids or _any(PROJECT_WORDS, norm) or _ambiguous_names(message, store)):
        return Plan("compare", ent, follow_up=follow_up)
    if flags.get("FF_FIND_MY_HOME") and _any(FMH, norm):
        return Plan("find_my_home", ent)
    if ent.project_ids:
        places = {normalize_text(v) for v in (ent.city, ent.country) if v}
        named_like_place = all(normalize_text(store.project_by_id(pid).get("name_en") or "") in places
                               for pid in ent.project_ids if store.project_by_id(pid))
        # "Projects in Aida" names the place Aida, not only the project of the same name.
        if not (places and named_like_place and _any(LOCATION, norm)):
            return Plan("project_info", ent, follow_up=follow_up)
    question = bool(re.match(r"^(can|could|how|why|what is|what are|what's|is|are|do|does|should|who|explain|"
                             r"هل|كيف|لماذا|ما هو|ما هي|ماهو|ماهي)\b", norm))
    has_place = bool(ent.city or ent.country)
    wants_listing = (ent.beds is not None or ent.budget_max is not None
                     or (ent.property_type is not None and (has_place or ent.listing_type is not None))
                     or (ent.listing_type is not None and has_place and not question))
    project_level = (_any(PROJECT_WORDS, norm) or ent.site == "DarGlobal" or ent.handover_year is not None
                     or bool(re.search(r"(?<![a-z])how many (projects|developments)(?![a-z])|كم مشروع", norm))
                     # "what countries do you cover?", "which countries have the most?": the per-country overview
                     or bool(re.search(r"(?<![a-z])(what|which|how many) countr(y|ies)(?![a-z])|"
                                       r"(?<![a-z])countries (do )?(you|u) (cover|have|operate|are in)(?![a-z])|"
                                       r"في اي (دوله|دول)|ما الدول|اي الدول|كم دوله", norm)))
    if project_level and not (ent.beds is not None or ent.baths is not None):
        # "handover 2027 projects", "cheapest darglobal project", "how many projects does darglobal have"
        return Plan("location_overview", ent)
    if _any(SEARCH, norm) and wants_listing:
        return Plan("search", ent)
    # Messy listing requests ("buy 1 bhk", "cheap apartment jedda", "flat 1500 sqft riyadh"): a bedroom count, a
    # budget, a size or a cheapest-first word, or a property type with a place / buy-rent word, is a listing search.
    # Informational questions ("how does renting work in Jeddah") are not.
    if not question_is_info(norm) and not _any(BRAND, norm) and not ent.brand and (
            ent.listing_signal() or (ent.property_type and (has_place or ent.place or ent.listing_type))):
        return Plan("search", ent)
    if _any(BRAND, norm) or ent.brand:
        return Plan("brand_partner", ent)
    if (has_place or ent.place) and _any(LOCATION, norm) and not (question and not _any(PROJECT_WORDS, norm)):
        return Plan("location_overview", ent)
    # "Any rentals in Riyadh?", "What can I buy in Al Khobar?", "Do you have anything in Makkah?"
    if has_place and not question_is_info(norm) and _any(PLACE_BROWSE, norm):
        if re.search(r"(?<![a-z])(rentals?|to rent)(?![a-z])|ايجار", norm):
            ent.listing_type = ent.listing_type or "rent"
            return Plan("search", ent)
        return Plan("location_overview", ent)
    # Short, unspecific messages ("villas?", "luxury", "best project", "dubai", "something in dubai", "invest"):
    # a known place gets its overview; anything else gets a clarifying answer built from what the data holds,
    # never the no-data template. Short real questions ("What is Wasalt?") still go to retrieval.
    vague_words = bool(_VAGUE_WORDS.search(norm) or _LUXURY.search(norm) or _INVEST.search(norm) or ent.property_type)
    if not ent.project_ids and is_vague(norm) and not question_is_info(norm) and not _any(COMPARE, norm) and (vague_words or (
            (has_place or ent.place) and not question)):
        if has_place or ent.place:
            return Plan("location_overview", ent)
        return Plan("vague", ent, topic=vague_topic(norm, ent.property_type))
    return Plan("general", ent, ambiguous=True)
