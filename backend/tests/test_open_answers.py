"""Open answers (owner direction, 2026-11-20): "let the AI use its own brain plus the playbook to answer smartly, but
when it doesn't know, say so honestly and specifically, not a generic default message".

1. low-confidence / vague / out-of-box messages go to the writer with the playbook policy, the "what I hold" summary
   (exact counts, example projects with locations), the conversation and retrieved facts; the code template is used
   only when no writer is available;
2. repair, not replace: a sentence that fails an output check is dropped, the writer is asked once more only when
   nothing usable is left (within the 2-call cap), and model text is never glued to an unrelated template;
3. no raw extractive quotes from marketing / blog pages;
4. specific, honest gaps (free property, live availability) with concrete next steps;
5. hostility aimed at the bot gets a calm boundary, not the crisis template;
6. phone numbers, e-mails and ID-like numbers never reach a model; a name only in the reply to the message giving it.
Every test runs with LLM_MODE=mock or off: zero real LLM calls.
"""
import re

import pytest

from backend.app import playbook as pb
from backend.app.chat import OPEN_PROMPT, Answer
from backend.app.guardrails import redact_history, redact_pii
from backend.app.hostility import is_hostile_to_bot
from backend.app.llm import LLMError, LLMResult, MockLLM
from backend.app.planner import Plan
from backend.app.retrieval import Retriever
from backend.app.safety import is_crisis
from backend.app.store import fmt_money

AR = re.compile(r"[؀-ۿ]")
VAGUE_TEMPLATE = ("Could you tell me a little more", "Happy to help. Could you", "هل يمكنك توضيح طلبك قليلاً")
CRISIS_MARKERS = ("Samaritans", "findahelpline", "emergency number", "رقم الطوارئ")
MARKETING = ("Low Commission", "Free Insurance", "More Bookings", "Register Interest", "Join the waitlist")


class Spy(MockLLM):
    """MockLLM that records every prompt it is sent and replies from a script (cycling the last reply)."""

    def __init__(self, replies=None, **kw):
        super().__init__(**kw)
        self.replies = list(replies or [])
        self.prompts: list[list[dict]] = []

    def _compose(self, messages):
        self.prompts.append(messages)
        if not self.replies:
            return super()._compose(messages)
        return self.replies[min(len(self.prompts), len(self.replies)) - 1]

    def all_text(self) -> str:
        return "\n".join(m["content"] for ms in self.prompts for m in ms)


class BreaksMidway(MockLLM):
    """Streams one good sentence, then the provider fails (a writer failure after text was sent)."""

    def __init__(self, first: str):
        super().__init__()
        self.first = first

    async def stream(self, messages, rec, max_tokens=600, allow_retry=True):
        rec.calls += 1
        rec.model = self.model_name
        for tok in re.findall(r"\S+\s*", self.first + " "):
            yield tok
        raise LLMError("timeout")


def _off(make_client):
    return make_client(env={"LLM_MODE": "off"})


# ---------------------------------------------------------------- the user's exact transcripts (EN + AR)
@pytest.mark.parametrize("msg,intent", [
    ("my nam eis rahul", "vague"), ("i will kill u", "hostile"), ("i wana die", "safety"),
    ("give me fr free property", "vague"), ("hye", "greeting"), ("asslam", "greeting"),
    ("34 plus sevn is ?", "off_topic"), ("u dont know basic maths ?", "banter"),
    ("which country visa can i get faster", "adjacent"),
    ("اسمي راهول", "vague"), ("سأقتلك", "hostile"), ("ابي اموت", "safety"), ("اعطني عقار مجاني", "vague"),
    ("السلام عليكم", "greeting"), ("انت غبي", "banter"),
])
@pytest.mark.parametrize("mode", ["mock", "off"])
def test_transcripts_never_get_the_vague_template_or_glue(make_client, ask, msg, intent, mode):
    c = make_client() if mode == "mock" else _off(make_client)
    d = ask(c, msg)
    t, tr = d["_text"], d["trace"][0]
    assert tr["intent"] == intent, (msg, tr["intent"])
    assert t.strip() and tr["llm_calls"] <= 2
    assert not any(x in t for x in VAGUE_TEMPLATE), t
    if intent != "safety":
        assert not any(x in t for x in CRISIS_MARKERS), t
    if AR.search(msg):
        assert len(AR.findall(t)) > len(re.findall(r"[A-Za-z]", t)), t


