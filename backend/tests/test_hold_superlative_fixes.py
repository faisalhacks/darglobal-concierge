"""Live-site bug fixes: (1) the "what I hold" counts survive the number check, (2) a project is never placed in a
city/country the data does not give it, (3) superlative follow-ups ("most expensive one??", "الأرخص") sort the carried
set in code, (4) "any auction for villa" says there are no auction listings and points to the auctions page."""
import copy
import re

import pytest

from backend.app.llm import MockLLM
from backend.app.planner import plan

NOT_PUB = ("not published", "غير منشور")


class Scripted(MockLLM):
    """Mock writer that returns a fixed reply (what a live model might say)."""

    def __init__(self, reply: str):
        super().__init__()
        self.reply = reply

    def _compose(self, messages):
        return self.reply


def _inflate_listings(client, n=1661):
    st = client.app.state.store
    base = st.listings[0]
    st.listings.extend(copy.deepcopy(base) for _ in range(n - len(st.listings)))
    return st


# ---------------------------------------------------------------- 1. hold-summary numbers survive
def test_greeting_keeps_real_counts_in_checked_context(make_client, ask):
    c = make_client(llm=Scripted("Welcome! I hold 1,661 Wasalt listings across 2 cities and 3 DarGlobal projects. "
                                 "Shall we start with villas or apartments?"))
    _inflate_listings(c)
    d = ask(c, "salam")
    assert "1,661" in d["_text"] and not any(x in d["_text"] for x in NOT_PUB)
    assert d["trace"][0]["degraded"] is False


@pytest.mark.parametrize("reply", ["Welcome to Wasalt's 1,600-plus listings across Riyadh and Jeddah, happy to help you today.",
                                   "Hello! I hold over 1,700 listings and plenty of projects for you to browse today."])
def test_rounded_count_never_becomes_not_published_plus(make_client, ask, reply):
    c = make_client(llm=Scripted(reply))
    _inflate_listings(c)
    d = ask(c, "salam")
    t = d["_text"]
    assert not any(x in t for x in NOT_PUB) and "published-plus" not in t
    assert "1,661" in t  # the code-built greeting with the real count replaced the rounded wording


def test_greeting_arabic_keeps_counts(make_client, ask):
    c = make_client(llm=Scripted("أهلاً بك! لدي 1,661 عرضاً من وصلت في مدينتين وثلاثة مشاريع لدار جلوبال. كيف أساعدك؟"))
    _inflate_listings(c)
    d = ask(c, "السلام عليكم")
    assert "1,661" in d["_text"] and not any(x in d["_text"] for x in NOT_PUB)


# ---------------------------------------------------------------- 2. location grounding
def _astera(client):
    st = client.app.state.store
    st.projects.append(dict(id="dg-the-astera-interiors-by-aston-martin", site="DarGlobal",
                            name_en="The Astera, Interiors by Aston Martin", name_ar=None, city="Ras Al Khaimah",
                            country="United Arab Emirates", slug="astera", source_url=None))
    return client.app.state.engine


def test_summary_examples_carry_their_location(client):
    eng = client.app.state.engine
    txt = eng._summary_text("en")
    assert "Fixture Oman Heights (Muscat, Oman)" in txt


@pytest.mark.parametrize("text,bad", [
    ("DarGlobal villa projects such as The Astera in Oman are popular.", True),
    ("The Astera (Oman) is a tower.", True),
    ("The Astera, Interiors by Aston Martin sits in Dubai.", True),
    ("The Astera in Ras Al Khaimah is a tower.", False),
    ("The Astera (Al Marjan Island, Ras Al Khaimah, UAE) is a tower.", False),
    ("The Astera is in the United Arab Emirates, and Fixture Oman Heights is in Oman.", False),
    ("Projects such as The Astera, Fixture Oman Heights in Oman.", False),
    ("Wasalt has villas in Oman.", False),
])
def test_location_conflict_detector(client, text, bad):
    eng = _astera(client)
    assert eng._location_conflict(text) is bad


def test_wrong_location_in_prose_falls_back_to_code_text(make_client, ask):
    c = make_client(llm=Scripted("Lovely choice! DarGlobal villa projects such as Fixture Marina Tower in Oman are "
                                 "popular, and you can browse them with me today."))
    d = ask(c, "salam")
    t = d["_text"]
    assert "Marina Tower in Oman" not in t
    assert d["trace"][0]["degraded"] is True


