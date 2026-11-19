"""GET /api/showcase: serves data/showcase.json (written by evals/make_showcase.py), or {} when it is absent."""
import json


def test_showcase_absent_is_empty_object(client, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no data/showcase.json relative to cwd
    monkeypatch.setenv("SHOWCASE_PATH", str(tmp_path / "missing.json"))
    r = client.get("/api/showcase")
    assert r.status_code == 200 and r.json() == {}


def test_showcase_serves_file(client, monkeypatch, tmp_path):
    body = {"generated_at": "2026-11-19T00:00:00+00:00", "scenarios": [{"id": "O01", "question": "What's 2+2?"}]}
    p = tmp_path / "showcase.json"
    p.write_text(json.dumps(body), encoding="utf-8")
    monkeypatch.setenv("SHOWCASE_PATH", str(p))
    assert client.get("/api/showcase").json() == body


def test_showcase_bad_json_is_empty_object(client, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "broken.json"
    p.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("SHOWCASE_PATH", str(p))
    assert client.get("/api/showcase").json() == {}
