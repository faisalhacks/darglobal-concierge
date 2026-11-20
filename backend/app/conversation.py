"""Casual conversation, vague queries and the off-topic spotlight: detection (code) and data-backed facts (code).

Intent detection never uses a model. The reply wording for these intents is written by the LLM writer when it is
available, grounded only in a code-built summary of what the dataset holds; the code templates built here are the
fallback, so a casual message never ends in the no-data template.
"""
from __future__ import annotations

import ast
import hashlib
import operator
import re
from collections import Counter
from dataclasses import dataclass, field

from .arabic import normalize_text

CONVERSATIONAL = ("greeting", "thanks", "goodbye", "identity", "ack")
CONV_INTENTS = CONVERSATIONAL + ("vague",)

# ---------------------------------------------------------------- detection
_PHRASES: dict[str, list[str]] = {
    "greeting": [
        "hi", "hey", "hello", "hiya", "heya", "yo", "sup", "wassup", "whats up", "what is up", "howdy", "greetings",
        "good morning", "good afternoon", "good evening", "good day", "morning", "evening", "hi there", "hey there",
        "hello there", "salam", "salaam", "salam alaikum", "salaam alaikum", "assalamu alaikum", "assalam alaikum",
        "asalam alaikum", "as salamu alaykum", "assalamualaikum", "salamu alaikum", "marhaba", "marhabaa", "ahlan",
        "ahlan wa sahlan", "how are you", "how r u", "how are u", "how are you doing", "hows it going",
        "how is it going", "anyone there", "is anyone there", "bonjour", "hola",
        "مرحبا", "مرحبتين", "اهلا", "اهلين", "اهلا وسهلا", "السلام عليكم", "السلام عليكم ورحمه الله",
        "السلام عليكم ورحمه الله وبركاته", "سلام عليكم", "سلام", "وعليكم السلام", "هلا", "هلا والله", "هاي",
        "صباح الخير", "مساء الخير", "صباح النور", "مساء النور", "كيف حالك", "كيفك", "شلونك", "كيف الحال",
    ],
    "thanks": [
        "thanks", "thank you", "thank u", "thx", "ty", "tysm", "thanks a lot", "many thanks", "cheers",
        "appreciate it", "much appreciated", "shukran", "merci", "no thanks", "no thank you",
        "شكرا", "شكرا جزيلا", "مشكور", "مشكوره", "يعطيك العافيه", "الف شكر", "جزاك الله خير", "تسلم", "شكرا لك",
    ],
    "goodbye": [
        "bye", "goodbye", "good bye", "bye bye", "see you", "see ya", "cya", "see you later", "later", "good night",
        "take care", "ciao", "مع السلامه", "وداعا", "الي اللقاء", "باي", "في امان الله", "تصبح علي خير",
    ],
    "identity": [
        "who are you", "who r u", "who are u", "what are you", "what r u", "who is this", "what is this",
        "whats this", "what can you do", "what can u do", "what do you do", "what can you help with",
        "what can you help me with", "how can you help", "how can you help me", "how do you work",
        "how does this work", "help", "help me", "menu", "options", "what do you know", "what can i ask",
        "what should i ask", "introduce yourself", "tell me about yourself", "about you", "are you a bot",
        "are you human", "are you real", "are you ai", "what is your name", "whats your name",
        "what is ur name", "whats ur name", "what ur name", "wat is ur name", "your name", "ur name", "tell me ur name",
        "tell me your name", "what do i call you", "what should i call you",
        "من انت", "من انتي", "مين انت", "ماذا تستطيع", "ماذا تستطيع ان تفعل", "ماذا يمكنك", "ماذا يمكنك ان تفعل",
        "ما الذي يمكنك فعله", "ماذا تفعل", "كيف تساعدني", "كيف يمكنك مساعدتي", "مساعده", "ساعدني", "ما اسمك",
        "عرفني بنفسك",
    ],
    "ack": [
        "ok", "okay", "k", "kk", "okey", "cool", "great", "nice", "perfect", "sure", "alright", "all right",
        "got it", "fine", "awesome", "understood", "noted", "sounds good", "good", "yes", "yeah", "yep", "yup",
        "wow", "amazing", "interesting", "i see", "makes sense",
        "تمام", "حسنا", "طيب", "ممتاز", "اوكي", "اوك", "جميل", "رائع", "زين", "نعم", "اكيد", "فهمت", "ماشي",
    ],
}
_FILLER = set("""there all guys folks team friend dear sir madam maam bot concierge again so much very a lot please pls plz
and just well oh hmm um umm then you u ya yall everyone mate bro man buddy darglobal wasalt dar global assistant
today for that the now too lol haha hehe again to it""".split()) | {
    normalize_text(w) for w in "يا اخي اختي صديقي الجميع جزيلا لك كثيرا و اخوي حبيبي عزيزي الله".split()}
