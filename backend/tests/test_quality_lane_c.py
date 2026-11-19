"""Quality round, Lane C (answering): per-entity fact sheet in the writer prompt, location-sentence repair, the
retrieval relevance floor with a reroute to structured data, and ChatRequest.last_entities validation."""
import pytest

from backend.app.chat import MIN_PROSE_CHARS, Answer, ChatRequest
from backend.app.llm import MockLLM
from backend.app.retrieval import Hit, Retriever

BLOG = dict(id="pg-blog-ejar", site="wasalt", page_type="guide", title="Ejar System Guide (fixture)",
            text="FAKE TEST ROW. Always ensure the rental contract is officially registered in Ejar before you move "
                 "into an apartment. Verify the landlord name on the Ejar portal.", lang="en",
            source_url="https://blog.fixture.invalid/en/ejar-system-guide/")


class Scripted(MockLLM):
    def __init__(self, reply: str):
        super().__init__()
        self.reply = reply

    def _compose(self, messages):
        self.last_messages = messages
        return self.reply


def _with_blog(client):
    """Adds an editorial (blog guide) page chunk to the fixture store and rebuilds the retriever over it."""
    st = client.app.state.store
    if not st.page_by_id(BLOG["id"]):
        st.pages.append(dict(BLOG, scraped_at="2026-11-18T00:00:00Z"))
        st.chunks.append({"id": "c-blog-ejar", "entity_type": "page", "entity_id": BLOG["id"], "site": "wasalt",
                          "lang": "en", "text": BLOG["title"] + ": " + BLOG["text"], "city": None, "country": None,
                          "source_url": BLOG["source_url"], "scraped_at": "2026-11-18T00:00:00Z"})
        if hasattr(st, "allowed_hosts"):
            st.allowed_hosts.add("blog.fixture.invalid")
        if hasattr(st, "_page_by_id"):
            st._page_by_id = None
    eng = client.app.state.engine
    eng.retriever = Retriever(st, embeddings="off")
    return eng


# ---------------------------------------------------------------- 1. fact sheet (FACTS block first)
def test_facts_block_lists_each_entity_from_the_store(client):
    eng = client.app.state.engine
    st = client.app.state.store
    ans = Answer("project_info", context=[{"site": "darglobal", "entity_type": "project", "entity_id": "p-dubai-b",
                                           "text": "Fixture Creek Villas are waterfront villas.", "source_url": None}],
                 projects=[st.project_by_id("p-oman")], listings=[st.listing_by_id("l-3")])
    facts = eng._facts_block(ans)
    lines = facts.splitlines()
    assert lines[0] == "Fixture Oman Heights | Muscat | Oman | 95,000 OMR | 2028 | Under construction"
    assert lines[1] == ("Fixture Creek Villas | Dubai | United Arab Emirates | not published | not published | "
                        "not published")
    assert lines[2].startswith("listing: Fixture 2-bed apartment for rent, Al Rawdah | Al Rawdah, Jeddah | 60,000 SAR")
    assert "for rent" in lines[2] and "2 bedrooms" in lines[2]


def test_facts_block_comes_first_and_its_figures_are_allowed(client):
    eng = client.app.state.engine
    st = client.app.state.store
    ans = Answer("project_info", context=[{"site": "darglobal", "entity_type": "project", "entity_id": "p-oman",
                                           "text": "A seaside community.", "source_url": None}],
                 projects=[st.project_by_id("p-oman")])
    msgs, ctx = eng._build_messages(ans, "tell me about it", "en", [])
    user = msgs[1]["content"]
    assert user.startswith("<facts>\nFixture Oman Heights | Muscat | Oman | 95,000 OMR | 2028")
    assert user.index("<facts>") < user.index("<context>")
    assert "95,000" in ctx and "2028" in ctx  # the allowed-number text includes the fact sheet
    assert "<facts> is the fact sheet" in msgs[0]["content"]


def test_no_facts_block_when_the_answer_names_no_entity(client):
    eng = client.app.state.engine
    msgs, _ = eng._build_messages(Answer("general", context=[{"site": "wasalt", "entity_type": "page",
                                                              "entity_id": "pg-auction", "text": "Auctions.",
                                                              "source_url": None}]), "q", "en", [])
    assert "<facts>" not in msgs[1]["content"]


