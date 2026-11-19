"""Messy real-world listing requests (EN / AR / Hinglish / typos): intent, parsed filters, code-built summary + cards,
never a blog/guide extract."""
import pytest

from backend.app.planner import extract_entities, plan

# (message, expected filters subset)
PARSE = [
    ("buy 1 bhk", {"beds": 1, "listing_type": "buy"}),
    ("2bhk flat in riyad", {"beds": 2, "property_type": "apartment", "city": "Riyadh"}),
    ("2 BHK apartment Riyadh", {"beds": 2, "property_type": "apartment", "city": "Riyadh"}),
    ("1br for rent riyadh", {"beds": 1, "listing_type": "rent", "city": "Riyadh"}),
    ("1bd to rent in jedda", {"beds": 1, "listing_type": "rent", "city": "Jeddah"}),
    ("one bedroom to buy", {"beds": 1, "listing_type": "buy"}),
    ("two bedroom flat jeddah", {"beds": 2, "property_type": "apartment", "city": "Jeddah"}),
    ("3-bed villa to own in jeddah below 3.5m", {"beds": 3, "property_type": "villa", "listing_type": "buy",
                                                 "city": "Jeddah", "budget_max": 3_500_000}),
    ("studio for rent", {"beds": 0, "listing_type": "rent"}),
    ("1 RK in riyadh", {"beds": 0, "city": "Riyadh"}),
    ("villa under 2 million sar", {"property_type": "villa", "budget_max": 2_000_000, "currency": "SAR"}),
    ("apartment below 500k", {"property_type": "apartment", "budget_max": 500_000}),
    ("flat 1.5 million riyadh max", {"property_type": "apartment", "city": "Riyadh"}),
    ("cheap apartment jedda", {"property_type": "apartment", "city": "Jeddah", "sort": "price_asc"}),
    ("affordable villa riyadh", {"property_type": "villa", "city": "Riyadh", "sort": "price_asc"}),
    ("plot in dammam", {"property_type": "land"}),
    ("land for sale riyadh", {"property_type": "land", "listing_type": "buy", "city": "Riyadh"}),
    ("townhouse for lease", {"property_type": "townhouse", "listing_type": "rent"}),
    ("penthouse dubay", {"property_type": "penthouse", "city": "Dubai"}),
    ("flat 1500 sqft riyadh", {"property_type": "apartment", "city": "Riyadh", "area_m2": 139.4,
                               "budget_min": None, "budget_max": None}),
    ("apartment 120 sqm riyadh", {"property_type": "apartment", "area_m2": 120.0}),
    ("yearly rent apartment riyadh", {"listing_type": "rent", "property_type": "apartment"}),
    ("monthly rental flat jeddah", {"listing_type": "rent", "property_type": "apartment", "city": "Jeddah"}),
    ("purchase villa in riyadh", {"listing_type": "buy", "property_type": "villa", "city": "Riyadh"}),
    ("appartment in riyad with 2 bathroms", {"property_type": "apartment", "city": "Riyadh", "baths": 2}),
    ("vila jeddah", {"property_type": "villa", "city": "Jeddah"}),
    ("furnished apartment jeddah monthly", {"furnished": True, "listing_type": "rent", "city": "Jeddah"}),
    ("bhai 2bhk chahiye riyadh me", {"beds": 2, "city": "Riyadh"}),
    ("mujhe 3 bhk villa chahiye jeddah", {"beds": 3, "property_type": "villa", "city": "Jeddah"}),
    ("2 bed in AED under 2m", {"beds": 2, "currency": "AED", "budget_max": 2_000_000}),
    ("$500k apartment", {"currency": "USD", "property_type": "apartment"}),
    ("office space riyadh", {"property_type": "office", "city": "Riyadh"}),
    ("شقة غرفتين للبيع في الرياض", {"beds": 2, "listing_type": "buy", "property_type": "apartment", "city": "Riyadh"}),
    ("شقة غرفة للإيجار في الرياض", {"beds": 1, "listing_type": "rent", "city": "Riyadh"}),
    ("فيلا للبيع في جدة أقل من 3 مليون ريال", {"property_type": "villa", "listing_type": "buy", "city": "Jeddah",
                                             "budget_max": 3_000_000, "currency": "SAR"}),
    ("شقة غرفتين للبيع في الرياض أقل من مليون", {"beds": 2, "budget_max": 1_000_000, "budget_min": None}),
    ("شقة غرفتين للبيع في الرياض حتى ٨٠٠ ألف", {"beds": 2, "budget_max": 800_000}),
    ("ارض للبيع بالرياض", {"property_type": "land", "listing_type": "buy", "city": "Riyadh"}),
    ("شقق للايجار في جده", {"property_type": "apartment", "listing_type": "rent", "city": "Jeddah"}),
    ("ابي اشتري فيلا في الرياض", {"property_type": "villa", "listing_type": "buy", "city": "Riyadh"}),
    ("شقة مفروشة للإيجار في جدة", {"furnished": True, "listing_type": "rent", "city": "Jeddah"}),
    ("استوديو للايجار", {"beds": 0, "listing_type": "rent"}),
]