_PRIORITY = ("identity", "goodbye", "thanks", "greeting", "ack")
_EMOJI = [("👋✋🖐🤝", " hi "), ("🙏", " thanks "), ("👍👌✅", " ok ")]


def _collapse(w: str) -> str:
    """Runs of the same letter -> one ("heyyy" -> "hey", "hello" -> "helo"): both sides of a match use it."""
    return re.sub(r"(.)\1+", r"\1", w)


def _dist(a: str, b: str) -> int:
    """Damerau-Levenshtein (optimal string alignment) distance: "hye" -> "hey" is one transposition."""
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            c = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + c)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[len(a)][len(b)]


_VOCAB = [(intent, tuple(_collapse(t) for t in normalize_text(p).split()))
          for intent, ps in _PHRASES.items() for p in ps]
_VOCAB.sort(key=lambda x: -len(x[1]))  # longest phrase first


def _tok_match(t: str, w: str, fuzzy: bool) -> bool:
    if t == w:
        return True
    if not fuzzy or len(t) < 3 or len(w) < 3:
        return False  # short tokens ("hi", "yo", "ty", "ok") only match exactly
    return _dist(t, w) <= 1


def _tokens(message: str) -> list[str]:
    t = message or ""
    for chars, rep in _EMOJI:
        for ch in chars:
            t = t.replace(ch, rep)
    t = normalize_text(t).replace("'", "").replace("’", "")
    return [_collapse(x) for x in re.findall(r"[a-z0-9]+|[؀-ۿ]+", t)]


def conversational_intent(message: str) -> str | None:
    """greeting | thanks | goodbye | identity | ack when the whole message is small talk, else None.

    Every token must belong to a known phrase (with typo tolerance for tokens of 3+ letters) or be a filler word;
    "hi, projects in Dubai" is a property question and returns None."""
    toks = _tokens(message)
    raw = (message or "").strip()
    if not toks:
        if not raw:
            return None
        return "identity" if ("?" in raw or "؟" in raw) else "greeting"  # "?" -> what can you do; "😊" -> hello
    if len(toks) > 8:
        return None
    found: set[str] = set()
    i = 0
    while i < len(toks):
        hit = None
        for fuzzy in (False, True):
            for intent, ph in _VOCAB:
                n = len(ph)
                if i + n <= len(toks) and all(_tok_match(toks[i + k], ph[k], fuzzy) for k in range(n)):
                    hit = (intent, n)
                    break
            if hit:
                break
        if hit:
            found.add(hit[0])
            i += hit[1]
        elif toks[i] in _FILLER:
            i += 1
        else:
            return None
    return next((x for x in _PRIORITY if x in found), None)


_LUXURY = re.compile(r"(?<![a-z])(luxury|luxurious|premium|high[- ]end|upscale|exclusive|prestige|prestigious|elite|"
                     r"fancy)(?![a-z])|فاخر|فخم|راقي|فخامه")
_INVEST = re.compile(r"(?<![a-z])(invest|investing|investment|investments|investor)(?![a-z])|استثمار|استثمر")
_VAGUE_WORDS = re.compile(r"(?<![a-z])(something|anything|options?|ideas?|recommend\w*|suggest\w*|best|top|good|nice|"
                          r"properties|property|homes?|houses?|real estate|show me|buy|rent|cheap|affordable|new)(?![a-z])"
                          r"|شي|شيء|اقتراح|افضل|عقار|عقارات|منزل|بيت")


def vague_topic(norm: str, property_type: str | None) -> str:
    if _LUXURY.search(norm):
        return "luxury"
    if _INVEST.search(norm):
        return "invest"
    if property_type:
        return "ptype"
    return "generic"


def is_vague(norm: str) -> bool:
    """Short message with nothing specific enough to look up (single words, "villas?", "best project")."""
    words = re.findall(r"[a-z0-9]+|[؀-ۿ]+", norm)
    return 0 < len(words) <= 5


# ---------------------------------------------------------------- arithmetic one-liners ("what's 2+2?")
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


_UNITS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
          "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
          "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
          "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100}