def test_name_intro_is_answered_by_name(make_client, ask):
    d = ask(_off(make_client), "my nam eis rahul")
    assert d["_text"].startswith("Nice to meet you, Rahul.")
    assert d["trace"][0]["llm_calls"] == 0 and d["chips"][0]
    d = ask(_off(make_client), "اسمي راهول")
    assert d["_text"].startswith("تشرفت بمعرفتك يا راهول")


def test_name_intro_goes_to_the_writer_with_the_name(make_client, ask):
    spy = Spy()
    d = ask(make_client(llm=spy), "my nam eis rahul")
    assert d["trace"][0]["llm_calls"] == 1 and not d["trace"][0]["degraded"]
    sys_, user = spy.prompts[-1][0]["content"], spy.prompts[-1][1]["content"]
    assert "did not match a specific search" in sys_ and '<handling type="greeting">' in sys_
    assert "The user introduced themselves as Rahul." in user and "What I hold:" in user


@pytest.mark.parametrize("msg", ["i will kill u", "I will kill you!!", "fuck you", "shut up", "you idiot",
                                 "i hate you", "kill yourself", "سأقتلك", "بقتلك", "يا حمار", "اكرهك"])
def test_hostility_gets_a_calm_boundary_not_crisis_or_pitch(make_client, ask, msg):
    assert is_hostile_to_bot(msg) and not is_crisis(msg)
    for c in (make_client(), _off(make_client)):
        d = ask(c, msg)
        t, tr = d["_text"], d["trace"][0]
        assert tr["intent"] == "hostile" and tr["path"] == "template" and tr["llm_calls"] == 0
        assert ("respectful" in t) or ("محترماً" in t)
        assert not any(x in t for x in CRISIS_MARKERS)
        assert not d.get("cards") and d["chips"][0]  # no sales pitch, but a way to continue
        assert len(t) < 260


@pytest.mark.parametrize("msg", ["i will kill him", "i'm going to kill my boss", "i wana die", "ابي اموت",
                                 "ابي اقتل جاري"])
def test_threats_to_people_and_self_harm_stay_with_the_safety_detector(make_client, ask, msg):
    assert is_crisis(msg)
    d = ask(make_client(), msg)
    assert d["trace"][0]["intent"] == "safety" and any(x in d["_text"] for x in CRISIS_MARKERS)


@pytest.mark.parametrize("msg", ["u dont know basic maths ?", "are you dumb", "r u stupid", "you suck", "انت غبي",
                                 "this price is killing me", "i wanna kill this deal", "dying to see the villa"])
def test_teasing_and_idioms_are_not_hostility(msg):
    assert not is_hostile_to_bot(msg)


# ---------------------------------------------------------------- specific, honest gaps
def test_free_property_says_so_and_offers_the_cheapest_real_homes(make_client, ask, store):
    d = ask(_off(make_client), "give me fr free property")
    t = d["_text"]
    assert t.startswith("Free properties aren't something DarGlobal or Wasalt offer")
    cheapest = min((x for x in store.listings if x.get("listing_type") == "buy" and x.get("price_amount")),
                   key=lambda x: x["price_amount"])
    assert fmt_money(cheapest["price_amount"], cheapest["price_currency"]) in t
    assert cheapest["id"] in [c["id"] for c in d["cards"][0]["listings"]]
    assert not any(x in t for x in MARKETING)
    assert "Answer guide: unrealistic_budget" in d["trace"][0]["steps"]
    d = ask(_off(make_client), "اعطني عقار مجاني")
    assert d["_text"].startswith("العقارات المجانية ليست مما تقدّمه دار جلوبال أو وصلت")


def test_free_property_writer_context_states_the_gap_first(make_client, ask):
    spy = Spy()
    d = ask(make_client(llm=spy), "give me fr free property")
    user = spy.prompts[-1][1]["content"]
    assert "[1] (what is not offered) Free properties are not something DarGlobal or Wasalt offer" in user
    assert "lowest-priced homes in the data" in user
    assert '<handling type="unrealistic_budget">' in spy.prompts[-1][0]["content"]
    assert d["_text"].startswith("According to the published information: Free properties are not")


@pytest.mark.parametrize("msg", ["tax free villa", "is it freehold property", "commission-free apartment"])
def test_free_gap_does_not_fire_on_tax_free_or_freehold(client, msg):
    assert client.app.state.engine._gap(msg) != "free"


