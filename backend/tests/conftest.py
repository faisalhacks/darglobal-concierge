import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

FIXTURE = os.path.join(HERE, "fixtures", "test.sqlite")
STATIC = os.path.join(HERE, "fixtures", "static")

# PROJECT_ANSWER=llm keeps the writer-path tests (they ask about a project) on the model path; the council-17
# code-built project answer (production default) is tested with PROJECT_ANSWER=code explicitly.
os.environ.update({"PROJECT_ANSWER": "llm", "LLM_MODE": "mock", "EMBEDDINGS": "off", "FX_FETCH": "off", "DATA_PATH": FIXTURE, "STATIC_DIR": STATIC,
                   "INDEX_DIR": os.path.join(HERE, "fixtures", "no-index")})
for k in ("OPENROUTER_API_KEY", "MAINTENANCE_MODE", "MOCK_LLM_FAIL", "CANDIDATE_NAME", "CANDIDATE_GITHUB",
          "CANDIDATE_LINKEDIN", "CANDIDATE_EMAIL"):
    os.environ.pop(k, None)

import make_fixture  # noqa: E402

make_fixture.build(FIXTURE)
os.makedirs(STATIC, exist_ok=True)
for name, body in (("index.html", "<!doctype html><title>home</title>HOME"),
                   ("how-it-works.html", "<!doctype html><title>how</title>HOW"),
                   ("404.html", "<!doctype html><title>404</title>NOTFOUND")):
    with open(os.path.join(STATIC, name), "w", encoding="utf-8") as f:
        f.write(body)

from fastapi.testclient import TestClient  # noqa: E402

from backend.app.config import load_settings  # noqa: E402
from backend.app.llm import MockLLM  # noqa: E402
from backend.app.main import create_app  # noqa: E402


def parse_sse(text: str) -> list[tuple[str, dict]]:
    out = []
    for frame in text.split("\n\n"):
        frame = frame.strip()
        if not frame:
            continue
        ev = data = None
        for line in frame.split("\n"):
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        out.append((ev, data))
    return out


@pytest.fixture
def make_client():
    def _make(llm=None, env: dict | None = None):
        old = {}
        for k, v in (env or {}).items():
            old[k] = os.environ.get(k)
            os.environ[k] = v
        try:
            s = load_settings()
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        app = create_app(s, llm=llm if llm is not None else (MockLLM() if s.llm_mode == "mock" else None))
        return TestClient(app)
    return _make


@pytest.fixture
def client(make_client):
    return make_client()


@pytest.fixture
def ask():
    def _ask(client, message, history=None, lang="auto"):
        r = client.post("/api/chat/stream", json={"session_id": "t", "message": message,
                                                  "history": history or [], "lang": lang})
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("text/event-stream")
        evs = parse_sse(r.text)
        d = {}
        for e, data in evs:
            d.setdefault(e, []).append(data)
        d["_order"] = [e for e, _ in evs]
        d["_text"] = "".join(x["t"] for x in d.get("token", []))
        return d
    return _ask


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def store():
    from backend.app.store import Store
    return Store.load(FIXTURE)