_OPWORDS = {"plus": "+", "add": "+", "and": "+", "minus": "-", "less": "-", "times": "*", "multiplied": "*",
            "divided": "/", "over": "/", "x": "*"}
_AR_OPS = {"زائد": "+", "زايد": "+", "جمع": "+", "ناقص": "-", "طرح": "-", "ضرب": "*", "في": "*", "قسمه": "/",
           "تقسيم": "/"}
_MATH_FILLER = {"what", "whats", "what's", "is", "the", "answer", "to", "calculate", "calc", "how", "much", "equals",
                "equal", "tell", "me", "a", "sum", "of", "by", "please", "pls", "result", "ما", "هو", "هي", "كم",
                "ناتج", "حاصل", "يساوي", "على"}


def _fuzzy(tok: str, vocab) -> str | None:
    import difflib
    if tok in vocab:
        return tok
    if len(tok) < 4:
        return None
    m = difflib.get_close_matches(tok, list(vocab), n=1, cutoff=0.7)
    return m[0] if m else None


def _words_expr(message: str) -> str | None:
    """"34 plus sevn is ?" -> "34+7"; None unless every token is a number, number word, operator word or filler."""
    t = normalize_text(message or "").replace("×", " * ").replace("÷", " / ")
    toks = re.findall(r"\d+(?:\.\d+)?|[a-z']+|[+\-*/]|[؀-ۿ]+", t)
    out: list[str] = []
    pend: int | None = None  # number-word accumulator ("twenty" "five")

    def flush():
        nonlocal pend
        if pend is not None:
            out.append(str(pend))
            pend = None
    for tok in toks:
        if re.fullmatch(r"\d+(?:\.\d+)?", tok):
            flush()
            out.append(tok)
        elif tok in "+-*/" and len(tok) == 1:
            flush()
            out.append(tok)
        elif tok in _AR_OPS:
            flush()
            out.append(_AR_OPS[tok])
        elif tok in _MATH_FILLER:
            continue
        elif tok == "x" or _fuzzy(tok, _OPWORDS):
            flush()
            out.append(_OPWORDS["x" if tok == "x" else _fuzzy(tok, _OPWORDS)])
        elif _fuzzy(tok, _UNITS):
            v = _UNITS[_fuzzy(tok, _UNITS)]
            if v == 100:
                pend = (pend or 1) * 100
            elif pend is not None and pend % 100 >= 20 and pend % 10 == 0 and v < 10 and pend % 100 != 0:
                pend += v
            else:
                flush()
                pend = v
        else:
            return None
    flush()
    expr = "".join(out)
    return expr if re.search(r"\d[-+*/]\d", expr) and not re.search(r"[-+*/]{2}|[-+*/]$|^[+*/]", expr) else None


def simple_arithmetic(message: str) -> tuple[str, str] | None:
    """("2 + 2", "4") for a harmless one-line sum; None for anything else (never evaluates names or calls)."""
    m = re.fullmatch(r"\s*(?:what(?:'?s| is)\s*)?([\d\s+\-*/().x×÷]+?)\s*=?\s*\??\s*", (message or "").lower())
    if m and re.search(r"\d\s*[-+*/x×÷]\s*\d", m.group(1)):
        expr = m.group(1).replace("x", "*").replace("×", "*").replace("÷", "/").strip()
    else:
        expr = _words_expr(message)
        if not expr:
            return None
    if len(expr) > 40:
        return None

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            return -ev(n.operand)
        raise ValueError
    try:
        v = ev(ast.parse(expr, mode="eval"))
    except (ValueError, SyntaxError, ZeroDivisionError, TypeError):
        return None
    if abs(v) > 1e12:
        return None
    out = str(int(v)) if float(v).is_integer() else f"{v:.4f}".rstrip("0").rstrip(".")
    shown = re.sub(r"\s*([-+*/])\s*", r" \1 ", expr).strip()
    return shown, out


_SPLIT = re.compile(r"\s*(?:[,;&?!؟،]|\.(?!\d)|\band\b|\bthen\b|\bplus\b(?=\s+(?:what|who|how|tell))|و(?=\s))\s*")


def compound_smalltalk(message: str) -> tuple[tuple[str, str], str] | None:
    """("4 + 7", "11"), "identity" for a message made only of one harmless sum plus small talk ("4+7, what is ur name"):
    every segment is either a sum or whole-message small talk. None otherwise (never a dead end for these)."""
    segs = [x for x in _SPLIT.split(message or "") if x and x.strip()]
    if len(segs) < 2 or len(segs) > 4:
        return None
    calc, intents = None, []
    for seg in segs:
        c = simple_arithmetic(seg) if calc is None else None
        if c:
            calc = c
            continue
        i = conversational_intent(seg)
        if not i:
            return None
        intents.append(i)
    if not calc or not intents:
        return None
    return calc, next((x for x in _PRIORITY if x in intents), intents[0])


