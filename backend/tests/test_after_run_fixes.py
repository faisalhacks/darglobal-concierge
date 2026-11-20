"""Fix round after the persona and 30-conversation after-runs (20 Nov 2026).

Pins: a budget with a place is a search even with a relocation word; "what countries do you cover" is the country
overview; Spanish "España"/"proyectos"; the code-built off-topic/banter pivot never quotes a project's marketing
description; the demo sum is only offered when the teasing is about maths; a listing title keeps its size inside
one bidi isolate."""
import pytest

from backend.app.bidi import FSI, PDI, isolate_latin
from backend.app.planner import extract_budget, plan
from backend.app.arabic import normalize_text


def test_budget_around_is_a_budget():
    assert extract_budget(normalize_text("Budget around 2 million SAR"))[1] == 2_000_000


@pytest.mark.parametrize("msg", ["what countries do you cover?", "which countries have the most?",
                                 "how many countries are you in"])
def test_country_questions_are_overview(store, msg):
    assert plan(msg, store).intent == "location_overview"


def test_spanish_country_alias(store):
    p = plan("Hola, que proyectos tienen en España?", store)
    assert "Spain" in (p.entities.country, p.entities.place) and p.intent == "location_overview"


def _off_topic_text(make_client, ask, msg):
    return ask(make_client(env={"LLM_MODE": "off"}), msg, lang="en")["_text"]


@pytest.mark.parametrize("msg", ["write me a python function to reverse a string", "now tell me a joke"])
def test_off_topic_pivot_is_code_built_not_quoted(store, make_client, ask, msg):
    t = _off_topic_text(make_client, ask, msg)
    descs = [p.get("description_en") or "" for p in store.projects]
    first = [d.split(". ")[0] for d in descs if len(d.split()) >= 12]
    assert not any(f and f in t for f in first), t
    assert "DarGlobal project" in t or "outside my world" in t, t


def test_plain_insult_gets_no_demo_sum(make_client, ask):
    t = _off_topic_text(make_client, ask, "you are a useless stupid bot")
    assert "2 + 2" not in t, t


def test_maths_teasing_keeps_demo_sum(make_client, ask):
    t = _off_topic_text(make_client, ask, "can you even do maths?")
    assert "2 + 2 = 4" in t, t


def test_listing_title_size_stays_in_one_isolate():
    out = isolate_latin("أغلى فيلا هو Villa 1189.54 SQM Facing 3 Streets في الرياض")
    assert f"{FSI}Villa 1189.54 SQM Facing 3 Streets{PDI}" in out, repr(out)
