"""Arithmetic one-liners in words/typos (computed in code, never "not published") and good-humoured banter replies."""
import re

import pytest

from backend.app.conversation import simple_arithmetic
from backend.app.planner import plan

AR = re.compile(r"[؀-ۿ]")
NO_DATA = ("I have no verified information", "not published", "غير منشور", "لا تتوفر لديّ معلومات")

SUMS = [("34 plus sevn is ?", "34 + 7", "41"), ("what's 2+2", "2 + 2", "4"), ("whats 12 minus 5", "12 - 5", "7"),
        ("six times seven", "6 * 7", "42"), ("twelf plus fourty", "12 + 40", "52"), ("20 divided by 4", "20 / 4", "5"),
        ("what is twenty five plus ten", "25 + 10", "35"), ("9 x 9", "9 * 9", "81"), ("100 over 5 is?", "100 / 5", "20"),
        ("ten multiplied by three", "10 * 3", "30"), ("٣٤ زائد ٧", "34 + 7", "41"), ("5 ضرب 5", "5 * 5", "25")]


@pytest.mark.parametrize("msg,expr,res", SUMS)
def test_simple_arithmetic_words(msg, expr, res):
    assert simple_arithmetic(msg) == (expr, res)


@pytest.mark.parametrize("msg", ["2 bed villa in Dubai", "villas under 2m", "20% down on 2,000,000 SAR", "hello",
                                 "one hundred villas please"])
def test_not_arithmetic(msg):
    assert simple_arithmetic(msg) is None


@pytest.mark.parametrize("msg,expr,res", SUMS)
def test_sum_routes_to_off_topic_with_result_first(store, client, ask, msg, expr, res):
    assert plan(msg, store).intent == "off_topic"
    d = ask(client, msg)
    t = d["_text"]
    assert d["trace"][0]["intent"] == "off_topic"
    assert res in t and "not published" not in t and "غير منشور" not in t, t
    assert d["chips"][0]


def test_sum_code_template_has_result_first(make_client, ask):
    d = ask(make_client(env={"LLM_MODE": "off"}), "34 plus sevn is ?")
    assert d["_text"].startswith("34 + 7 = 41."), d["_text"]
    assert any("advisor" in c["label"].lower() for c in d["chips"][0])


BANTER = ["u dont know basic maths ?", "are you dumb", "you're useless", "ur useless", "are you a bot", "are u an AI?",
          "can you even do maths", "why can't you answer", "you suck", "u dont know anything", "worst bot ever",
          "are you human", "r u stupid", "do you even know maths",
          "ما تعرف تحسب؟", "انت غبي", "هل انت روبوت", "لا تعرف الحساب", "هل تجيد الحساب", "انت فاشل", "لماذا لا تجيب"]


@pytest.mark.parametrize("msg", BANTER)
def test_banter_routes_and_replies(store, client, ask, msg):
    assert plan(msg, store).intent == "banter"
    d = ask(client, msg)
    t = d["_text"]
    assert d["trace"][0]["intent"] == "banter"
    assert t.strip() and not any(x in t for x in NO_DATA), t
    assert len(d["chips"][0]) >= 2
    assert not re.search(r"\bI am human\b|I'm human|\bsorry\b.*\bsorry\b", t, re.I)
    if AR.search(msg):
        assert len(AR.findall(t)) > len(re.findall(r"[A-Za-z]", t))


def test_banter_code_fallback_proves_the_sum_from_history(make_client, ask):
    c = make_client(env={"LLM_MODE": "off"})
    hist = [{"role": "user", "content": "34 plus sevn is ?"}, {"role": "assistant", "content": "x"}]
    d = ask(c, "u dont know basic maths ?", history=hist)
    t = d["_text"]
    assert "34 + 7 = 41" in t and "AI property concierge" in t and "human" not in t.replace("AI property", "")
    labels = [x["label"] for x in d["chips"][0]]
    assert any("advisor" in x.lower() for x in labels) and "Compare two projects" in labels or any("Compare" in x for x in labels)


def test_banter_ar_fallback(make_client, ask):
    d = ask(make_client(env={"LLM_MODE": "off"}), "انت غبي")
    assert "مساعد عقاري بالذكاء الاصطناعي" in d["_text"]


def test_property_questions_not_banter(store):
    for m in ["you dont know Fixture Marina Tower?", "villas in Dubai", "what can you do?", "who are you"]:
        assert plan(m, store).intent != "banter"


def test_number_check_still_strict_for_property_facts(client, ask):
    d = ask(client, "tell me about Fixture Marina Tower")
    assert d["trace"][0]["intent"] == "project_info"