# ---------------------------------------------------------------- 3. superlatives
HIST = [{"role": "user", "content": "any auction for villa"},
        {"role": "assistant", "content": "I don't see any auction listings in the data I hold."}]


@pytest.mark.parametrize("msg,key", [
    ("most expensive one??", "price_desc"), ("most expenmsive one", "price_desc"), ("priciest?", "price_desc"),
    ("cheapest one", "price_asc"), ("lowest price", "price_asc"), ("biggest", "area_desc"), ("largest one", "area_desc"),
    ("smallest?", "area_asc"), ("newest", "newest"), ("الأغلى", "price_desc"), ("الأرخص", "price_asc"),
    ("الأكبر", "area_desc"), ("الأصغر", "area_asc")])
def test_superlative_intent_with_history(store, msg, key):
    p = plan(msg, store, HIST)
    assert p.intent == "superlative" and p.topic == key
    assert p.entities.property_type == "villa"  # carried from "any auction for villa"


def test_most_expensive_villa_en(client, ask):
    d = ask(client, "most expensive one??", history=HIST)
    t = d["_text"]
    assert d["trace"][0]["path"] == "code" and d["meta"][0]["intent"] == "superlative"
    assert t.startswith("The most expensive villa for sale in the Wasalt sample is Fixture 3-bed villa, Al Malqa")
    assert "Al Malqa, Riyadh at 3,400,000 SAR" in t and "here is the top 1" in t
    assert [x["id"] for x in d["cards"][0]["listings"]] == ["l-2"]
    assert "don't have pricing" not in t


def test_superlative_apartments_sorted_and_defaults_to_buy(client, ask):
    h = [{"role": "user", "content": "apartments"}, {"role": "assistant", "content": "ok"}]
    d = ask(client, "cheapest one?", history=h)
    assert "Fixture 2-bed apartment, Al Olaya" in d["_text"] and "1,200,000 SAR" in d["_text"]  # buy, not the rent one
    d = ask(client, "biggest", history=h)
    assert "140 m²" in d["_text"] and "largest" in d["_text"]


def test_superlative_arabic(client, ask):
    d = ask(client, "الأرخص", history=[{"role": "user", "content": "فلل للبيع في الرياض"},
                                       {"role": "assistant", "content": "تمام"}])
    t = d["_text"]
    assert d["meta"][0]["lang"] == "ar" and "أرخص فيلا للبيع في الرياض" in t and "3,400,000" in t
    assert d["cards"][0]["listings"][0]["id"] == "l-2"
    d = ask(client, "الأغلى", history=[{"role": "user", "content": "شقق"}, {"role": "assistant", "content": "تمام"}])
    assert "أغلى شقة للبيع" in d["_text"]


def test_superlative_darglobal_projects_have_no_prices(client, ask):
    for pr in client.app.state.store.projects:  # the live DarGlobal rows hold no prices
        pr["price_from_amount"] = None
    h = [{"role": "user", "content": "darglobal projects in oman"}, {"role": "assistant", "content": "ok"}]
    d = ask(client, "most expensive one?", history=h)
    t = d["_text"]
    assert "not published" in t and "largest by published area" in t and "latest handover" in t
    assert not d.get("cards")
    d = ask(client, "الأغلى مشروع دار جلوبال")
    assert "غير منشورة" in d["_text"]


def test_superlative_newest_listing_has_no_date(client, ask):
    d = ask(client, "newest one", history=HIST)
    assert "not published" in d["_text"]


def test_cheapest_without_history_keeps_old_search(store):
    assert plan("cheapest villa in Riyadh", store).intent == "search"


# ---------------------------------------------------------------- 4. auctions pointer
def test_auction_for_villa_points_to_auctions_page_en(client, ask):
    d = ask(client, "any auction for villa")
    t = d["_text"]
    assert "auction listings" in t and "Wasalt does run property auctions" in t and "[1]" in t
    assert d["sources"][0][0]["url"].endswith("/auctions")
    assert "How do Wasalt auctions work?" in [c["label"] for c in d["chips"][0]]
    assert d["trace"][0]["path"] == "template"


def test_auction_for_villa_ar(client, ask):
    d = ask(client, "في مزاد على فيلا؟")
    t = d["_text"]
    assert "مزادات" in t and d["sources"][0][0]["url"].endswith("/ar/auctions")
    assert any("كيف تعمل مزادات وصلت" in c["label"] for c in d["chips"][0])


def test_auction_process_question_still_explains(client, ask):
    d = ask(client, "How do Wasalt auctions work?")
    assert "refundable deposit" in d["_text"]
