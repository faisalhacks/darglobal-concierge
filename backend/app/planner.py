"""Code planner (SPEC §9): rules + entity extraction, no LLM.

Intents: project_info, compare, search, calculation, location_overview, brand_partner, contact_sales,
find_my_home, off_topic, injection, advice, general (+ greeting, routed as a template).
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from .arabic import normalize_text
from .guardrails import is_injection
from .store import Store

# Canonical place name -> aliases (EN + AR, matched on normalised text).
PLACE_ALIASES: dict[str, list[str]] = {
    "Dubai": ["dubai", "دبي"],
    "Abu Dhabi": ["abu dhabi", "abudhabi", "ابوظبي", "ابو ظبي"],
    "Ras Al Khaimah": ["ras al khaimah", "rak", "راس الخيمه"],
    "United Arab Emirates": ["uae", "united arab emirates", "emirates", "الامارات"],
    "Riyadh": ["riyadh", "الرياض", "رياض"],
    "Jeddah": ["jeddah", "jedda", "جده"],
    "Makkah": ["makkah", "mecca", "مكه"],
    "Madinah": ["madinah", "medina", "المدينه المنوره"],
    "Dammam": ["dammam", "الدمام"],
    "Khobar": ["khobar", "al khobar", "الخبر"],
    "Saudi Arabia": ["saudi arabia", "saudi", "ksa", "السعوديه"],
    "Muscat": ["muscat", "مسقط"],
    "Oman": ["oman", "عمان", "سلطنه عمان"],
    "Doha": ["doha", "الدوحه"],
    "Qatar": ["qatar", "قطر"],
    "Bahrain": ["bahrain", "البحرين"],
    "London": ["london", "لندن"],
    "United Kingdom": ["uk", "united kingdom", "england", "britain", "بريطانيا", "المملكه المتحده"],
    "Marbella": ["marbella", "ماربيا", "ماربيلا"],
    "Spain": ["spain", "اسبانيا"],
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
    "Marbella": "ماربيا", "Spain": "إسبانيا", "Maldives": "المالديف", "Bosnia": "البوسنة", "Greece": "اليونان",
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
    "gbp": "GBP", "£": "GBP", "pound": "GBP", "pounds": "GBP", "جنيه": "GBP",
    "eur": "EUR", "€": "EUR", "euro": "EUR", "euros": "EUR", "يورو": "EUR",
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

    def key(self) -> str:
        return "|".join(map(str, [sorted(self.project_ids), self.city, self.country, self.budget_min, self.budget_max,
                                  self.beds, self.currency, self.listing_type, self.property_type, self.brand, self.site]))


@dataclass
class Plan:
    intent: str
    entities: Entities
    ambiguous: bool = False
    follow_up: bool = False


def _has(norm: str, words) -> bool:
    return any(re.search(rf"(?<![\w]){re.escape(w)}(?![\w])", norm) for w in words)


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


def extract_budget(norm: str) -> tuple[float | None, float | None]:
    lo = hi = None
    m = re.search(rf"(under|below|less than|up to|upto|max|maximum|within|اقل من|تحت|حتى|بحدود)\s*(?:[a-z$£€]{{0,4}}\s*)?{_AMOUNT}", norm)
    if m:
        hi = parse_amount(m.group(2), m.group(3))
    m = re.search(rf"(over|above|more than|at least|min|minimum|from|اكثر من|فوق|من)\s*(?:[a-z$£€]{{0,4}}\s*)?{_AMOUNT}", norm)
    if m and not re.search(r"\d\s*%", norm[m.start():m.end() + 2]):
        lo = parse_amount(m.group(2), m.group(3))
    m = re.search(rf"between\s*{_AMOUNT}\s*(?:and|-|to)\s*{_AMOUNT}", norm)
    if m:
        lo, hi = parse_amount(m.group(1), m.group(2)), parse_amount(m.group(3), m.group(4))
    return lo, hi


def extract_beds(norm: str) -> int | None:
    m = re.search(r"(\d+)\s*[- ]?\s*(bed|beds|bedroom|bedrooms|br|bhk|غرف|غرفه نوم|غرف نوم)\b", norm)
    if m:
        return int(m.group(1))
    if re.search(r"\bstudio\b|استوديو", norm):
        return 0
    for w, n in _AR_NUM_WORDS.items():
        if w in norm:
            return n
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
        if _has(norm, [alias]):
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


def project_aliases(p: dict) -> list[str]:
    out = []
    for k in ("name_en", "name_ar"):
        v = p.get(k)
        if not v:
            continue
        n = normalize_text(v)
        cands = [n, n.split(" - ")[0].strip()]
        cands += [re.sub(r"^(the|مشروع)\s+", "", c) for c in cands]
        for c in cands:
            c = re.sub(r"\s+", " ", c).strip(" -")
            if len(c) >= 3 and not _is_generic(c):
                out.append(c)
    return list(dict.fromkeys(out))


def extract_projects(norm: str, store: Store) -> list[str]:
    hits: list[tuple[int, str]] = []
    words = norm.split()
    for p in store.projects:
        best = None
        for alias in project_aliases(p):
            idx = norm.find(alias)
            if idx >= 0 and (idx == 0 or not norm[idx - 1].isalnum()):
                best = idx if best is None else min(best, idx)
                continue
            # fuzzy: compare alias against same-length word windows
            n = len(alias.split())
            if n == 1 and alias in _GENERIC_NAME_TOKENS:
                continue
            for i in range(0, max(len(words) - n + 1, 0)):
                window = " ".join(words[i:i + n])
                if len(window) >= 4 and difflib.SequenceMatcher(None, window, alias).ratio() >= 0.86:
                    pos = norm.find(window)
                    best = pos if best is None else min(best, pos)
                    break
        if best is not None:
            hits.append((best, p["id"]))
    hits.sort()
    return list(dict.fromkeys(pid for _, pid in hits))


def extract_entities(text: str, store: Store) -> Entities:
    norm = normalize_text(text)
    e = Entities()
    e.project_ids = extract_projects(norm, store)
    e.city, e.country, e.place = extract_places(norm, store)
    e.budget_min, e.budget_max = extract_budget(norm)
    e.beds = extract_beds(norm)
    e.currency = extract_currency(norm)
    if _has(norm, ["rent", "rental", "for rent", "lease", "ايجار", "للايجار"]):
        e.listing_type = "rent"
    elif _has(norm, ["buy", "for sale", "sale", "purchase", "للبيع", "شراء", "بيع"]):
        e.listing_type = "buy"
    for ptype, words in (("villa", ["villa", "villas", "فيلا", "فلل", "فيلات"]),
                         ("apartment", ["apartment", "apartments", "flat", "flats", "شقه", "شقق"]),
                         ("townhouse", ["townhouse", "townhouses", "تاون هاوس"]),
                         ("penthouse", ["penthouse", "penthouses", "بنتهاوس"]),
                         ("land", ["land", "plot", "ارض", "اراضي"])):
        if _has(norm, words):
            e.property_type = ptype
            break
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
ADVICE = [r"\bguarantee", r"\broi\b", r"return on investment", r"\bgood investment\b", r"\bbest investment\b",
          r"should i (buy|invest)", r"\bwill (the )?(prices?|values?|it) (rise|go up|increase|appreciate)",
          r"capital (appreciation|gain)", r"\bprofit\b", r"\bworth investing\b", r"\bis it a good time\b",
          r"ضمان", r"مضمون", r"عائد", r"هل استثمر", r"استثمار جيد", r"افضل استثمار", r"ربح", r"هل اشتري"]
CONTACT = [r"\bcontact\b", r"\bcall me\b", r"\bbook (a )?(viewing|visit|tour|appointment)", r"\bsales (team|agent|office)",
           r"\bspeak (to|with) (a |an )?(human|agent|person|someone)", r"\bphone number\b", r"\bwhatsapp\b",
           r"\bget in touch\b", r"تواصل", r"اتصل", r"رقم الهاتف", r"حجز (موعد|معاينه|زياره)", r"فريق المبيعات"]
CALC = [r"\d\s*%\s*(down|deposit|upfront|مقدم|دفعه)", r"(down ?payment|deposit|دفعه مقدمه|مقدم)",
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
LOCATION = [r"\bprojects?\b", r"\bdevelopments?\b", r"\bwhat (do you have|is available)\b", r"\bwhere\b",
            r"مشاريع|مشروع|ماذا لديكم|المتوفره|المتوفر"]
BRAND = [r"\bbranded\b", r"\bbrand partners?\b", r"\bpartners?\b", r"\bpartnership",
         r"علامات تجاريه|العلامات التجاريه|علامه تجاريه|شركاء|الشركاء"]
PROJECT_WORDS = [r"\bprojects?\b", r"\bdevelopments?\b", r"مشاريع|مشروع"]
FMH = [r"\bfind (me )?(a |my )?home\b", r"\bhelp me (find|choose)\b", r"ساعدني في (ايجاد|اختيار)", r"ابحث لي عن منزل"]
GREETING = [r"^(hi|hello|hey|salam|good (morning|evening|afternoon)|greetings)\b[!. ]*$",
            r"^(مرحبا|اهلا|السلام عليكم|صباح الخير|مساء الخير)[!. ]*$"]
FOLLOW_UP = [r"^(and |what about |how about )?(the )?(price|prices|cost|handover|status|location|size|area|amenities|units?|"
             r"payment plan|completion|when)\b", r"\b(it|this one|that one|this project|that project)\b",
             r"^(وماذا عن|ماذا عن|كم|متى|و?السعر|و?الاسعار|التسليم)", r"(هذا المشروع|ذلك المشروع)"]


PLACE_BROWSE = [r"(?<![a-z])any(thing)?(?![a-z])", r"(?<![a-z])what can i (buy|rent)(?![a-z])", r"(?<![a-z])rentals?(?![a-z])", r"(?<![a-z])for (sale|rent)(?![a-z])",
                r"(?<![a-z])what (do you have|is there)(?![a-z])", r"عندكم|لديكم|للايجار|للبيع"]


def question_is_info(norm: str) -> bool:
    """Questions about rules/processes in a place ("how do auctions work in Riyadh") are not browsing."""
    return bool(re.search(r"(?<![a-z])(how|why|rules?|laws?|process|tax|fees?|mortgage|interest)(?![a-z])|كيف|لماذا|قوانين|رسوم", norm))


def _any(patterns, norm: str) -> bool:
    return any(re.search(p, norm) for p in patterns)


def plan(message: str, store: Store, history: list[dict] | None = None, flags: dict | None = None) -> Plan:
    flags = flags or {}
    norm = normalize_text(message)
    ent = extract_entities(message, store)

    if is_injection(message):
        return Plan("injection", ent)
    if _any(GREETING, norm):
        return Plan("greeting", ent)
    if _any(ADVICE, norm):
        return Plan("advice", ent)
    if _any(CONTACT, norm):
        return Plan("contact_sales", ent)
    has_money = bool(re.search(r"\d", norm)) and (ent.currency is not None or re.search(r"\d\s*%|\d\s*(m|k|million|مليون)\b", norm))
    if _any(CALC, norm) and has_money:
        return Plan("calculation", ent)
    if _any(OFF_TOPIC, norm) and not ent.project_ids:
        return Plan("off_topic", ent)
    if _any(CALC, norm) and re.search(r"\d", norm):
        return Plan("calculation", ent)

    follow_up = False
    if not ent.project_ids and history and _any(FOLLOW_UP, norm):
        for turn in reversed(history[-8:]):
            ids = extract_projects(normalize_text(turn.get("content") or ""), store)
            if ids:
                ent.project_ids = ids[:2]
                follow_up = True
                break

    if _any(COMPARE, norm):
        return Plan("compare", ent, follow_up=follow_up)
    if flags.get("FF_FIND_MY_HOME") and _any(FMH, norm):
        return Plan("find_my_home", ent)
    if ent.project_ids:
        return Plan("project_info", ent, follow_up=follow_up)
    question = bool(re.match(r"^(can|could|how|why|what is|what are|what's|is|are|do|does|should|who|explain|"
                             r"هل|كيف|لماذا|ما هو|ما هي|ماهو|ماهي)\b", norm))
    has_place = bool(ent.city or ent.country)
    wants_listing = (ent.beds is not None or ent.budget_max is not None
                     or (ent.property_type is not None and (has_place or ent.listing_type is not None))
                     or (ent.listing_type is not None and has_place and not question))
    if _any(SEARCH, norm) and wants_listing:
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
    return Plan("general", ent, ambiguous=True)