# ---------------------------------------------------------------- data summary (all numbers counted from rows)
def ar_count(n: int, one: str, two: str, few: str, many: str) -> str:
    """Arabic number + noun agreement for counts (1, 2, 3-10, 11+; hundreds take the singular)."""
    if n == 1:
        return f"{one} واحد" if not one.endswith("ة") else f"{one} واحدة"
    if n == 2:
        return two
    r = n % 100
    if 3 <= r <= 10:
        return f"{n:,} {few}"
    if r in (0, 1, 2) and n >= 100:
        return f"{n:,} {one}"
    return f"{n:,} {many}"


def holdings(store) -> dict:
    dg = [p for p in store.projects if str(p.get("site")) == "DarGlobal"]
    wp = [p for p in store.projects if str(p.get("site")) == "Wasalt"]
    dg_countries = Counter(p.get("country") for p in dg if p.get("country"))
    proj_countries = Counter(p.get("country") for p in store.projects if p.get("country"))
    list_cities = Counter(x.get("city") for x in store.listings if x.get("city"))
    ptypes = Counter(x.get("property_type") for x in store.listings if x.get("property_type"))
    brands = Counter(p.get("brand_partner") for p in store.projects if p.get("brand_partner"))
    dg_cities = Counter(p.get("city") for p in dg if p.get("city"))
    rent_cities = Counter(x.get("city") for x in store.listings if x.get("city") and x.get("listing_type") == "rent")
    return {"dg": len(dg), "dg_countries": dg_countries, "wp": len(wp),
            "wp_countries": Counter(p.get("country") for p in wp if p.get("country")),
            "proj_countries": proj_countries, "listings": len(store.listings), "list_cities": list_cities,
            "ptypes": ptypes, "brands": brands, "branded": sum(brands.values()), "dg_cities": dg_cities,
            "rent_cities": rent_cities}


def spotlight(store, message: str) -> dict | None:
    """A DarGlobal project with its own collected page and a published description, rotated by message hash
    (projects with photos first). Facts about it are only ever read from its row."""
    from .store import _first_image, detail_level
    pool = [p for p in store.projects if str(p.get("site")) == "DarGlobal" and detail_level(p) == "page"
            and (p.get("description_en") or "").strip()]
    if not pool:
        pool = [p for p in store.projects if (p.get("description_en") or "").strip()]
    if not pool:
        return None
    photo = [p for p in pool if _first_image(p)]
    pool = sorted(photo or pool, key=lambda p: p["id"])
    h = int(hashlib.sha256(normalize_text(message).encode()).hexdigest(), 16)
    return pool[h % len(pool)]


def first_sentence(text: str) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    m = re.match(r"(.{20,320}?[.!?])(\s|$)", t)
    return (m.group(1) if m else t[:320]).strip()


STATUS_AR = {"under development": "قيد التطوير", "completed": "مكتمل", "completed and sold out": "مكتمل ومباع بالكامل",
             "sold out": "مباع بالكامل", "ready": "جاهز", "off-plan": "على الخريطة", "launched": "تم الإطلاق"}


# ---------------------------------------------------------------- conversation memory (stateless, rebuilt per request)
# Frozen contract (docs/CONTRACT_QUALITY.md §1). Nothing is stored server-side: every request rebuilds the memory from
# the client's history (user turns re-planned in code) plus the client's `last_entities` ids, which are validated
# against the store. Values never come from the client verbatim; only ids do, and unknown ids are dropped.


MAX_LAST_ENTITIES = 6
MEMORY_FIELDS = ("site", "country", "city", "property_type", "listing_type", "beds", "budget_max", "currency")


