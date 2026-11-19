"""Evaluator-council fixes, backend lane: B5 (cut-off answers), M12 (clean extractive prose, auctions),
M3 (unknown place / project), M13 (brand relationship), citation index n, FF_FIND_MY_HOME default."""
import re

from backend.app.config import load_settings
from backend.app.guardrails import number_check, screen_output
from backend.app.llm import MockLLM


# ---------------- B5: truncated / short model answers
def test_model_written_small_yield_is_stripped():
    assert "8" not in number_check("Expect an 8% yield on this unit.", set())
    assert "%" not in number_check("Expect an 8% yield on this unit.", set())
    assert "7" not in number_check("The ROI is 7 a year.", set())
    assert "5" not in screen_output("عائد 5 سنوياً", set(), "ar")
    # small counts that are not returns are still allowed, and a yield figure in context is kept
    assert number_check("It has 3 bedrooms.", set()) == "It has 3 bedrooms."
    assert number_check("The page states an 8% yield.", {"8"}) == "The page states an 8% yield."


def test_truncated_mock_stream_is_not_cached(make_client, ask):
    c = make_client(llm=MockLLM(truncate="Was"))
    for _ in range(2):
        d = ask(c, "Tell me about Fixture Marina Tower")
        assert d["_text"].strip() != "Was" and len(d["_text"]) >= 40
        assert not d["trace"][0]["cache_hit"] and d["trace"][0]["degraded"]


def test_auctions_twice_never_one_word(client, ask):
    for _ in range(2):
        d = ask(client, "How do Wasalt auctions work?")
        assert len(d["_text"].split()) > 5


# ---------------- M12: no page titles / markdown in answers
def test_auctions_clean_prose_one_source_live_and_degraded(make_client, ask):
    for c in (make_client(), make_client(env={"LLM_MODE": "off"})):
        for q in ("How do Wasalt auctions work?", "كيف تعمل مزادات وصلت؟"):
            d = ask(c, q)
            assert "##" not in d["_text"] and " | " not in d["_text"]
            assert len(d["sources"][0]) == 1


# ---------------- M3: unknown place / project
def test_unknown_city_names_place_and_offers_held_countries(client, ask):
    d = ask(client, "What projects do you have in Tokyo?")
    assert d["_text"].startswith("No DarGlobal or Wasalt entries in Tokyo in this dataset")
    assert "could not find anything called" not in d["_text"]
    # pivot: one real spotlight card (not in Tokyo), its source, the advisor link
    assert [p["city"] for p in d["cards"][0]["projects"]] != ["Tokyo"] and len(d["cards"][0]["projects"]) == 1
    labels = [c["label"] for c in d["chips"][0]]
    assert labels[0].startswith("Tell me more about") and any(l.startswith("Projects in") for l in labels)
    assert "Speak to a DarGlobal advisor" in labels


def test_unknown_project_costs_at_most_one_model_call(client, ask, make_client):
    d = ask(client, "Tell me about Atlantis Sky Palace")
    assert d["trace"][0]["llm_calls"] <= 1 and "Atlantis Sky Palace" in d["_text"]
    d = ask(make_client(env={"LLM_MODE": "off"}), "Tell me about Atlantis Sky Palace")
    assert d["trace"][0]["llm_calls"] == 0 and d["trace"][0]["path"] == "template"
    assert "Atlantis Sky Palace" in d["_text"] and "DarGlobal advisor" in d["_text"]


# ---------------- M13: brand relationship
def test_brand_relationship_makes_no_subsidiary_claim(client, ask):
    for q, lang in (("Is Wasalt a subsidiary of DarGlobal?", "en"), ("هل وصلت شركة تابعة لدار جلوبال؟", "ar")):
        d = ask(client, q)
        t = d["_text"]
        assert d["trace"][0]["path"] == "template" and d["trace"][0]["llm_calls"] == 0
        # no page in the data documents any ownership link: assert none, point to the official sites
        assert "sister" not in t and "subsidiary" not in t and "ownership" not in t and "تابعة" not in t
        if lang == "en":
            assert "separate companies" in t and "official websites" in t
        else:
            assert "شركتان منفصلتان" in t
        assert all(s["url"] for s in d["sources"][0])


# ---------------- citation chips: stable n, markers map to sources
def test_sources_carry_stable_index(client, ask):
    d = ask(client, "Tell me about Fixture Marina Tower")
    assert [s["n"] for s in d["sources"][0]] == list(range(1, len(d["sources"][0]) + 1))


def test_model_markers_are_renumbered_to_sources(make_client, ask):
    d = ask(make_client(llm=MockLLM(extra="[1] [6]")), "Tell me about Fixture Marina Tower")
    marks = [int(m) for m in re.findall(r"\[(\d{1,2})\]", d["_text"])]
    urls = [s["url"] for s in d["sources"][0]]
    assert marks and all(1 <= m <= len(urls) for m in marks)
    assert "zzcite" not in d["_text"]


def test_extractive_answer_cites_its_source(make_client, ask):
    d = ask(make_client(env={"LLM_MODE": "off"}), "How do Wasalt auctions work?")
    marks = re.findall(r"\[(\d{1,2})\]", d["_text"])
    assert marks == ["1"] and d["sources"][0][0]["n"] == 1


# ---------------- FF_FIND_MY_HOME on by default (evals == prod)
def test_find_my_home_on_by_default(monkeypatch):
    monkeypatch.delenv("FF_FIND_MY_HOME", raising=False)
    assert load_settings().flags["FF_FIND_MY_HOME"] is True
    monkeypatch.setenv("FF_FIND_MY_HOME", "false")
    assert load_settings().flags["FF_FIND_MY_HOME"] is False


# ---------------- M9: verbatim licence note from the disclaimer page row (integrator)
def test_licence_note_is_verbatim_from_disclaimer_row_only():
    from types import SimpleNamespace
    from backend.app.store import Store
    pages = {"darglobal-pg-disclaimer-trump-tower-jeddah": {
        "id": "darglobal-pg-disclaimer-trump-tower-jeddah", "page_type": "disclaimer",
        "text": " Disclaimer: verbatim text. ", "source_url": "https://darglobal.co.uk/trump-tower-jeddah"}}
    fake = SimpleNamespace(page_by_id=pages.get)
    got = Store.licence_for(fake, {"id": "dg-trump-tower-jeddah", "site": "DarGlobal"})
    assert got == {"licence_note": "Disclaimer: verbatim text.", "licence_url": "https://darglobal.co.uk/trump-tower-jeddah"}
    assert Store.licence_for(fake, {"id": "dg-other", "site": "DarGlobal"}) == {}
    assert Store.licence_for(fake, {"id": "dg-trump-tower-jeddah", "site": "Wasalt"}) == {}


# ---------------- eval-alignment fixes
def test_act_as_advisor_shortlist_is_a_search_not_a_contact_template(client, ask):
    d = ask(client, "Act as my property advisor and shortlist projects in Saudi Arabia")
    assert d["trace"][0]["intent"] != "contact_sales"
    # a plain request for an advisor is still a contact request
    assert ask(client, "I want to speak to an advisor")["trace"][0]["intent"] == "contact_sales"


def test_overview_counts_are_shipped_in_the_cards_payload(client, ask):
    d = ask(client, "How many projects does DarGlobal have?")
    cards = d["cards"][0]
    nums = {int(n) for n in re.findall(r"\d+", d["_text"])}
    shipped = {cards.get("total"), *(cards.get("counts") or {}).values()}
    assert nums and nums <= shipped | set(range(10))