@pytest.mark.parametrize("msg,want", PARSE)
def test_messy_phrasing_parses_filters(store, msg, want):
    e = extract_entities(msg, store)
    for k, v in want.items():
        got = getattr(e, k)
        if isinstance(v, float) and got is not None:
            assert abs(got - v) < 0.5, (k, got)
        else:
            assert got == v, (k, got)


@pytest.mark.parametrize("msg,want", PARSE)
def test_messy_phrasing_routes_to_search(store, msg, want):
    assert plan(msg, store).intent == "search", msg


@pytest.mark.parametrize("msg,n_min", [
    ("buy 1 bhk", 0), ("2bhk flat in riyad", 1), ("2 BHK apartment Riyadh", 1), ("1 bed apartment riyadh", 0),
    ("villa riyadh", 1), ("cheap apartment jedda", 1), ("شقة غرفتين للبيع في الرياض", 1),
    ("فيلا للبيع في الرياض", 1), ("rent flat jeddah 2bhk", 1)])
def test_search_answers_are_code_built_with_cards(client, ask, msg, n_min):
    d = ask(client, msg)
    t = d["_text"]
    assert d["trace"][0]["intent"] == "search" and d["trace"][0]["path"] == "code"
    assert not t.startswith(("From the published source", "من المصدر المنشور")), "no blog/guide extract"
    cards = d.get("cards") or [{"projects": [], "listings": []}]
    assert len(cards[0]["listings"]) + len(cards[0]["projects"]) >= n_min
    if n_min:
        assert t.startswith(("I found", "وجدت", "No Wasalt listing", "لا يوجد في عيّنة")), t


def test_cheapest_first_and_one_price_scale(client, ask):
    d = ask(client, "cheap apartment riyadh")
    ls = d["cards"][0]["listings"]
    assert all(x["listing_type"] == "buy" for x in ls) and "cheapest first" in d["_text"]


def test_place_without_listings_says_so_and_offers_real_alternatives(client, ask):
    d = ask(client, "1-bed to buy in Dubai")
    t = d["_text"]
    assert "none in Dubai" in t and d["trace"][0]["intent"] == "search"
    assert d["chips"][0]


def test_unsatisfiable_filter_relaxes_one_filter_and_says_which(client, ask):
    d = ask(client, "studio for rent in riyadh")
    assert "matches all of that" in d["_text"] or "I found" in d["_text"]


def test_showing_n_equals_listing_sources(client, ask):
    d = ask(client, "2-bed in Riyadh")
    n = len(d["cards"][0]["listings"])
    assert n == len([s for s in d["sources"][0] if "listing" in s["url"]])
    assert d["cards"][0]["total"] >= n


def test_informational_questions_are_not_searches(store):
    for q in ("How does renting work in Jeddah?", "Can foreigners buy property in Riyadh?", "How do Wasalt auctions work?"):
        assert plan(q, store).intent != "search", q