# ---------------------------------------------------------------- 2. location-sentence repair
def _astera(client):
    st = client.app.state.store
    if not st.project_by_id("dg-the-astera-interiors-by-aston-martin"):
        st.projects.append(dict(id="dg-the-astera-interiors-by-aston-martin", site="DarGlobal",
                                name_en="The Astera, Interiors by Aston Martin", name_ar=None, city="Ras Al Khaimah",
                                country="United Arab Emirates", slug="astera", source_url=None))
        if hasattr(st, "_project_by_id"):
            st._project_by_id = None
    eng = client.app.state.engine
    eng._loc_index = None
    return eng


def test_repair_drops_only_the_wrong_sentence(client):
    eng = _astera(client)
    text = ("The Astera in Oman is a beachfront tower. It has residences and villas with sea views. "
            "Prices are not published, so the sales team can confirm them.")
    kept, ids = eng._repair_locations(text)
    assert ids == ["dg-the-astera-interiors-by-aston-martin"]
    assert "Oman" not in kept and kept.startswith("It has residences and villas") and "sales team" in kept


def test_repair_keeps_a_correct_reply_untouched(client):
    eng = _astera(client)
    text = "The Astera in Ras Al Khaimah is a tower. Handover is 2028."
    assert eng._repair_locations(text) == (text, [])


def test_repair_does_not_split_decimals(client):
    eng = _astera(client)
    kept, ids = eng._repair_locations("Prices start at 2.5 million. The Astera in Oman is lovely. Ask the team.")
    assert ids and kept == "Prices start at 2.5 million. Ask the team."


def test_wrong_location_sentence_is_replaced_by_the_fact_line(make_client, ask):
    reply = ("Fixture Marina Tower is a branded tower in Oman with sea views. It offers studios to two-bedroom "
             "homes, with a published starting price shown below. The sales team can confirm availability for you.")
    c = make_client(llm=Scripted(reply))
    d = ask(c, "Tell me about Fixture Marina Tower")
    t = d["_text"]
    tr = d["trace"][0]
    assert "in Oman" not in t
    assert "It offers studios to two-bedroom homes" in t  # the rest of the writer's reply is kept
    assert "Fixture Marina Tower — Location: Dubai, United Arab Emirates." in t  # the code fact line appended
    assert tr["degraded"] is False and tr["path"] != "template"
    assert any("wrong location" in s for s in tr["steps"])


def test_repair_that_leaves_too_little_falls_back(make_client, ask):
    c = make_client(llm=Scripted("Sure! Fixture Marina Tower in Oman is popular, and you can browse it with me now."))
    d = ask(c, "Tell me about Fixture Marina Tower")
    assert "in Oman" not in d["_text"]
    assert d["trace"][0]["degraded"] is True  # the MIN_PROSE_CHARS fallback still applies
    assert MIN_PROSE_CHARS == 40


# ---------------------------------------------------------------- 3. relevance floor + reroute
def test_gate_floor_rejects_a_blog_best_hit_for_a_property_question(client):
    eng = _with_blog(client)
    r = eng.retriever
    q = "i need an apartment rental registered on ejar"
    hits = r.search(q, top_k=6, demote_index=True)
    assert hits and hits[0].chunk["entity_id"] == BLOG["id"]
    assert r.is_editorial(hits[0].chunk)
    assert r.gate(q, hits)  # unchanged without property intent
    assert not r.gate(q, hits, property_intent=True)  # BM25-only: no cosine to clear the floor


def test_floor_needs_both_cosine_and_coverage(client):
    eng = _with_blog(client)
    r = eng.retriever
    chunk = next(c for c in r.chunks if c["entity_id"] == BLOG["id"])
    q = "ejar registered rental contract"
    assert r.relevance_floor(q, Hit(chunk, 1.0, 5.0, 0.72))
    assert not r.relevance_floor(q, Hit(chunk, 1.0, 5.0, 0.55))  # cosine under 0.6
    assert not r.relevance_floor("ejar penthouse jacuzzi skyline", Hit(chunk, 1.0, 5.0, 0.9))  # coverage under 0.5
    assert not r.relevance_floor(q, Hit(chunk, 1.0, 5.0, None))


def test_non_editorial_pages_are_not_floored(client):
    r = _with_blog(client).retriever
    auction = next(c for c in r.chunks if c["entity_id"] == "pg-auction")
    assert not r.is_editorial(auction)


