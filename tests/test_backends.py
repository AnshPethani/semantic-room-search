import io
import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from lang_grounding.backends import (
    GEMINI_DROPPED_KEYWORDS,
    BackendError,
    BackendRateLimitError,
    BackendResponseError,
    BackendTimeoutError,
    FakeBackend,
    GeminiBackend,
    HttpResponse,
    OllamaBackend,
    SchemaConversionError,
    create_backend,
    to_gemini_schema,
    urllib_post,
)
from lang_grounding.config import ConfigError, load_config
from lang_grounding.grounding_output import (
    GroundingResult,
    build_output_schema,
    load_vocabulary,
    validate_grounding,
)
from lang_grounding.scene_graph import load_scene_graph

ROOT = Path(__file__).resolve().parents[1]
GRAPH = load_scene_graph(ROOT / "data" / "scene_graph.placeholder.json")
VOCAB = load_vocabulary()
ROOMS = ["E", "K", "LR", "D", "B1", "B2"]
SCHEMA = build_output_schema(GRAPH, VOCAB)
SECRET = "test-secret-key-123456"


def walk(node):
    """Yield every dict in a nested schema."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


class RecordingHttp:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append({"url": url, "headers": dict(headers), "payload": payload,
                           "timeout": timeout})
        if self.error:
            raise self.error
        return self.response


def gemini_body(text="{}"):
    return json.dumps({"candidates": [{"content": {"parts": [{"text": text}]},
                                       "finishReason": "STOP"}]})


# ----------------------------------------------------------------- Gemini schema conversion

def test_gemini_schema_keeps_enums():
    out = to_gemini_schema(SCHEMA)
    props = out["properties"]
    assert props["targets"]["items"]["enum"] == list(VOCAB)
    assert list(props["room_prior"]["properties"]) == ROOMS
    assert props["room_prior"]["required"] == ROOMS
    constraint = props["room_constraint"]
    assert constraint["nullable"] is True
    assert constraint["items"]["enum"] == ROOMS
    assert out["required"] == ["targets", "room_prior", "room_constraint"]


def test_gemini_schema_removes_unsupported_keywords_and_uppercases_types():
    out = to_gemini_schema(SCHEMA)
    for node in walk(out):
        assert not (GEMINI_DROPPED_KEYWORDS & set(node)), node
        assert "anyOf" not in node
        if "type" in node:
            assert node["type"] == node["type"].upper()
    assert out["type"] == "OBJECT"
    assert out["properties"]["targets"]["minItems"] == 1
    prob = out["properties"]["room_prior"]["properties"]["K"]
    assert prob == {"type": "NUMBER", "minimum": 0, "maximum": 1}
    assert out["properties"]["rationale"]["maxLength"] == 300
    json.dumps(out)


def test_gemini_schema_does_not_modify_input():
    before = json.dumps(SCHEMA, sort_keys=True)
    to_gemini_schema(SCHEMA)
    assert json.dumps(SCHEMA, sort_keys=True) == before


def test_gemini_schema_rejects_unknown_keyword():
    with pytest.raises(SchemaConversionError, match="unsupported keyword 'const'"):
        to_gemini_schema({"type": "string", "const": "x"})


def test_gemini_schema_rejects_other_any_of():
    with pytest.raises(SchemaConversionError, match="anyOf"):
        to_gemini_schema({"anyOf": [{"type": "string"}, {"type": "number"}]})


def test_gemini_schema_any_of_null_either_order():
    a = to_gemini_schema({"anyOf": [{"type": "null"}, {"type": "string"}], "description": "d"})
    b = to_gemini_schema({"anyOf": [{"type": "string"}, {"type": "null"}]})
    assert a == {"type": "STRING", "description": "d", "nullable": True}
    assert b == {"type": "STRING", "nullable": True}


# ----------------------------------------------------------------- Gemini backend

def test_gemini_request_and_response():
    http = RecordingHttp(HttpResponse(200, gemini_body('{"a": 1}')))
    backend = GeminiBackend("some-model", SECRET, timeout_s=7, http_post=http)
    out = backend.generate("SYSTEM", "USER", SCHEMA)
    assert out.text == '{"a": 1}'
    assert out.model == "some-model"
    assert out.latency_s >= 0
    call = http.calls[0]
    assert call["url"].endswith("/models/some-model:generateContent")
    assert call["timeout"] == 7
    assert call["headers"] == {"x-goog-api-key": SECRET}
    payload = call["payload"]
    assert payload["systemInstruction"]["parts"][0]["text"] == "SYSTEM"
    assert payload["contents"][0]["parts"][0]["text"] == "USER"
    cfg = payload["generationConfig"]
    assert cfg["temperature"] == 0.0
    assert cfg["responseMimeType"] == "application/json"
    assert cfg["responseSchema"] == to_gemini_schema(SCHEMA)
    assert SECRET not in json.dumps(payload)


def test_gemini_model_prefix_not_doubled():
    backend = GeminiBackend("models/some-model", SECRET)
    url, _ = backend.build_request("s", "u", SCHEMA)
    assert "/models/some-model:generateContent" in url
    assert "models/models" not in url


def test_gemini_key_never_in_repr_or_errors():
    http = RecordingHttp(HttpResponse(500, "server broke"))
    backend = GeminiBackend("m", SECRET, http_post=http)
    assert SECRET not in repr(backend)
    with pytest.raises(BackendError) as info:
        backend.generate("s", "u", SCHEMA)
    assert SECRET not in str(info.value)


def test_gemini_skips_thought_parts():
    body = json.dumps({"candidates": [{"content": {"parts": [
        {"text": "thinking...", "thought": True}, {"text": '{"ok": true}'}]}}]})
    out = GeminiBackend("m", SECRET, http_post=RecordingHttp(HttpResponse(200, body))).generate(
        "s", "u", SCHEMA)
    assert out.text == '{"ok": true}'


@pytest.mark.parametrize("status, exc", [
    (429, BackendRateLimitError),
    (504, BackendTimeoutError),
    (500, BackendError),
    (400, BackendError),
])
def test_gemini_http_status_errors(status, exc):
    backend = GeminiBackend("m", SECRET, http_post=RecordingHttp(HttpResponse(status, "{}")))
    with pytest.raises(exc):
        backend.generate("s", "u", SCHEMA)


def test_gemini_timeout_propagates():
    backend = GeminiBackend(
        "m", SECRET, http_post=RecordingHttp(error=BackendTimeoutError("slow")))
    with pytest.raises(BackendTimeoutError):
        backend.generate("s", "u", SCHEMA)


@pytest.mark.parametrize("body", [
    "not json",
    "[]",
    json.dumps({"candidates": []}),
    json.dumps({"promptFeedback": {"blockReason": "SAFETY"}}),
    json.dumps({"candidates": [{"content": {"parts": []}, "finishReason": "MAX_TOKENS"}]}),
])
def test_gemini_malformed_response(body):
    backend = GeminiBackend("m", SECRET, http_post=RecordingHttp(HttpResponse(200, body)))
    with pytest.raises(BackendResponseError):
        backend.generate("s", "u", SCHEMA)


def test_gemini_requires_model_and_key():
    with pytest.raises(ConfigError):
        GeminiBackend("", SECRET)
    with pytest.raises(ConfigError):
        GeminiBackend("m", "")


# ----------------------------------------------------------------- Ollama backend

def test_ollama_request_contains_full_schema():
    body = json.dumps({"message": {"role": "assistant", "content": '{"x": 1}'}})
    http = RecordingHttp(HttpResponse(200, body))
    backend = OllamaBackend("llama3.1:8b", host="http://example:1234/", timeout_s=9,
                            http_post=http)
    out = backend.generate("SYSTEM", "USER", SCHEMA)
    assert out.text == '{"x": 1}'
    assert out.model == "llama3.1:8b"
    call = http.calls[0]
    assert call["url"] == "http://example:1234/api/chat"
    assert call["timeout"] == 9
    payload = call["payload"]
    assert payload["format"] == SCHEMA  # the full schema, unconverted
    assert payload["options"] == {"temperature": 0.0}
    assert payload["stream"] is False
    assert payload["model"] == "llama3.1:8b"
    assert payload["messages"] == [
        {"role": "system", "content": "SYSTEM"}, {"role": "user", "content": "USER"}]


@pytest.mark.parametrize("response, exc", [
    (HttpResponse(404, '{"error": "model not found"}'), BackendError),
    (HttpResponse(429, "{}"), BackendRateLimitError),
    (HttpResponse(200, "nope"), BackendResponseError),
    (HttpResponse(200, "{}"), BackendResponseError),
    (HttpResponse(200, '{"error": "boom"}'), BackendError),
])
def test_ollama_errors(response, exc):
    backend = OllamaBackend("m", http_post=RecordingHttp(response))
    with pytest.raises(exc):
        backend.generate("s", "u", SCHEMA)


# ----------------------------------------------------------------- urllib layer (mocked)

class _FakeUrlopen:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def __call__(self, request, timeout=None):
        if self.error:
            raise self.error
        return self.result

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_urllib_post_maps_timeout(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", _FakeUrlopen(error=TimeoutError()))
    with pytest.raises(BackendTimeoutError):
        urllib_post("http://x/y", {}, {}, 1.0)


def test_urllib_post_maps_url_error_timeout_and_refused(monkeypatch):
    monkeypatch.setattr(
        urllib.request, "urlopen",
        _FakeUrlopen(error=urllib.error.URLError(TimeoutError())))
    with pytest.raises(BackendTimeoutError):
        urllib_post("http://x/y", {}, {}, 1.0)
    monkeypatch.setattr(
        urllib.request, "urlopen",
        _FakeUrlopen(error=urllib.error.URLError(ConnectionRefusedError("refused"))))
    with pytest.raises(BackendError, match="cannot reach x"):
        urllib_post("http://x/y", {}, {}, 1.0)


def test_urllib_post_returns_http_error_status(monkeypatch):
    err = urllib.error.HTTPError("http://x/y", 429, "Too Many", {}, io.BytesIO(b'{"e": 1}'))
    monkeypatch.setattr(urllib.request, "urlopen", _FakeUrlopen(error=err))
    assert urllib_post("http://x/y", {}, {}, 1.0) == HttpResponse(429, '{"e": 1}')


# ----------------------------------------------------------------- Fake backend

def test_fake_default_response_is_valid():
    backend = FakeBackend()
    out = backend.generate("s", "u", SCHEMA)
    result = validate_grounding(json.loads(out.text), GRAPH, VOCAB)
    assert isinstance(result, GroundingResult)
    assert result.targets == [VOCAB[0]]
    assert len(backend.calls) == 1


def test_fake_script_items_and_exhaustion():
    backend = FakeBackend(["raw text", {"a": 1}, BackendTimeoutError("t")], model="m")
    assert backend.generate("s", "u", SCHEMA).text == "raw text"
    assert json.loads(backend.generate("s", "u", SCHEMA).text) == {"a": 1}
    with pytest.raises(BackendTimeoutError):
        backend.generate("s", "u", SCHEMA)
    with pytest.raises(BackendError, match="exhausted"):
        backend.generate("s", "u", SCHEMA)
    assert len(backend.calls) == 4


# ----------------------------------------------------------------- factory

def test_create_backend_fake_and_ollama():
    config = load_config()
    assert isinstance(create_backend("fake", config), FakeBackend)
    ollama = create_backend("ollama", config)
    assert isinstance(ollama, OllamaBackend)
    assert ollama.model == config.ollama.model == "llama3.1:8b"


def test_create_backend_gemini_needs_key_and_model():
    config = load_config()
    with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
        create_backend("gemini", config, env={})
    with pytest.raises(ConfigError, match="model"):
        create_backend("gemini", config, env={"GEMINI_API_KEY": SECRET})
    backend = create_backend(
        "gemini", config, env={"GEMINI_API_KEY": SECRET, "GEMINI_MODEL": "env-model"})
    assert isinstance(backend, GeminiBackend)
    assert backend.model == "env-model"
    assert SECRET not in repr(backend)


def test_create_backend_unknown():
    with pytest.raises(ConfigError, match="unknown backend"):
        create_backend("nope", load_config())