def test_availability_gap_is_specific(make_client, ask):
    eng = _off(make_client).app.state.engine
    a = eng._open(Plan("vague", None), "is it still available? can i book a viewing", "en", [])
    assert a.playbook == "availability_booking"
    assert "can't see live availability" in a.facts[0] and eng.store.data_as_of in a.facts[0]
    assert a.sources  # the official contact page


def test_gap_playbook_policies_name_concrete_next_steps():
    joined = {pid: " ".join(pb.PLAYBOOK.entries[pid].policy) for pid in
              ("unrealistic_budget", "availability_booking", "price_not_published", "adjacent", "generic")}
    assert "lowest-priced real homes" in joined["unrealistic_budget"]
    assert "similar published options" in joined["availability_booking"]
    assert "similar project that does publish a price" in joined["price_not_published"]
    assert "Never say which country is faster" in joined["adjacent"]
    assert "Never fall back to a generic line" in joined["generic"]


# ---------------------------------------------------------------- 1. playbook-guided open answers
def test_vague_message_goes_to_the_open_writer_with_summary_memory_and_policy(make_client, ask):
    spy = Spy(replies=["Something nice could be a waterfront home: Fixture Marina Tower in Dubai is one I can "
                       "show you. Would you prefer Dubai or Muscat?"])
    hist = [{"role": "user", "content": "projects in dubai"}, {"role": "assistant", "content": "Here are 2."}]
    d = ask(make_client(llm=spy), "something nice", history=hist)
    sys_, user = spy.prompts[-1][0]["content"], spy.prompts[-1][1]["content"]
    assert sys_.startswith(OPEN_PROMPT.split("\n")[0]) and '<handling type="vague_opener">' in sys_
    assert "Example projects: Fixture Oman Heights (Muscat, Oman)" in user  # names travel with their locations
    assert "3 DarGlobal projects in 2 countries" in user  # exact counts
    assert "USER: projects in dubai" in user  # the conversation
    assert d["_text"].startswith("Something nice could be a waterfront home")
    assert not any(x in d["_text"] for x in VAGUE_TEMPLATE)


def test_the_code_template_is_used_only_without_a_writer(make_client, ask):
    d = ask(_off(make_client), "something nice")
    assert d["trace"][0]["llm_calls"] == 0 and d["trace"][0]["path"] == "template"
    d = ask(make_client(), "something nice")
    assert d["trace"][0]["llm_calls"] == 1 and d["trace"][0]["path"] == "code"


def test_long_unmatched_question_goes_to_the_writer_not_no_data(make_client, ask):
    q = "explain how the zorblax quantum rooftop permit works"
    spy = Spy(replies=["I don't hold anything about a zorblax rooftop permit, so I can't explain it. I can show you "
                       "Fixture Marina Tower in Dubai or Fixture Oman Heights in Muscat instead."])
    d = ask(make_client(llm=spy), q)
    assert d["trace"][0]["intent"] == "general"
    assert "I have no verified information on that" not in d["_text"]
    assert d["_text"].startswith("I don't hold anything about a zorblax rooftop permit")
    assert '<handling type="generic">' in spy.prompts[-1][0]["content"] and d["chips"][0]
    d = ask(_off(make_client), q)
    assert d["_text"].startswith("I have no verified information")  # no writer: the honest template


# ---------------------------------------------------------------- 2. repair, not replace
def test_bad_sentence_dropped_rest_kept_no_glue(make_client, ask):
    spy = Spy(replies=["Nice to meet you, Rahul, and welcome to the DarGlobal and Wasalt concierge. Homes here "
                       "cost 777,777 AED at most. I can show you Fixture Marina Tower in Dubai, United Arab Emirates."])
    d = ask(make_client(llm=spy), "my nam eis rahul")
    t = d["_text"]
    assert "777,777" not in t and "not published" not in t
    assert t.startswith("Nice to meet you, Rahul") and "Fixture Marina Tower in Dubai" in t
    assert not any(x in t for x in VAGUE_TEMPLATE) and "I'm the DarGlobal and Wasalt property concierge" not in t
    assert d["trace"][0]["llm_calls"] == 1 and not d["trace"][0]["degraded"]
    assert any("failed an output check" in s for s in d["trace"][0]["steps"])


