"""LLM backends (D-104 to D-109): Gemini, Ollama, and a scripted fake. No ROS imports.

All HTTP goes through one injectable function (`HttpPost`), so tests never touch the network.
The Gemini API key is read from the environment, sent only in a request header, and never
appears in messages, reprs, or logs.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from lang_grounding.config import (
    GEMINI_API_KEY_ENV,
    GEMINI_MODEL_ENV,
    ConfigError,
    GroundingConfig,
)

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


# --------------------------------------------------------------------------- errors and types

class BackendError(Exception):
    """A backend call failed (network problem or an HTTP error status)."""


class BackendTimeoutError(BackendError):
    """The backend did not answer within the timeout."""


class BackendRateLimitError(BackendError):
    """Rate limit or quota exhausted (HTTP 429)."""


class BackendResponseError(BackendError):
    """The backend answered, but the response is not in the expected format."""


@dataclass(frozen=True)
class BackendResponse:
    text: str
    latency_s: float
    model: str


class Backend(Protocol):
    """Anything that can turn prompts plus a JSON Schema into response text."""

    model: str

    def generate(
        self, system_prompt: str, user_prompt: str, json_schema: dict[str, Any]
    ) -> BackendResponse: ...


# --------------------------------------------------------------------------- HTTP layer

@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: str


HttpPost = Callable[[str, Mapping[str, str], Mapping[str, Any], float], HttpResponse]


def urllib_post(
    url: str, headers: Mapping[str, str], payload: Mapping[str, Any], timeout: float
) -> HttpResponse:
    """POST JSON with the standard library. Maps timeouts and connection failures to errors."""
    host = urllib.parse.urlsplit(url).netloc
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return HttpResponse(response.status, response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return HttpResponse(exc.code, exc.read().decode("utf-8", "replace"))
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise BackendTimeoutError(f"request to {host} timed out after {timeout} s") from exc
        raise BackendError(f"cannot reach {host}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise BackendTimeoutError(f"request to {host} timed out after {timeout} s") from exc
    except OSError as exc:
        raise BackendError(f"network error talking to {host}: {exc}") from exc


def _snippet(body: str, limit: int = 300) -> str:
    text = " ".join(body.split())
    return text if len(text) <= limit else text[:limit] + "..."


def _check_status(name: str, response: HttpResponse) -> None:
    status = response.status
    if status == 429:
        raise BackendRateLimitError(
            f"{name}: rate limit or quota exhausted (HTTP 429): {_snippet(response.body)}")
    if status in (408, 504):
        raise BackendTimeoutError(f"{name}: HTTP {status}: {_snippet(response.body)}")
    if status < 200 or status >= 300:
        raise BackendError(f"{name}: HTTP {status}: {_snippet(response.body)}")


def _json_body(name: str, body: str) -> dict[str, Any]:
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise BackendResponseError(f"{name}: response body is not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise BackendResponseError(f"{name}: response body is not a JSON object")
    return data


# --------------------------------------------------------------------------- Gemini schema

# Gemini's `responseSchema` accepts an OpenAPI-style subset of JSON Schema (D-107).
GEMINI_KEPT_KEYWORDS = frozenset({
    "type", "enum", "properties", "required", "items", "description",
    "minItems", "maxItems", "minimum", "maximum", "minLength", "maxLength",
})
GEMINI_DROPPED_KEYWORDS = frozenset({
    "$schema", "$id", "title", "additionalProperties", "uniqueItems",
})
_JSON_TYPES = frozenset({"string", "number", "integer", "boolean", "array", "object"})


class SchemaConversionError(ValueError):
    """The JSON Schema uses something the Gemini conversion does not handle."""


def to_gemini_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Convert our response JSON Schema into Gemini's `responseSchema` subset. Pure function.

    Kept: type, enum, properties, required, items, description, minItems, maxItems, minimum,
    maximum, minLength, maxLength.
    Dropped silently: $schema, $id, title, additionalProperties, uniqueItems.
    Rewritten: `type` names to upper case ("string" -> "STRING"); `anyOf: [{"type": "null"}, X]`
    (either order) to X plus `nullable: true`.
    Anything else (other anyOf shapes, const, $ref, oneOf, not, ...) raises
    SchemaConversionError instead of being dropped without notice.
    """
    return _convert_node(schema, "$")


