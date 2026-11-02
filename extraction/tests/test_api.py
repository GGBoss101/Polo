import json

import pytest
from fastapi.testclient import TestClient

from polo_extract import api, llm
from polo_extract.schema import Extraction


@pytest.fixture
def client(tmp_path, monkeypatch, make_event):
    monkeypatch.setattr(api, "LOG_DIR", tmp_path)
    api._hits.clear()

    def fake_extract(**kw):
        fake_extract.kw = kw
        return llm.LLMResult(Extraction(is_event_source=True, events=[make_event()]),
                             "claude-opus-5-5", 1234, 1500, 300, 0.012)

    monkeypatch.setattr(llm, "extract", fake_extract)
    c = TestClient(api.app)
    c.fake = fake_extract
    c.logs = tmp_path
    return c


def test_extract_text(client):
    r = client.post("/api/extract", data={"text": "Board games Fri 6pm ICCS X150", "captured_on": "2026-11-01"})
    assert r.status_code == 200
    body = r.json()
    assert body["events"][0]["building_code"] == "ICCS"
    assert body["events"][0]["google_calendar_url"]
    assert body["meta"]["cost_usd"] == 0.012
    assert client.fake.kw["image"] is None
    rec = json.loads((client.logs / "captures.jsonl").read_text())
    assert rec["n_events"] == 1 and rec["source"] == "text"


def test_extract_image(client):
    r = client.post("/api/extract", files={"image": ("p.jpg", b"\xff\xd8fake", "image/jpeg")})
    assert r.status_code == 200
    assert client.fake.kw["image"] == b"\xff\xd8fake"


def test_extract_validation(client):
    assert client.post("/api/extract", data={}).status_code == 400
    assert client.post("/api/extract", files={"image": ("p.pdf", b"x", "application/pdf")}).status_code == 415
    assert client.post("/api/extract", data={"text": "x", "captured_on": "nope"}).status_code == 400


def test_rate_limit(client, monkeypatch):
    monkeypatch.setattr(api, "RATE_LIMIT", 2)
    codes = [client.post("/api/extract", data={"text": "x"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_ics_and_log(client):
    ev = client.post("/api/extract", data={"text": "x", "captured_on": "2026-11-01"}).json()["events"][0]
    r = client.post("/api/ics", json={"events": [ev], "capture_id": "abc"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/calendar")
    assert "BEGIN:VEVENT" in r.text
    assert client.post("/api/log", json={"type": "visibility", "data": {"visibility": "public"}}).status_code == 204
    lines = (client.logs / "activity.jsonl").read_text().splitlines()
    assert [json.loads(l)["type"] for l in lines] == ["ics_download", "visibility"]


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Polo" in r.text


def test_model_choice_ignored_outside_dev(client, monkeypatch):
    monkeypatch.setattr(api, "DEV", False)
    client.post("/api/extract", data={"text": "x", "model": "ollama:gemma3:4b"})
    assert client.fake.kw["model"] == llm.DEFAULT_MODEL
    assert client.get("/api/config").json()["models"] == []


def test_model_choice_in_dev(client, monkeypatch):
    monkeypatch.setattr(api, "DEV", True)
    monkeypatch.setattr(llm, "available_models", lambda: [{"id": "ollama:gemma3:4b"}])
    client.post("/api/extract", data={"text": "x", "model": "ollama:gemma3:4b"})
    assert client.fake.kw["model"] == "ollama:gemma3:4b"
    assert client.post("/api/extract", data={"text": "x", "model": "gpt-5"}).status_code == 400
    cfg = client.get("/api/config").json()
    assert cfg["dev"] and cfg["models"][0]["id"] == "ollama:gemma3:4b"


def test_extract_uses_linked_pages(client, monkeypatch):
    from polo_extract import enrich as enrich_mod, links

    page = links.LinkedPage(url="https://qr.link", final_url="https://events.ubc.ca/e/1", title="Board Game Night")
    fake = enrich_mod.Enrichment(qr=["https://qr.link"], results=[links.LinkResult("https://qr.link", page=page)],
                                 origin={"https://qr.link": "qr"})
    monkeypatch.setattr(api, "enrich", lambda image, text: fake)
    body = client.post("/api/extract", files={"image": ("p.jpg", b"\xff\xd8x", "image/jpeg")}).json()
    assert '<linked_page url="https://events.ubc.ca/e/1">' in client.fake.kw["context"]
    assert body["sources"][0] == {"url": "https://qr.link", "from": "qr", "read": True,
                                  "title": "Board Game Night", "note": None}
    assert body["events"][0]["link"] == "https://events.ubc.ca/e/1"