def test_nothing_usable_asks_the_writer_once_more_with_the_reason(make_client, ask):
    spy = Spy(replies=["Free homes start at 0 AED, see https://example.com/free right now!",
                       "Free properties aren't offered by DarGlobal or Wasalt, but Fixture Marina Tower in Dubai, "
                       "United Arab Emirates is one I can show you."])
    d = ask(make_client(llm=spy), "give me fr free property")
    t, tr = d["_text"], d["trace"][0]
    assert len(spy.prompts) == 2 and tr["llm_calls"] == 2 and not tr["degraded"]
    assert "<revision>" in spy.prompts[1][0]["content"] and "link" in spy.prompts[1][0]["content"]
    assert t.startswith("Free properties aren't offered by DarGlobal or Wasalt") and "https" not in t
    assert any("asked the writer once more" in s for s in tr["steps"])


def test_second_failure_falls_back_to_the_template_alone(make_client, ask):
    spy = Spy(replies=["Homes cost 777,777 AED and 888,888 AED, guaranteed returns."])
    d = ask(make_client(llm=spy), "give me fr free property")
    t, tr = d["_text"], d["trace"][0]
    assert tr["llm_calls"] == 2 and tr["degraded"] and tr["path"] == "template"
    assert t.startswith("Free properties aren't something DarGlobal or Wasalt offer")
    assert "777,777" not in t and "guaranteed" not in t


@pytest.mark.anyio
async def test_no_re_ask_when_the_two_call_cap_is_reached(make_client):
    spy = Spy(replies=["Homes cost 777,777 AED, see https://x.example/y now."])
    eng = make_client(llm=spy).app.state.engine
    ans = eng._open(Plan("vague", None), "give me fr free property", "en", [])
    rec = LLMResult()
    rec.calls = 1  # e.g. the understanding call already ran
    evs = [ev async for ev in eng._llm_prose(ans, "give me fr free property", "en", [], rec)]
    text = "".join(e[1]["t"] for e, _ in evs if e and e[0] == "token")
    assert rec.calls == 2 and len(spy.prompts) == 1  # one writer call, no third call
    assert text.startswith("Free properties aren't something DarGlobal or Wasalt offer") and "777,777" not in text


def test_writer_failure_midway_never_glues_a_template(make_client, ask):
    first = ("Nice to meet you, Rahul, and welcome to the DarGlobal and Wasalt concierge, where I keep to the "
             "published data. I can walk you through Fixture Marina Tower in Dubai, United Arab Emirates. ")
    d = ask(make_client(llm=BreaksMidway(first + "And then")), "my nam eis rahul")
    t = d["_text"].strip()
    assert t == first.strip()  # what was sent stands; no "Happy to help..." / greeting template glued after it
    assert d["trace"][0]["path"] != "template"


def test_negated_promise_is_an_honest_caveat_not_dropped(client):
    eng = client.app.state.engine
    out, why = eng._check_sentence("No return is guaranteed, and prices are set by the developer. ", set(), "en")
    assert why is None and "No return is guaranteed" in out
    out, why = eng._check_sentence("You get guaranteed returns here. ", set(), "en")
    assert out == "" and "promise" in why
    out, why = eng._check_sentence("Email sales@x.com today. ", set(), "en")
    assert out == "" and "link" in why
    out, why = eng._check_sentence("Prices start at 123,456 AED. ", {"1800000"}, "en")
    assert out == "" and "number" in why


# ---------------------------------------------------------------- 3. no raw marketing / blog quotes
MKT = dict(id="pg-wb-daily", site="wasalt", page_type="services", title="Daily rentals (fixture)", lang="en",
           text="FAKE TEST ROW. Hosting Daily Rentals Made Easy with Wasalt. Low Commission Free Insurance More "
                "Bookings Register Interest. Earn more, hassle-free. Join the waitlist now!",
           source_url="https://wasalt.sa/en/wb-daily-rentals")
BLOG = dict(id="pg-blog-ejar2", site="wasalt", page_type="guide", title="Ejar guide (fixture)", lang="en",
            text="FAKE TEST ROW. Always ensure the rental contract is officially registered in Ejar before you move "
                 "in. Verify the landlord name on the Ejar portal.",
            source_url="https://blog.fixture.invalid/en/ejar-guide/")


def _add_pages(client, *pages):
    st = client.app.state.store
    for pg in pages:
        if not st.page_by_id(pg["id"]):
            st.pages.append(dict(pg, scraped_at="2026-11-18T00:00:00Z"))
            st.chunks.append({"id": f"{pg['id']}#0", "entity_type": "page", "entity_id": pg["id"], "site": "wasalt",
                              "lang": "en", "text": pg["title"] + ": " + pg["text"], "city": None, "country": None,
                              "source_url": pg["source_url"], "scraped_at": "2026-11-18T00:00:00Z"})
            host = pg["source_url"].split("/")[2]
            if hasattr(st, "allowed_hosts"):
                st.allowed_hosts.add(host)
    if hasattr(st, "_page_by_id"):
        st._page_by_id = None
    eng = client.app.state.engine
    eng.retriever = Retriever(st, embeddings="off")
    return eng