def _convert_node(node: Any, path: str) -> dict[str, Any]:
    if not isinstance(node, Mapping):
        raise SchemaConversionError(f"{path}: schema node must be an object")
    if "anyOf" in node:
        return _convert_any_of(node, path)
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in GEMINI_DROPPED_KEYWORDS:
            continue
        if key not in GEMINI_KEPT_KEYWORDS:
            raise SchemaConversionError(f"{path}: unsupported keyword {key!r}")
        if key == "type":
            if not isinstance(value, str) or value not in _JSON_TYPES:
                raise SchemaConversionError(f"{path}: unsupported type {value!r}")
            out[key] = value.upper()
        elif key == "properties":
            out[key] = {
                name: _convert_node(sub, f"{path}.properties.{name}")
                for name, sub in value.items()
            }
        elif key == "items":
            out[key] = _convert_node(value, f"{path}.items")
        elif key in ("enum", "required"):
            out[key] = list(value)
        else:
            out[key] = value
    return out


def _convert_any_of(node: Mapping[str, Any], path: str) -> dict[str, Any]:
    branches = node["anyOf"]
    non_null = [b for b in branches if not (isinstance(b, Mapping) and b.get("type") == "null")]
    if len(branches) != 2 or len(non_null) != 1:
        raise SchemaConversionError(f"{path}: only anyOf [null, X] is supported")
    outer = {k: v for k, v in node.items() if k != "anyOf"}
    out = _convert_node(non_null[0], path)
    out.update(_convert_node(outer, path))
    out["nullable"] = True
    return out


# --------------------------------------------------------------------------- Gemini

class GeminiBackend:
    """Gemini `generateContent` over REST, JSON mode with a response schema, temperature 0."""

    def __init__(
        self,
        model: str,
        api_key: str,
        *,
        timeout_s: float = 30.0,
        temperature: float = 0.0,
        http_post: HttpPost = urllib_post,
        base_url: str = GEMINI_BASE_URL,
    ) -> None:
        if not model:
            raise ConfigError("Gemini model name is empty")
        if not api_key:
            raise ConfigError(f"{GEMINI_API_KEY_ENV} is empty")
        self.model = model
        self._api_key = api_key
        self._timeout_s = timeout_s
        self._temperature = temperature
        self._http_post = http_post
        self._base_url = base_url.rstrip("/")

    def __repr__(self) -> str:  # never show the key
        return f"GeminiBackend(model={self.model!r})"

    def build_request(
        self, system_prompt: str, user_prompt: str, json_schema: Mapping[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        """URL and JSON body of the request (no key inside)."""
        model_path = self.model if self.model.startswith("models/") else f"models/{self.model}"
        url = f"{self._base_url}/{model_path}:generateContent"
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": self._temperature,
                "responseMimeType": "application/json",
                "responseSchema": to_gemini_schema(json_schema),
            },
        }
        return url, payload

    def generate(
        self, system_prompt: str, user_prompt: str, json_schema: dict[str, Any]
    ) -> BackendResponse:
        url, payload = self.build_request(system_prompt, user_prompt, json_schema)
        start = time.perf_counter()
        response = self._http_post(
            url, {"x-goog-api-key": self._api_key}, payload, self._timeout_s)
        latency = time.perf_counter() - start
        _check_status("Gemini", response)
        return BackendResponse(_gemini_text(response.body), latency, self.model)


def _gemini_text(body: str) -> str:
    data = _json_body("Gemini", body)
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        feedback = data.get("promptFeedback")
        raise BackendResponseError(f"Gemini: no candidates in response (promptFeedback={feedback})")
    content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    texts = [
        p["text"] for p in (parts or [])
        if isinstance(p, dict) and isinstance(p.get("text"), str) and not p.get("thought")
    ]
    if not texts:
        reason = candidates[0].get("finishReason") if isinstance(candidates[0], dict) else None
        raise BackendResponseError(f"Gemini: candidate has no text (finishReason={reason})")
    return "".join(texts)


# --------------------------------------------------------------------------- Ollama

