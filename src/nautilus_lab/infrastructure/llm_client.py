"""OpenAI-compatible chat client for the offline research loop.

Works with any endpoint that speaks the `/chat/completions` schema: a hosted API, a
locally served open-weights model (vLLM / Ollama / llama.cpp — the data-sovereignty
route the 2026 survey argues for), or a corporate gateway.

Research only. Nothing in the backtest or execution path may import this module; the
only caller is `scripts/propose_alphas.py` (docs/14-llm-model-u-torhivli.md, section 1).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

DEFAULT_TIMEOUT_SECONDS = 120
_MAX_ERROR_BODY = 400


class LlmRequestError(RuntimeError):
    """The endpoint is unreachable, refused the call, or answered in an unknown shape."""


class OpenAICompatibleChatClient:
    """Minimal chat-completions client. No streaming, no tools, no retries."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float = 0.2,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not api_key.strip():
            raise LlmRequestError(
                "LLM_API_KEY is required; the proposal loop fails closed without it"
            )
        if not base_url.strip():
            raise LlmRequestError("LLM_BASE_URL must not be empty")
        if urlsplit(base_url.strip()).scheme not in ("http", "https"):
            # urllib also opens file: and custom schemes; the key must only go to an API.
            raise LlmRequestError("LLM_BASE_URL must be an http(s) URL")
        if not model.strip():
            raise LlmRequestError("LLM_MODEL must not be empty")
        if timeout_seconds < 1:
            raise LlmRequestError("LLM_TIMEOUT_SECONDS must be >= 1")
        self._api_key = api_key.strip()
        self._endpoint = f"{base_url.strip().rstrip('/')}/chat/completions"
        self._model = model.strip()
        self._temperature = temperature
        self._timeout_seconds = timeout_seconds

    @property
    def model(self) -> str:
        return self._model

    def complete(self, *, system: str, user: str) -> str:
        """One non-streamed completion. Raises LlmRequestError on any deviation."""
        body = json.dumps(
            {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": self._temperature,
                "stream": False,
            }
        ).encode("utf-8")
        request = Request(  # noqa: S310 — scheme checked in __init__
            self._endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "User-Agent": "nautilus-lab/research",
            },
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:  # noqa: S310
                raw = response.read()
        except HTTPError as exc:
            raise LlmRequestError(
                f"endpoint returned HTTP {exc.code}: {_short(str(exc.reason))}"
            ) from exc
        except URLError as exc:
            raise LlmRequestError(f"endpoint unreachable: {_short(str(exc.reason))}") from exc

        try:
            decoded: object = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LlmRequestError("endpoint returned a non-JSON body") from exc
        return _extract_content(decoded)


def _extract_content(payload: object) -> str:
    root = _require_mapping(payload, what="response")
    choices = root.get("choices")
    if not isinstance(choices, Sequence) or isinstance(choices, (str, bytes)) or not choices:
        raise LlmRequestError("response has no 'choices' array")
    first = _require_mapping(choices[0], what="choices[0]")
    message = _require_mapping(first.get("message"), what="choices[0].message")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise LlmRequestError("response message carries no text content")
    return content


def _require_mapping(value: object, *, what: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise LlmRequestError(f"{what} must be a JSON object")
    return {str(key): item for key, item in value.items()}


def _short(text: str) -> str:
    return text[:_MAX_ERROR_BODY]
