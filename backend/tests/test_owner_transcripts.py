"""Owner's round-2 live transcripts: buying from abroad (eligibility, adjacent), payment in another currency (honest gap +
sales team + conversion offer), and the related-but-unanswerable family. Never a generic search, never a marketing extract,
never "everyone can buy"."""
import re

import pytest

from backend.app.planner import plan

NO_GENERIC = ("1,255", "According to the published information: What I hold")
FORBIDDEN = re.compile(r"all nationalit|anyone can buy|everyone can buy|you can buy|you can freely|yes[, ]+you can", re.I)
LAST = ["l-1"]

ELIG = ["Can I buy from India too ?", "can i buy from abroad", "I am an Indian national, am I allowed to buy",
        "do you sell to NRIs", "can overseas buyers purchase", "can i buy remotely without visiting"]
PAY = ["Can I make payment in inr", "can i pay in rupees", "do you accept crypto", "what payment methods do you accept",
       "which currencies can I pay in", "can I pay by cheque", "how can i pay"]
NOT_ADJ = ["buy from darglobal", "20% down on 2,000,000 SAR", "monthly payment on 1.5M over 25 years",
           "apartments for sale in Riyadh", "what is the payment plan for aida"]


@pytest.mark.parametrize("msg", ELIG)
def test_eligibility_routes_to_adjacent(store, msg):
    p = plan(msg, store)
    assert p.intent == "adjacent" and p.adjacent_topic == "ownership"


@pytest.mark.parametrize("msg", PAY)
def test_payment_routes_to_adjacent(store, msg):
    p = plan(msg, store)
    assert p.intent == "adjacent" and p.adjacent_topic == "payment"


@pytest.mark.parametrize("msg", NOT_ADJ)
def test_unrelated_stays_out_of_adjacent(store, msg):
    assert plan(msg, store).intent != "adjacent"


def test_buy_from_india_after_not_in_india(make_client, ask):
    c = make_client(env={"LLM_MODE": "off"})  # code-built answer: the structure is what is asserted
    hist = [{"role": "user", "content": "Hye"}, {"role": "assistant", "content": "Welcome."},
            {"role": "user", "content": "In India?"}, {"role": "assistant", "content": "We don't have projects in India."}]
    d = ask(c, "Can I buy from India too ?", history=hist)
    t = d["_text"]
    assert d["trace"][0]["intent"] == "adjacent"
    assert not any(x in t for x in NO_GENERIC) and not d.get("cards")
    assert not FORBIDDEN.search(t)
    assert "can't confirm" in t and "differ by country" in t
    assert "international buyers" in t          # the advisor route
    assert re.search(r"Real Estate General Authority|Ministry of Housing", t)  # official bodies per country held
    assert not re.search(r"\d", t)              # no rule, no number
    assert "meanwhile" in t.lower() or "in the meantime" in t.lower()
    labels = [x["label"] for x in d["chips"][0]]
    assert any(x.startswith("Projects in") for x in labels) and any("advisor" in x.lower() for x in labels)
    assert d["sources"][0], "official contact page must be attached"


def test_payment_in_inr_is_an_honest_gap_with_conversion_offer(make_client, ask):
    c = make_client(env={"LLM_MODE": "off"})
    hist = [{"role": "user", "content": "apartments for sale in Riyadh"},
            {"role": "assistant", "content": "I found 104 apartments for sale in Riyadh."}]
    d = ask(c, "Can I make payment in inr", history=hist)
    t = d["_text"]
    assert d["trace"][0]["intent"] == "adjacent"
    assert "aren't published" in t and "INR" in t and "sales team" in t
    assert "Wasalt" in t and "reference rate" in t
    assert not re.search(r"daily|short-term|book now|enjoy|luxur", t, re.I), "no marketing extract"
    assert not FORBIDDEN.search(t) and "yes" not in t.lower().split()[:2]
    labels = [x["label"] for x in d["chips"][0]]
    assert "Show these prices in INR" in labels and any("advisor" in x.lower() for x in labels)
    assert d["sources"][0]


def test_payment_chip_keeps_last_listings_context(make_client, ask):
    """The chip text, with the last cards' ids carried by the client, becomes a conversion of the carried price."""
    c = make_client(env={"LLM_MODE": "off"})
    r = c.post("/api/chat/stream", json={"message": "Show these prices in INR", "last_entities": LAST,
               "history": [{"role": "user", "content": "Can I make payment in inr"},
                           {"role": "assistant", "content": "Payment methods are not published."}]})
    assert r.status_code == 200 and '"intent": "calculation"' in r.text


@pytest.mark.parametrize("msg", ["can i pay in inr", "do you accept cash"])
def test_payment_never_quotes_marketing(client, ask, msg):
    d = ask(client, msg)
    assert d["trace"][0]["intent"] == "adjacent"
    assert not FORBIDDEN.search(d["_text"])