def test_property_question_failing_the_floor_reroutes_to_listings(client):
    eng = _with_blog(client)
    from backend.app.planner import plan
    q = "i need an apartment rental registered on ejar"
    p = plan(q, client.app.state.store, [], {})
    a = eng._general(q, "en", [], e=p.entities)
    assert a.intent != "no_data" and a.playbook in ("filtered_search", "superlative", "vague_opener")
    assert not any("blog." in (s.get("url") or "") for s in a.sources)
    assert a.listings or a.projects or a.chips  # never a dead end


def test_superlative_failing_the_floor_reroutes_to_superlative(client):
    eng = _with_blog(client)
    from backend.app.planner import Entities
    e = Entities(property_type="apartment", listing_type="rent")
    a = eng._general("cheapest apartment for rent registered on ejar", "en", [], e=e)
    assert a.playbook == "superlative" and a.listings
    assert not any("blog." in (s.get("url") or "") for s in a.sources)


def test_explanation_question_still_answered_from_the_page(client, ask):
    _with_blog(client)
    d = ask(client, "how do Wasalt auctions work?")
    assert "refundable deposit" in d["_text"]  # not a property-row question: the floor does not apply


# ---------------------------------------------------------------- 4. ChatRequest.last_entities
def test_last_entities_default_and_validation(client):
    assert ChatRequest("s", "hi", []).last_entities == []
    eng = client.app.state.engine
    ids = ["p-oman", "nope", "l-2", "p-oman", 7, "l-1", "l-3", "p-dubai-a", "p-dubai-b"]
    assert eng._valid_last_entities(ids) == ["p-oman", "l-2", "l-1"]  # items past 6 dropped, then unknown/dupes
    assert eng._valid_last_entities(None) == [] and eng._valid_last_entities("p-oman") == []


def test_last_entities_reach_the_planner_flags(client, monkeypatch):
    eng = client.app.state.engine
    seen = {}
    import backend.app.chat as chat_mod
    real = chat_mod.plan

    def fake_plan(text, store, history=None, flags=None, **kw):
        seen["flags"], seen["kw"] = flags, kw
        return real(text, store, history, {})
    monkeypatch.setattr(chat_mod, "plan", fake_plan)
    eng._plan("hi", [], ["p-oman"])
    assert seen["flags"]["last_entities"] == ["p-oman"]


def test_reference_turn_selects_followup_playbook(client):
    """With validated last_entities and a short ordinal follow-up, the selected playbook is followup_reference."""
    eng = client.app.state.engine
    from backend.app.llm import LLMResult
    from backend.app.planner import Entities, Plan
    p = Plan("project_info", Entities(project_ids=["p-dubai-a"]))
    pid = eng._playbook_id(p, "tell me more about the second one", Answer("project_info"), ["p-oman", "p-dubai-a"],
                           LLMResult(), False)
    assert pid == "followup_reference"
    pid = eng._playbook_id(p, "tell me more about the second one", Answer("project_info"), [], LLMResult(), False)
    assert pid == "project_facts"  # no reference context: the plain intent map


def test_listing_reference_answers_that_listing_with_one_card(client):
    """Fix round: "how big is the first one?" over listing cards used to fall to general retrieval (no card, wrong
    entity). It now answers from the row the client pointed at, no model call."""
    st = client.app.state.store
    ids = [x["id"] for x in st.listings[:3]]
    r = client.post("/api/chat/stream", json={"session_id": "t", "message": "tell me abt the frist one", "lang": "en",
                                              "history": [{"role": "user", "content": "apartments for sale"},
                                                          {"role": "assistant", "content": "Here are some."}],
                                              "last_entities": ids})
    assert r.status_code == 200
    body = r.text
    assert ids[0] in body and ids[1] not in body.split("event: cards")[1].split("event: ")[0]
    assert '"llm_calls": 0' in body


def test_chained_place_continuation_keeps_filters():
    """Fix round: "3 bed apartments in Riyadh" -> "what about Jeddah" -> "and Makkah?" stays a search with the type
    and beds kept (it used to degrade to a bare place overview on the second continuation). Real data (skipped
    when the dataset is absent)."""
    import os
    from backend.app.planner import plan
    from backend.app.store import Store
    path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "concierge.sqlite")
    if not os.path.exists(path):
        pytest.skip("real dataset not present")
    st = Store.load(path)
    h = [{"role": "user", "content": "3 bedroom apartments for sale in Riyadh"}, {"role": "assistant", "content": "ok"},
         {"role": "user", "content": "what about Jeddah"}, {"role": "assistant", "content": "ok"}]
    p = plan("and Makkah?", st, h, {})
    assert p.intent == "search" and p.entities.property_type == "apartment" and p.entities.beds == 3
