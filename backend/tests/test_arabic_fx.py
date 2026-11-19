"""Arabic bidi isolates, Arabic project-name compare, USD budgets, and currency conversion (peg + ECB, mocked)."""
import asyncio
import os
import re

import pytest

from backend.app import calculator
from backend.app.bidi import FSI, PDI, isolate_latin
from backend.app.planner import extract_entities, plan

REAL_DB = os.path.join(os.path.dirname(__file__), "..", "..", "data", "concierge.sqlite")
ECB_XML = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
<gesmes:subject>Reference rates</gesmes:subject><Cube><Cube time='2026-11-18'>
<Cube currency='USD' rate='1.0800'/><Cube currency='JPY' rate='160.00'/><Cube currency='GBP' rate='0.8500'/>
<Cube currency='INR' rate='90.0000'/></Cube></Cube></gesmes:Envelope>"""


@pytest.fixture(autouse=True)
def _no_live_rates():
    calculator.clear_live_rates()
    yield
    calculator.clear_live_rates()


@pytest.fixture
def real_client(make_client):
    if not os.path.exists(REAL_DB):
        pytest.skip("no built dataset")
    return make_client(env={"DATA_PATH": REAL_DB, "ANSWER_CACHE_PATH": "no-such-cache.json",
                            "RATE_LIMIT": "1000000/300"})


@pytest.fixture
def real_store():
    if not os.path.exists(REAL_DB):
        pytest.skip("no built dataset")
    from backend.app.store import Store
    return Store.load(REAL_DB)


def outside_isolates(text: str) -> str:
    return re.sub(f"{FSI}[^{PDI}]*{PDI}", " ", text)


# ---------------------------------------------------------------- 1. bidi
def test_isolate_wraps_every_latin_run_and_keeps_arabic_comma_outside():
    s = "لدينا Trump Furnished Residences، Marriott Residences، و The Astera من 1,180,000 USD و 120 m²."
    out = isolate_latin(s)
    for run in ("Trump Furnished Residences", "Marriott Residences", "The Astera", "1,180,000 USD", "120 m²"):
        assert f"{FSI}{run}{PDI}" in out, run
    assert f"{PDI}، {FSI}" in out  # the Arabic comma and its space stay outside the isolates
    assert isolate_latin(out) == out  # idempotent
    assert isolate_latin("Latin only") == "Latin only"  # only Arabic text is touched
    assert isolate_latin("وجدت 12 شقة") == "وجدت 12 شقة"


def test_arabic_oman_answer_has_isolates_around_each_latin_name(real_client, ask):
    d = ask(real_client, "ما المشاريع المتوفرة في عُمان؟")
    t = d["_text"]
    assert d["meta"][0]["lang"] == "ar"
    names = re.findall(f"{FSI}([^{PDI}]+){PDI}", t)
    assert len(names) >= 3, t
    assert all(re.search("[A-Za-z]", n) for n in names)
    assert not re.search(r"[A-Za-z]{2,}", outside_isolates(t)), outside_isolates(t)  # no bare Latin run
    assert f"{PDI}, " not in t and f"{PDI}، " in t  # the Arabic comma separates names, outside the isolates


def test_history_with_isolates_still_resolves_the_project(real_client, ask):
    d1 = ask(real_client, "ما المشاريع المتوفرة في عُمان؟")
    d2 = ask(real_client, "ما سعر Aida؟", history=[{"role": "user", "content": "ما المشاريع المتوفرة في عُمان؟"},
                                                  {"role": "assistant", "content": d1["_text"]}])
    assert d2["trace"][0]["intent"] in ("project_info", "general")


def test_md_renderer_keeps_isolates():
    src = open(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "lib", "md.ts"), encoding="utf-8").read()
    assert not re.search(r"2066|2067|2068|2069|\\p\{C", src), "md.ts must not strip bidi isolates"


# ---------------------------------------------------------------- 2. Arabic compare
@pytest.mark.parametrize("msg", ["قارن بين ترامب تاور جدة ونبتون", "قارن بين ترامب تاور جدة و نبتون",
                                 "ترامب تاور جدة مقابل نبتون", "قارن بين برج ترامب جدة ونبتون",
                                 "Compare Trump Tower Jeddah vs Neptune", "Trump Tower Jeddah vs Neptune"])
def test_compare_two_named_projects_ar_and_en(real_client, real_store, ask, msg):
    assert plan(msg, real_store).intent == "compare"
    d = ask(real_client, msg)
    assert d["trace"][0]["intent"] == "compare"
    cols = d["compare"][0]["columns"]
    assert len(cols) == 2
    assert any("Trump Tower Jeddah" in c["name"] for c in cols) and any("Neptune" in c["name"] for c in cols), cols
    assert not d["_text"].startswith(("Which two", "أي مشروعين"))


@pytest.mark.parametrize("msg,a,b", [
    ("قارن بين ماريوت عايدة ودافنشي", "dg-marriott-residences", "dg-da-vinci-tower-interiors-by-pagani"),
    ("قارن بين دا فينشي وليه فاغ", "dg-da-vinci-tower-interiors-by-pagani", "dg-les-vagues-by-elie-saab"),
    ("قارن بين لي فاغ وذا أستيرا", "dg-les-vagues-by-elie-saab", "dg-the-astera-interiors-by-aston-martin"),
    ("قارن بين تييرا فيفا وذا مولينر", "dg-tierra-viva-design-inspired-by-automobili-lamborghini", "dg-the-mulliner"),
])
def test_arabic_alias_table_matches_names(real_store, msg, a, b):
    p = plan(msg, real_store)
    assert p.intent == "compare" and p.entities.project_ids[:2] == [a, b]


def test_aida_alias_names_the_aida_project(real_store):
    assert extract_entities("ما سعر عايدة", real_store).project_ids == ["dg-aida"]


# ---------------------------------------------------------------- 3. USD budgets
@pytest.mark.parametrize("msg,amount", [("$500k apartment", 500_000), ("$1.2m apartment", 1_200_000),
                                        ("1.5 million dollars apartment", 1_500_000),
                                        ("apartment under $500k", 500_000), ("500k usd apartment", 500_000)])
def test_usd_budget_parsing(store, msg, amount):
    e = extract_entities(msg, store)
    assert e.currency == "USD" and e.budget_max == amount, (e.currency, e.budget_max)
    assert plan(msg, store).intent == "search"


def test_usd_budget_converted_to_sar_at_the_peg_and_said_so(client, ask):
    d = ask(client, "$500k apartment")
    t = d["_text"]
    assert d["trace"][0]["intent"] == "search" and t.startswith("I found")
    assert "3.75" in t and "1,875,000" in t and "USD" in t
    # l-1 is 1,200,000 SAR (<= 1,875,000 SAR) so the converted budget keeps it
    assert d["cards"][0]["listings"]
    assert all(x["price"]["currency"] == "SAR" and x["price"]["amount"] <= 1_875_000 for x in d["cards"][0]["listings"])


def test_usd_budget_below_every_listing_returns_nothing_cheap(client, ask):
    d = ask(client, "$100k apartment")  # 375,000 SAR: below the cheapest fixture listing
    assert d["_text"].startswith("No Wasalt listing") and "375,000 SAR" in d["_text"]  # relaxed, and says so


# ---------------------------------------------------------------- 4. currency conversion
def _ecb():
    per_eur, date = calculator.parse_ecb_xml(ECB_XML)
    calculator.set_live_rates(per_eur, date)


def test_ecb_xml_parsing_and_cross_via_usd():
    per_eur, date = calculator.parse_ecb_xml(ECB_XML)
    assert date == "2026-11-18" and per_eur["USD"] == 1.08
    calculator.set_live_rates(per_eur, date)
    assert calculator.rate_per_usd("EUR")[0] == pytest.approx(1 / 1.08)
    assert calculator.rate_per_usd("GBP")[0] == pytest.approx(0.85 / 1.08)
    assert calculator.rate_per_usd("INR")[0] == pytest.approx(90 / 1.08)
    c = calculator.currency_convert(2_000_000, "SAR", "EUR")
    assert c["result"]["amount"] == pytest.approx(2_000_000 / 3.75 / 1.08, abs=0.01)
    assert "ECB reference rate on 2026-11-18" in c["result"]["rate_basis"]
    assert c["result"]["rate_date"] == "2026-11-18" and "approximate, not financial advice" in c["formula"]
    p = calculator.currency_convert(1_180_000, "SAR", "USD")
    assert p["result"]["amount"] == pytest.approx(314_666.67, abs=0.01) and "official peg (SAMA)" in p["result"]["rate_basis"]
    assert "approximate, not financial advice" in p["formula"]


def test_ecb_xml_rejects_dtd():
    with pytest.raises(ValueError):
        calculator.parse_ecb_xml('<!DOCTYPE x [<!ENTITY a "b">]>' + ECB_XML)


def test_refresh_uses_mocked_fetch_and_keeps_cache_on_failure(monkeypatch):
    async def ok():
        return ECB_XML

    async def boom():
        raise OSError("no network in tests")

    monkeypatch.setattr(calculator, "_fetch_ecb_xml", ok)
    assert asyncio.run(calculator.refresh_live_rates()) is True and calculator.live_rates_date() == "2026-11-18"
    monkeypatch.setattr(calculator, "_fetch_ecb_xml", boom)
    assert asyncio.run(calculator.refresh_live_rates()) is False
    assert calculator.live_rates_date() == "2026-11-18"  # stale cache kept, never cleared by a failed refresh


def test_background_loop_never_blocks_a_request(monkeypatch):
    started = []

    async def slow():
        started.append(1)
        await asyncio.sleep(3600)
        return ECB_XML

    monkeypatch.setattr(calculator, "_fetch_ecb_xml", slow)

    async def run():
        t = asyncio.create_task(calculator.fx_refresh_loop())
        await asyncio.sleep(0.05)
        # the fetch is in flight but a pegged conversion answers immediately
        r = calculator.currency_convert(1_000, "AED", "USD")
        t.cancel()
        return r

    assert asyncio.run(run())["result"]["amount"] == pytest.approx(272.29, abs=0.01) and started


def test_convert_sar_to_eur_en_shows_rate_source_and_disclaimer(client, ask):
    _ecb()
    d = ask(client, "convert 2,000,000 SAR to EUR")
    c = d["calc"][0]
    assert c["kind"] == "currency_convert" and c["inputs"] == {"amount": 2_000_000.0, "from": "SAR", "to": "EUR"}
    assert c["result"]["amount"] == pytest.approx(2_000_000 / 3.75 / 1.08, abs=0.01)
    assert "ECB reference rate on 2026-11-18" in d["_text"] and "approximate, not financial advice" in d["_text"].lower() \
        or "Approximate, not financial advice" in d["_text"]
    assert "1 SAR =" in c["formula"]


def test_convert_2m_aed_to_gbp(client, ask):
    _ecb()
    c = ask(client, "convert 2M AED to GBP")["calc"][0]
    assert c["inputs"]["to"] == "GBP" and c["result"]["amount"] == pytest.approx(2_000_000 / 3.6725 * 0.85 / 1.08, abs=0.01)


def test_how_much_is_x_sar_in_dollars_uses_the_peg(client, ask):
    d = ask(client, "how much is 1,180,000 SAR in dollars")
    c = d["calc"][0]
    assert c["result"]["currency"] == "USD" and c["result"]["amount"] == pytest.approx(314_666.67, abs=0.01)
    assert "official peg (SAMA)" in d["_text"] and "approximate" in d["_text"].lower()


@pytest.mark.parametrize("q,cur", [("how much is that in dollars?", "USD"), ("in USD?", "USD"),
                                   ("and in euros?", "EUR"), ("how much is that in pounds", "GBP"),
                                   ("what is that in rupees", "INR")])
def test_follow_up_uses_last_price_in_conversation(client, ask, q, cur):
    _ecb()
    hist = [{"role": "user", "content": "2-bed in Riyadh"},
            {"role": "assistant", "content": "I found 3 apartments. The first is 1,200,000 SAR, the next 1,500,000 SAR."}]
    d = ask(client, q, history=hist)
    c = d["calc"][0]
    assert c["inputs"]["amount"] == 1_500_000.0 and c["inputs"]["from"] == "SAR" and c["inputs"]["to"] == cur
    assert d["trace"][0]["intent"] == "calculation"


@pytest.mark.parametrize("q,cur", [("بالدولار", "USD"), ("كم يساوي ذلك باليورو؟", "EUR"), ("وبالدولار؟", "USD")])
def test_arabic_follow_up_uses_last_price(client, ask, q, cur):
    _ecb()
    hist = [{"role": "assistant", "content": "السعر يبدأ من ⁨1,200,000 ر.س⁩ حسب المنشور."}]
    d = ask(client, q, history=hist)
    c = d["calc"][0]
    assert c["inputs"]["amount"] == 1_200_000.0 and c["inputs"]["from"] == "SAR" and c["inputs"]["to"] == cur
    assert d["meta"][0]["lang"] == "ar" and "تقريبي" in d["_text"]


def test_arabic_convert_phrase(client, ask):
    _ecb()
    c = ask(client, "حول 2 مليون ريال باليورو")["calc"][0]
    assert c["inputs"] == {"amount": 2_000_000.0, "from": "SAR", "to": "EUR"}


def test_unavailable_rate_is_said_honestly_and_pegs_still_work(client, ask):
    d = ask(client, "convert 2,000,000 SAR to EUR")  # no ECB rate cached (feed off in tests)
    assert "calc" not in d and "isn't available right now" in d["_text"] and "EUR" in d["_text"]
    ok = ask(client, "convert 2,000,000 SAR to USD")
    assert ok["calc"][0]["result"]["amount"] == pytest.approx(533_333.33, abs=0.01)
    ar = ask(client, "حول 2 مليون ريال باليورو")
    assert "calc" not in ar and "لا يتوفر الآن" in ar["_text"]


def test_follow_up_with_no_price_in_conversation_asks_for_figures(client, ask):
    d = ask(client, "how much is that in dollars?", history=[{"role": "user", "content": "hello"},
                                                             {"role": "assistant", "content": "Hi!"}])
    assert "calc" not in d


def test_listing_card_has_price_usd_approx_via_peg(client, ask):
    d = ask(client, "2-bed in Riyadh")
    ls = d["cards"][0]["listings"]
    assert ls and all(x["price_usd_approx"] == round(x["price"]["amount"] / 3.75) for x in ls if x["price"])


def test_ascii_comma_inside_a_name_keeps_the_name_in_one_isolate():
    out = isolate_latin("مقارنة بين Trump Tower Jeddah و Neptune, Interiors by Mouawad، Aida.")
    assert f"{FSI}Neptune, Interiors by Mouawad{PDI}\u060c {FSI}Aida{PDI}." in out