@dataclass
class Memory:
    site: str | None = None            # "DarGlobal" | "Wasalt" | None
    country: str | None = None         # canonical English name, as in the store
    city: str | None = None
    property_type: str | None = None   # villa | apartment | townhouse | land | floor | penthouse ...
    listing_type: str | None = None    # "buy" | "rent" | None
    beds: int | None = None
    budget_max: float | None = None
    currency: str | None = None        # ISO code ("SAR", "AED", "OMR" ...)
    last_entities: list[str] = field(default_factory=list)  # ids shown on the previous turn, order kept, max 6
    last_intent: str | None = None
    # Added behind the frozen fields (allowed by the contract):
    brand: str | None = None
    projects_level: bool = False       # the remembered request was about projects, not listings
    reset: bool = False                # the memory was cleared on this request (reset phrase or understanding)

    def filters(self) -> dict:
        """The remembered search filters that are set (no ids, no intent)."""
        return {k: getattr(self, k) for k in MEMORY_FIELDS + ("brand",) if getattr(self, k) is not None}

    def is_empty(self) -> bool:
        return not self.filters() and not self.last_entities

    def merge(self, values: dict) -> None:
        """An explicit new value wins over the remembered one; a new country clears the remembered city."""
        new_country = values.get("country")
        if new_country and new_country != self.country and not values.get("city"):
            self.city = None
        for k in MEMORY_FIELDS + ("brand",):
            v = values.get(k)
            if v is not None:
                setattr(self, k, v)

    def clear(self) -> None:
        for k in MEMORY_FIELDS + ("brand",):
            setattr(self, k, None)
        self.last_entities = []
        self.last_intent = None
        self.projects_level = False
        self.reset = True


def validate_entity_ids(ids, store) -> list[str]:
    """Client-sent ids: strings only, known to the store (projects or listings), de-duplicated, order kept, max 6."""
    out: list[str] = []
    for i in ids if isinstance(ids, (list, tuple)) else []:
        if not isinstance(i, str) or not i or len(i) > 120 or i in out:
            continue
        if store.project_by_id(i) or store.listing_by_id(i):
            out.append(i)
        if len(out) >= MAX_LAST_ENTITIES:
            break
    return out


def entity_name(store, eid: str) -> str | None:
    p = store.project_by_id(eid)
    if p:
        return p.get("name_en") or p.get("name_ar") or eid
    x = store.listing_by_id(eid)
    if x:
        return x.get("title") or eid
    return None


def memory_block(mem: "Memory", store) -> str:
    """Plain-text memory for a prompt: remembered filters, then the previous turn's entities as numbered lines with
    names resolved from the store (never from the client)."""
    f = mem.filters()
    lines = ["remembered filters: " + (", ".join(f"{k}={v}" for k, v in f.items()) if f else "none")]
    if mem.last_intent:
        lines.append(f"previous intent: {mem.last_intent}")
    if mem.last_entities:
        lines.append("shown on the previous turn (1-based positions for refs):")
        for n, eid in enumerate(mem.last_entities, 1):
            row = store.project_by_id(eid) or store.listing_by_id(eid) or {}
            where = ", ".join(v for v in (row.get("city"), row.get("country")) if v)
            kind = "project" if store.project_by_id(eid) else "listing"
            lines.append(f"{n}. {eid} = {entity_name(store, eid)} ({kind}{', ' + where if where else ''})")
    else:
        lines.append("shown on the previous turn: nothing")
    return "\n".join(lines)


# "forget that", "something else", "start over", "انسى", "غير الموضوع": the user abandons the previous topic.
RESET_RX = re.compile(
    r"(?<![a-z])(forget (that|it|this|about (that|it|this|those|them))|never ?mind|start (over|again|fresh)|"
    r"something (else|different)|different (topic|question|thing)|change (of )?(the )?(topic|subject)|"
    r"new (search|topic|question)|scratch that|from scratch|reset)(?![a-z])"
    r"|(?<![\w])(انس[يا]?|انسي ذلك|خلنا من|غير الموضوع|موضوع ثاني|موضوع اخر|شي ثاني|شيء اخر|من جديد|ابدا من جديد)(?![\w])")


def is_reset(norm: str) -> bool:
    return bool(RESET_RX.search(norm))


# Words that point at something shown earlier ("it", "them", "that one", "the second", "both", "هذا", "الثاني").
REFERENCE_RX = re.compile(
    r"(?<![a-z])(it|its|it's|them|they|those|these|that one|this one|that project|this project|the one|"
    r"both|either|each|first|second|third|fourth|last|1st|2nd|3rd|4th|former|latter|same one|the others?)(?![a-z])"
    r"|(?<![\w])(هذا|هذه|هذي|ذلك|تلك|هذاك|هذيك|هم|منهم|الاثنين|كلاهما|الاول|الثاني|الثالث|الرابع|الاخير|"
    r"نفسه|سعره|موقعه|تسليمه|مساحته)(?![\w])")


def has_reference(norm: str) -> bool:
    return bool(REFERENCE_RX.search(norm))
