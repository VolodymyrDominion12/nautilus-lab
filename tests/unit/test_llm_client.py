import json
from email.message import Message
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

import nautilus_lab.infrastructure.llm_client as llm_client
from nautilus_lab.infrastructure.llm_client import LlmRequestError, OpenAICompatibleChatClient


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _request_body(request: Request) -> dict[str, object]:
    data = request.data
    if not isinstance(data, bytes):
        raise AssertionError("expected a bytes request body")
    parsed = json.loads(data.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise AssertionError("expected a JSON object body")
    return {str(key): item for key, item in parsed.items()}


def _completion(content: str) -> bytes:
    return json.dumps(
        {"choices": [{"message": {"role": "assistant", "content": content}}]}
    ).encode()


def _client(
    *,
    api_key: str = "test-key",
    base_url: str = "https://api.example.com/v1",
    model: str = "deepseek-chat",
    timeout_seconds: int = 120,
) -> OpenAICompatibleChatClient:
    return OpenAICompatibleChatClient(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout_seconds=timeout_seconds,
    )


def test_client_fails_closed_without_api_key() -> None:
    with pytest.raises(LlmRequestError, match="LLM_API_KEY"):
        _client(api_key="   ")


@pytest.mark.parametrize(
    "overrides",
    [
        {"base_url": ""},
        # urllib would open file: and custom schemes; the key must only go to an API.
        {"base_url": "file:///etc/passwd"},
        {"model": " "},
        {"timeout_seconds": 0},
    ],
)
def test_client_validates_configuration(overrides: dict[str, Any]) -> None:
    with pytest.raises(LlmRequestError):
        _client(**overrides)


def test_complete_posts_to_chat_completions(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_urlopen(request: Request, timeout: float | None = None) -> _FakeResponse:
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        seen["authorization"] = request.get_header("Authorization")
        seen["body"] = _request_body(request)
        return _FakeResponse(_completion("[]"))

    monkeypatch.setattr(llm_client, "urlopen", fake_urlopen)
    client = _client(timeout_seconds=42)
    assert client.complete(system="s", user="u") == "[]"
    assert seen["url"] == "https://api.example.com/v1/chat/completions"
    assert seen["timeout"] == 42
    assert seen["authorization"] == "Bearer test-key"
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["model"] == "deepseek-chat"
    assert body["stream"] is False
    assert body["messages"] == [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
    ]


def test_base_url_trailing_slash_is_normalised(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    def fake_urlopen(request: Request, timeout: float | None = None) -> _FakeResponse:
        seen["url"] = request.full_url
        return _FakeResponse(_completion("ok"))

    monkeypatch.setattr(llm_client, "urlopen", fake_urlopen)
    client = _client(base_url="http://127.0.0.1:11434/v1/")
    assert client.complete(system="s", user="u") == "ok"
    assert seen["url"] == "http://127.0.0.1:11434/v1/chat/completions"
    assert client.model == "deepseek-chat"


def test_complete_wraps_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: Request, timeout: float | None = None) -> _FakeResponse:
        raise HTTPError(request.full_url, 401, "Unauthorized", Message(), None)

    monkeypatch.setattr(llm_client, "urlopen", fake_urlopen)
    with pytest.raises(LlmRequestError, match="HTTP 401"):
        _client().complete(system="s", user="u")


def test_complete_wraps_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: Request, timeout: float | None = None) -> _FakeResponse:
        raise URLError("connection refused")

    monkeypatch.setattr(llm_client, "urlopen", fake_urlopen)
    with pytest.raises(LlmRequestError, match="unreachable"):
        _client().complete(system="s", user="u")


@pytest.mark.parametrize(
    "payload",
    [
        b"not json at all",
        b"{}",
        b'{"choices": []}',
        b'{"choices": [{"message": {}}]}',
        b'{"choices": [{"message": {"content": "   "}}]}',
        b'{"choices": ["nope"]}',
    ],
)
def test_complete_rejects_unexpected_shapes(
    monkeypatch: pytest.MonkeyPatch, payload: bytes
) -> None:
    def fake_urlopen(request: Request, timeout: float | None = None) -> _FakeResponse:
        return _FakeResponse(payload)

    monkeypatch.setattr(llm_client, "urlopen", fake_urlopen)
    with pytest.raises(LlmRequestError):
        _client().complete(system="s", user="u")


def test_no_openai_sdk_dependency() -> None:
    """The client must stay stdlib-only so the research loop adds no runtime deps."""
    source = llm_client.__file__
    assert source is not None
    text = Path(source).read_text(encoding="utf-8")
    for forbidden in ("import openai", "import httpx", "import requests"):
        assert forbidden not in text
