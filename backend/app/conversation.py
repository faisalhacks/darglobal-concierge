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


def simple_arithmetic(message: str) -> tuple[str, str] | None:
    """("2 + 2", "4") for a harmless one-line sum; None for anything else (never evaluates names or calls)."""
    m = re.fullmatch(r"\s*(?:what(?:'?s| is)\s*)?([\d\s+\-*/().x×÷]+?)\s*=?\s*\??\s*", (message or "").lower())
    if not m or not re.search(r"\d\s*[-+*/x×÷]\s*\d", m.group(1)):
        return None
    expr = m.group(1).replace("x", "*").replace("×", "*").replace("÷", "/").strip()
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