class OllamaBackend:
    """Local Ollama server, `/api/chat`, full JSON Schema in `format`, temperature 0."""

    def __init__(
        self,
        model: str,
        *,
        host: str = "http://localhost:11434",
        timeout_s: float = 120.0,
        temperature: float = 0.0,
        http_post: HttpPost = urllib_post,
    ) -> None:
        if not model:
            raise ConfigError("Ollama model name is empty")
        self.model = model
        self._host = host.rstrip("/")
        self._timeout_s = timeout_s
        self._temperature = temperature
        self._http_post = http_post

    def __repr__(self) -> str:
        return f"OllamaBackend(model={self.model!r}, host={self._host!r})"

    def build_request(
        self, system_prompt: str, user_prompt: str, json_schema: Mapping[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "format": json_schema,
            "stream": False,
            "options": {"temperature": self._temperature},
        }
        return f"{self._host}/api/chat", payload

    def generate(
        self, system_prompt: str, user_prompt: str, json_schema: dict[str, Any]
    ) -> BackendResponse:
        url, payload = self.build_request(system_prompt, user_prompt, json_schema)
        start = time.perf_counter()
        response = self._http_post(url, {}, payload, self._timeout_s)
        latency = time.perf_counter() - start
        _check_status("Ollama", response)
        data = _json_body("Ollama", response.body)
        if "error" in data:
            raise BackendError(f"Ollama: {_snippet(str(data['error']))}")
        message = data.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise BackendResponseError("Ollama: response has no message.content text")
        return BackendResponse(content, latency, self.model)


# --------------------------------------------------------------------------- Fake

@dataclass(frozen=True)
class FakeCall:
    system_prompt: str
    user_prompt: str
    json_schema: dict[str, Any]


class FakeBackend:
    """Scripted backend for tests and offline use; never touches the network.

    `script` is a list consumed one item per call: a str (returned as the response text), a
    dict or list (returned as JSON text), or an exception instance (raised). When the script is
    exhausted a BackendError is raised. With `script=None` every call returns a valid, uniform
    response built from the schema (first vocabulary class, equal probability for every room).
    """

    def __init__(
        self,
        script: Sequence[Any] | None = None,
        *,
        model: str = "fake-model",
        latency_s: float = 0.0,
    ) -> None:
        self.model = model
        self._script = None if script is None else list(script)
        self._latency_s = latency_s
        self.calls: list[FakeCall] = []

    def generate(
        self, system_prompt: str, user_prompt: str, json_schema: dict[str, Any]
    ) -> BackendResponse:
        self.calls.append(FakeCall(system_prompt, user_prompt, json_schema))
        if self._script is None:
            text = json.dumps(_default_fake_response(json_schema))
        else:
            if not self._script:
                raise BackendError("FakeBackend script exhausted")
            item = self._script.pop(0)
            if isinstance(item, BaseException):
                raise item
            text = item if isinstance(item, str) else json.dumps(item)
        return BackendResponse(text, self._latency_s, self.model)


def _default_fake_response(schema: Mapping[str, Any]) -> dict[str, Any]:
    props = schema["properties"]
    rooms = list(props["room_prior"]["properties"])
    return {
        "targets": [props["targets"]["items"]["enum"][0]],
        "room_prior": {rid: 1.0 / len(rooms) for rid in rooms},
        "room_constraint": None,
        "rationale": "Fake backend: uniform prior.",
    }


# --------------------------------------------------------------------------- factory

def create_backend(
    kind: str, config: GroundingConfig, env: Mapping[str, str] | None = None
) -> Backend:
    """Build a backend by name ("gemini", "ollama", "fake") from settings and the environment.

    Gemini model: the GEMINI_MODEL environment variable if set, else `gemini.model` in the
    config. A missing key or model raises ConfigError (it is a setup problem, not a backend
    failure, so it never falls back silently).
    """
    env = os.environ if env is None else env
    if kind == "fake":
        return FakeBackend()
    if kind == "ollama":
        s = config.ollama
        return OllamaBackend(
            s.model, host=s.host, timeout_s=s.timeout_s, temperature=s.temperature)
    if kind == "gemini":
        s = config.gemini
        key = env.get(GEMINI_API_KEY_ENV)
        if not key:
            raise ConfigError(f"{GEMINI_API_KEY_ENV} is not set")
        model = env.get(GEMINI_MODEL_ENV) or s.model
        if not model:
            raise ConfigError(
                f"no Gemini model name: set {GEMINI_MODEL_ENV} or gemini.model in "
                f"configs/grounding.json")
        return GeminiBackend(
            model, key, timeout_s=s.timeout_s, temperature=s.temperature)
    raise ConfigError(f"unknown backend {kind!r}; use gemini, ollama or fake")
