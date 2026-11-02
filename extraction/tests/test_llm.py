import json

import httpx
import pytest

from polo_extract import llm


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def extraction_json(make_event):
    return json.dumps({"is_event_source": True, "events": [make_event().model_dump()]})


def test_ollama_extract(monkeypatch, make_event):
    sent = {}

    def fake_post(url, json, timeout, **kw):
        sent.update(url=url, body=json)
        return FakeResponse(200, {"message": {"content": extraction_json(make_event)},
                                  "prompt_eval_count": 900, "eval_count": 200})

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    r = llm.extract(image=b"img", text="hi", model="ollama:qwen2.5vl:7b")
    assert sent["url"].endswith("/api/chat")
    assert sent["body"]["model"] == "qwen2.5vl:7b"
    assert sent["body"]["messages"][1]["images"]
    assert sent["body"]["format"]["properties"]["events"]
    assert r.model == "ollama:qwen2.5vl:7b" and r.cost_usd == 0.0
    assert r.extraction.events[0].title == "CS Club Board Game Night"


def test_ollama_errors(monkeypatch):
    def down(*a, **kw):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(llm.httpx, "post", down)
    with pytest.raises(llm.NotConfigured, match="isn't running"):
        llm.extract(text="x", model="ollama:gemma3:4b")

    monkeypatch.setattr(llm.httpx, "post", lambda *a, **kw: FakeResponse(404, {"error": "model not found"}))
    with pytest.raises(llm.NotConfigured, match="ollama pull gemma3:4b"):
        llm.extract(text="x", model="ollama:gemma3:4b")

    monkeypatch.setattr(llm.httpx, "post", lambda *a, **kw: FakeResponse(200, {"message": {"content": "{}"}}))
    with pytest.raises(RuntimeError, match="schema"):
        llm.extract(text="x", model="ollama:gemma3:4b")


def test_available_models(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(llm.httpx, "get", lambda *a, **kw: FakeResponse(200, {"models": [{"name": "qwen2.5vl:7b"}, {"name": "llama3.2:3b"}]}))
    caps = {"qwen2.5vl:7b": ["completion", "vision"], "llama3.2:3b": ["completion"]}
    monkeypatch.setattr(llm.httpx, "post", lambda url, json, timeout: FakeResponse(200, {"capabilities": caps[json["model"]]}))
    for cfg in llm.PROVIDERS.values():
        monkeypatch.delenv(cfg["key_env"], raising=False)
    models = {m["id"]: m for m in llm.available_models()}
    assert models["claude-haiku-5-5"]["available"] is False
    assert models["ollama:qwen2.5vl:7b"]["vision"] is True
    assert models["ollama:llama3.2:3b"]["note"] == "text only"


def test_available_models_without_ollama(monkeypatch):
    def down(*a, **kw):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(llm.httpx, "get", down)
    assert not any(m["provider"] == "ollama" for m in llm.available_models())


def test_is_known_model():
    assert llm.is_known_model("claude-haiku-5-5")
    assert llm.is_known_model("ollama:gemma3:4b")
    assert not llm.is_known_model("ollama:")
    assert not llm.is_known_model("gpt-5")


def chat_response(make_event, content=None):
    return {"choices": [{"message": {"content": content or extraction_json(make_event)}}],
            "usage": {"prompt_tokens": 1200, "completion_tokens": 300}}


def test_hosted_needs_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(llm.NotConfigured, match="GROQ_API_KEY"):
        llm.extract(text="x", model="groq:qwen/qwen3.8-27b")


def test_hosted_extract(monkeypatch, make_event):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    calls = []

    def fake_post(url, json, headers, timeout):
        calls.append((url, json, headers))
        return FakeResponse(200, chat_response(make_event))

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    r = llm.extract(image=b"img", media_type="image/png", text="x", model="gemini:gemini-3.8-flash")
    url, body, headers = calls[0]
    assert url == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert headers["Authorization"] == "Bearer k"
    assert body["model"] == "gemini-3.8-flash"
    assert body["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    schema = body["response_format"]["json_schema"]["schema"]
    assert schema["additionalProperties"] is False and "$ref" not in str(schema)
    assert r.model == "gemini:gemini-3.8-flash" and r.input_tokens == 1200


def test_hosted_falls_back_to_json_mode(monkeypatch, make_event):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    bodies = []

    def fake_post(url, json, headers, timeout):
        bodies.append(json.copy())
        if len(bodies) == 1:
            return FakeResponse(400, {"error": "response_format json_schema not supported"})
        return FakeResponse(200, chat_response(make_event, "```json\n" + extraction_json(make_event) + "\n```"))

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    r = llm.extract(text="x", model="openrouter:google/gemma-4-31b-it:free")
    assert bodies[1]["response_format"] == {"type": "json_object"}
    assert r.model == "openrouter:google/gemma-4-31b-it:free"
    assert r.extraction.events


def test_hosted_errors(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **kw: FakeResponse(401, {"error": "bad key"}))
    with pytest.raises(llm.NotConfigured, match="rejected"):
        llm.extract(text="x", model="groq:qwen/qwen3.8-27b")
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **kw: FakeResponse(429, {"error": "slow down"}))
    with pytest.raises(RuntimeError, match="rate limit"):
        llm.extract(text="x", model="groq:qwen/qwen3.8-27b")


def test_provider_model_lists(monkeypatch):
    monkeypatch.setenv("GROQ_MODELS", "a, b")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setattr(llm.httpx, "get", lambda *a, **kw: FakeResponse(200, {"models": []}))
    ids = {m["id"]: m for m in llm.available_models()}
    assert ids["groq:a"]["available"] and "groq:b" in ids
    assert llm.is_known_model("openrouter:google/gemma-4-31b-it:free")
