"""Rate-limit-aware JSON GET for public exchange endpoints.

Implements the protocol described in `docs/23 §1` (doc section 3): public REST
endpoints are not free — Binance meters them in *request weight*, answers an
over-limit caller with HTTP 429 plus a `Retry-After` header, and escalates
persistent abuse to an IP ban signalled as HTTP 418, whose length grows from
minutes to days.

The policy here is deliberately three-tiered:

* **proactive** — the exchange reports its own meter in `X-MBX-USED-WEIGHT-1M`
  on every response. Once that meter reaches `weight_pause_ratio` of the limit we
  wait out the window *before* issuing the next request, instead of spending a
  retry on a 429 we could see coming.
* **reactive** — a 429 is honoured through `Retry-After` when the exchange sends
  it, falling back to exponential backoff otherwise.
* **fail closed** — when the retry budget runs out the call raises
  `RateLimitedError` rather than returning a short series. A truncated catalog
  that looks complete is worse than an ingest that stops loudly.

Only public, key-less endpoints are in scope; nothing here signs a request or
touches an order path.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from nautilus_lab.domain.errors import MarketDataError, RateLimitedError
from nautilus_lab.domain.ports import JsonResponse, JsonTransport

# Read timeout for one request. Measured 2026-09-23 against `api/v3/aggTrades`: the
# typical page answers in ~0.7s and an occasional one in ~4.7s, but roughly one in
# three stalls and never answers at all. A stalled socket is retried either way, so the
# timeout is pure waiting cost: at 30s a tick ingest spent most of its wall clock on
# sockets that were never going to reply, which is what made a single day of history
# look impossible. 10s keeps the slow-but-real 4.7s case and cuts each stall's cost
# threefold.
_HTTP_TIMEOUT_SECONDS = 10
_RETRYABLE_STATUSES = frozenset({418, 429, 500, 502, 503, 504})
_WEIGHT_HEADER = "x-mbx-used-weight-1m"


class TransportUnavailableError(RuntimeError):
    """The socket failed: DNS, TLS, timeout or a dropped connection.

    Retryable by nature, so it never escapes `ResilientJsonClient.get_json`.
    """


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    """Retry budget and backoff shape. Defaults follow the weights in docs/23 §1."""

    max_attempts: int = 5
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0
    weight_limit: int = 6000
    weight_pause_ratio: float = 0.9
    weight_pause_seconds: float = 60.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.base_delay_seconds <= 0 or self.max_delay_seconds <= 0:
            raise ValueError("delays must be > 0")
        if not 0 < self.weight_pause_ratio <= 1:
            raise ValueError("weight_pause_ratio must be in (0, 1]")

    @property
    def weight_pause_threshold(self) -> int:
        """Weight at which we wait out the window instead of risking a 429."""
        return int(self.weight_limit * self.weight_pause_ratio)

    def backoff_seconds(self, attempt: int) -> float:
        """Exponential backoff for a 1-based attempt number, capped at max_delay."""
        if attempt < 1:
            raise ValueError("attempt must be >= 1")
        return min(self.max_delay_seconds, self.base_delay_seconds * float(2 ** (attempt - 1)))


def _header(headers: Mapping[str, str], name: str) -> str | None:
    """Case-insensitive header lookup that also works on plain dicts (tests)."""
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None


def parse_used_weight(headers: Mapping[str, str]) -> int | None:
    """Read `X-MBX-USED-WEIGHT-1M`. None when absent or not an integer.

    Absent is normal and not an error: only spot endpoints report this meter, and
    a missing header must never be treated as a weight of zero.
    """
    raw = _header(headers, _WEIGHT_HEADER)
    if raw is None:
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


def parse_retry_after(headers: Mapping[str, str]) -> float | None:
    """Read `Retry-After` seconds. None when absent, non-numeric or in the past.

    Only the delta-seconds form is supported; the HTTP-date form degrades to
    `None` and the caller falls back to exponential backoff.
    """
    raw = _header(headers, "retry-after")
    if raw is None:
        return None
    try:
        seconds = float(raw.strip())
    except ValueError:
        return None
    return seconds if seconds > 0 else None


class UrllibJsonTransport:
    """Single stdlib GET. Converts HTTP errors into data; raises on socket failure."""

    def __init__(self, *, timeout_seconds: float = _HTTP_TIMEOUT_SECONDS) -> None:
        self._timeout_seconds = timeout_seconds

    def get(self, url: str, params: Mapping[str, str]) -> JsonResponse:
        request = Request(  # noqa: S310 — callers pass the fixed https Binance endpoints
            f"{url}?{urlencode(params)}",
            headers={"User-Agent": "nautilus-lab/research"},
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:  # noqa: S310
                body = response.read()
                return JsonResponse(
                    status=int(response.status),
                    headers=dict(response.headers),
                    payload=_decode(body),
                )
        except HTTPError as exc:
            # 429/418/5xx arrive here. They are outcomes, not exceptions, for as
            # long as the retry policy still has budget left.
            body = exc.read()
            return JsonResponse(
                status=int(exc.code),
                headers=dict(exc.headers or {}),
                payload=_decode(body),
            )
        except (URLError, TimeoutError, OSError) as exc:
            raise TransportUnavailableError(f"{url}: {exc}") from exc


def _decode(body: bytes) -> object:
    """Parse a JSON body, tolerating an empty or non-JSON error page."""
    if not body:
        return None
    try:
        return json.loads(body.decode())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


class ResilientJsonClient:
    """`JsonHttpClient` that honours the exchange rate-limit protocol.

    Wrap a `JsonTransport`; callers keep depending on the plain `JsonHttpClient`
    port and never see a retry.
    """

    def __init__(
        self,
        transport: JsonTransport | None = None,
        *,
        policy: RateLimitPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._transport = transport or UrllibJsonTransport()
        self._policy = policy or RateLimitPolicy()
        self._sleep = sleep
        self._last_used_weight: int | None = None

    @property
    def last_used_weight(self) -> int | None:
        """Most recent `X-MBX-USED-WEIGHT-1M` observed, or None if never reported."""
        return self._last_used_weight

    def get_json(self, url: str, params: Mapping[str, str]) -> object:
        last_error = "no attempt was made"
        for attempt in range(1, self._policy.max_attempts + 1):
            self._wait_if_weight_is_high()
            try:
                response = self._transport.get(url, params)
            except TransportUnavailableError as exc:
                last_error = str(exc)
                if attempt == self._policy.max_attempts:
                    break
                self._sleep(self._policy.backoff_seconds(attempt))
                continue

            self._observe_weight(response)
            if response.status == 200:
                return response.payload
            if response.status in _RETRYABLE_STATUSES:
                last_error = f"HTTP {response.status}"
                if attempt == self._policy.max_attempts:
                    break
                self._sleep(self._retry_delay(response, attempt))
                continue
            raise MarketDataError(
                f"{url} answered HTTP {response.status}; not retryable. "
                f"payload={_summarise(response.payload)}"
            )
        raise RateLimitedError(
            f"{url}: gave up after {self._policy.max_attempts} attempts ({last_error}). "
            "Fail closed: a truncated series must not be written to the catalog."
        )

    def _observe_weight(self, response: JsonResponse) -> None:
        weight = parse_used_weight(response.headers)
        if weight is not None:
            self._last_used_weight = weight

    def _wait_if_weight_is_high(self) -> None:
        if self._last_used_weight is None:
            return
        if self._last_used_weight < self._policy.weight_pause_threshold:
            return
        # Wait out the one-minute metering window rather than spend a retry on a
        # 429 that the exchange has already told us is coming.
        self._sleep(self._policy.weight_pause_seconds)

    def _retry_delay(self, response: JsonResponse, attempt: int) -> float:
        retry_after = parse_retry_after(response.headers)
        if retry_after is None:
            return self._policy.backoff_seconds(attempt)
        return min(retry_after, self._policy.max_delay_seconds)


def _summarise(payload: object) -> str:
    text = str(payload)
    return text if len(text) <= 200 else f"{text[:200]}..."