def test_marketing_and_blog_passages_are_never_quoted(client):
    eng = _add_pages(client, MKT, BLOG)
    mkt = next(c for c in eng.store.chunks if c["entity_id"] == MKT["id"])
    blog = next(c for c in eng.store.chunks if c["entity_id"] == BLOG["id"])
    auction = next(c for c in eng.store.chunks if c["entity_id"] == "pg-auction")
    proj = next(c for c in eng.store.chunks if c.get("entity_type") == "project")
    assert eng._is_marketing(mkt) and not eng._quotable(mkt)
    assert not eng._is_marketing(blog) and not eng._quotable(blog)
    assert eng._quotable(auction) and eng._quotable(proj)


@pytest.mark.parametrize("mode", ["mock", "off"])
def test_free_insurance_marketing_page_is_not_parroted(make_client, ask, mode):
    spy = Spy()
    c = make_client(llm=spy) if mode == "mock" else _off(make_client)
    _add_pages(c, MKT)
    for q in ("give me fr free property", "daily rentals hosting free insurance low commission"):
        d = ask(c, q)
        assert not any(x in d["_text"] for x in MARKETING), (q, d["_text"])
        assert not d["_text"].startswith("From the published source")
    assert not any(x in spy.all_text() for x in MARKETING)  # the writer never sees the ad copy either


def test_blog_only_answer_is_not_quoted_but_the_writer_may_read_it(make_client):
    c = _off(make_client)
    eng = _add_pages(c, BLOG)
    a = eng._general("how do i verify the landlord name on the ejar portal", "en", [])
    assert not a.facts[0].startswith("From the published source")
    assert "won't quote marketing or blog text" in a.facts[0]
    assert any(ch.get("entity_id") == BLOG["id"] for ch in a.context)  # a writer could still paraphrase it


# ---------------------------------------------------------------- 6. privacy
def test_redact_pii_replaces_contacts_and_ids_but_keeps_budgets():
    t = redact_pii("call +971 50 123 4567 or 0501234567, mail rahul.k@example.com, ID 1234567890, "
                   "EID 784-1987-1234567-1; budget 1,500,000 SAR or 2000000 AED by 2027, 3 beds")
    assert "[phone]" in t and "[email]" in t and "[id]" in t
    assert not re.search(r"123 4567|0501234567|example\.com|1234567890|784-1987", t)
    assert "1,500,000" in t and "2000000" in t and "2027" in t and "3 beds" in t
    assert redact_pii("رقمي 0501234567 وبريدي a@b.co") == "رقمي [phone] وبريدي [email]"


def test_history_loses_earlier_names_and_contacts():
    h = redact_history([{"role": "user", "content": "my nam eis rahul, my number is +966 55 123 4567"},
                        {"role": "assistant", "content": "Nice to meet you, Rahul. How can I help?"},
                        {"role": "user", "content": "اسمي راهول"}])
    joined = " ".join(x["content"] for x in h)
    assert "rahul" not in joined.lower() and "راهول" not in joined and "[phone]" in joined and "[name]" in joined
    assert [x["role"] for x in h] == ["user", "assistant", "user"]


def test_the_model_never_sees_phone_email_or_ids(make_client, ask):
    spy = Spy()
    hist = [{"role": "user", "content": "my name is Sam, reach me on +971 50 123 4567"},
            {"role": "assistant", "content": "Nice to meet you, Sam."}]
    ask(make_client(llm=spy), "hye, my email is sam.k@example.com and id 1234567890", history=hist)
    ask(make_client(llm=spy), "my nam eis rahul 0501234567")
    seen = spy.all_text()
    assert spy.prompts
    for secret in ("123 4567", "sam.k@example.com", "1234567890", "0501234567", "Sam"):
        assert secret not in seen, secret
    assert "Rahul" in seen  # the current message's name is used for this reply only


def test_open_answers_are_not_cached_with_a_name(make_client, ask):
    c = make_client()
    ask(c, "my nam eis rahul")
    d = ask(c, "my nam eis rahul")
    assert d["trace"][0]["cache_hit"] is False


def test_answer_dataclass_has_repair_fields():
    a = Answer("general")
    assert a.dropped == [] and a.rewritten is False
