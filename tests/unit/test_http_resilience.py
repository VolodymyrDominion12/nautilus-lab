from collections.abc import Mapping

import pytest

from nautilus_lab.domain.errors import MarketDataError, RateLimitedError
from nautilus_lab.domain.ports import JsonResponse
from nautilus_lab.infrastructure.http_resilience import (
    RateLimitPolicy,
    ResilientJsonClient,
    TransportUnavailableError,
    parse_retry_after,
    parse_used_weight,
)


class _RecordingSleep:
    """Captures requested delays instead of really sleeping."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


class _ScriptedTransport:
    """Returns a scripted sequence of responses (or raises) and records the calls."""

    def __init__(self, script: list[JsonResponse | Exception]) -> None:
        self._script = list(script)
        self.calls: list[Mapping[str, str]] = []

    def get(self, url: str, params: Mapping[str, str]) -> JsonResponse:
        self.calls.append(params)
        if not self._script:
            raise AssertionError("transport called more times than the script allows")
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _ok(payload: object, headers: Mapping[str, str] | None = None) -> JsonResponse:
    return JsonResponse(status=200, headers=headers or {}, payload=payload)


def _status(status: int, headers: Mapping[str, str] | None = None) -> JsonResponse:
    return JsonResponse(status=status, headers=headers or {}, payload={"msg": "err"})


def _client(
    script: list[JsonResponse | Exception],
    *,
    policy: RateLimitPolicy | None = None,
) -> tuple[ResilientJsonClient, _RecordingSleep, _ScriptedTransport]:
    sleep = _RecordingSleep()
    transport = _ScriptedTransport(script)
    client = ResilientJsonClient(transport, policy=policy, sleep=sleep)
    return client, sleep, transport


# --- header parsing ---------------------------------------------------------


def test_parse_used_weight_is_case_insensitive() -> None:
    assert parse_used_weight({"X-MBX-USED-WEIGHT-1M": "54"}) == 54
    assert parse_used_weight({"x-mbx-used-weight-1m": " 5400 "}) == 5400


def test_parse_used_weight_absent_is_none_not_zero() -> None:
    # A missing header must never read as "no weight used": endpoints that do not
    # report the meter would otherwise look idle.
    assert parse_used_weight({}) is None
    assert parse_used_weight({"X-MBX-USED-WEIGHT-1M": "not-a-number"}) is None


def test_parse_retry_after_reads_delta_seconds() -> None:
    assert parse_retry_after({"Retry-After": "12"}) == 12.0


def test_parse_retry_after_rejects_unusable_values() -> None:
    # HTTP-date form and non-positive values both fall back to exponential backoff.
    assert parse_retry_after({}) is None
    assert parse_retry_after({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}) is None
    assert parse_retry_after({"Retry-After": "0"}) is None


# --- policy -----------------------------------------------------------------


def test_policy_backoff_grows_exponentially_and_is_capped() -> None:
    policy = RateLimitPolicy(base_delay_seconds=1.0, max_delay_seconds=5.0)
    assert policy.backoff_seconds(1) == 1.0
    assert policy.backoff_seconds(2) == 2.0
    assert policy.backoff_seconds(3) == 4.0
    assert policy.backoff_seconds(4) == 5.0


def test_policy_weight_threshold_is_ninety_percent_by_default() -> None:
    assert RateLimitPolicy().weight_pause_threshold == 5400


def test_policy_rejects_nonsense() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        RateLimitPolicy(max_attempts=0)
    with pytest.raises(ValueError, match="weight_pause_ratio"):
        RateLimitPolicy(weight_pause_ratio=0)
    with pytest.raises(ValueError, match="delays"):
        RateLimitPolicy(base_delay_seconds=0)
    with pytest.raises(ValueError, match="attempt"):
        RateLimitPolicy().backoff_seconds(0)


# --- retry behaviour --------------------------------------------------------


def test_success_returns_payload_without_sleeping() -> None:
    client, sleep, _ = _client([_ok([{"a": 1}])])
    assert client.get_json("https://api.binance.com/api/v3/klines", {}) == [{"a": 1}]
    assert sleep.delays == []


def test_429_is_retried_after_the_requested_retry_after() -> None:
    client, sleep, transport = _client([_status(429, {"Retry-After": "7"}), _ok([{"a": 1}])])
    assert client.get_json("https://api.binance.com/api/v3/klines", {}) == [{"a": 1}]
    assert sleep.delays == [7.0]
    assert len(transport.calls) == 2


def test_429_without_retry_after_falls_back_to_backoff() -> None:
    client, sleep, _ = _client([_status(429), _ok([])])
    client.get_json("https://api.binance.com/api/v3/klines", {})
    assert sleep.delays == [1.0]


def test_retry_after_is_clamped_to_the_policy_ceiling() -> None:
    # A ban-length Retry-After must not park the process for hours silently.
    policy = RateLimitPolicy(max_delay_seconds=60.0)
    client, sleep, _ = _client([_status(429, {"Retry-After": "100000"}), _ok([])], policy=policy)
    client.get_json("https://api.binance.com/api/v3/klines", {})
    assert sleep.delays == [60.0]


def test_418_ip_ban_is_retried_with_backoff() -> None:
    client, sleep, _ = _client([_status(418), _ok([{"a": 1}])])
    assert client.get_json("https://api.binance.com/api/v3/klines", {}) == [{"a": 1}]
    assert sleep.delays == [1.0]


def test_server_error_is_retried() -> None:
    client, sleep, _ = _client([_status(503), _ok([])])
    client.get_json("https://api.binance.com/api/v3/klines", {})
    assert sleep.delays == [1.0]


def test_exhausted_budget_raises_instead_of_returning_a_short_series() -> None:
    policy = RateLimitPolicy(max_attempts=3)
    client, sleep, transport = _client([_status(429) for _ in range(3)], policy=policy)
    with pytest.raises(RateLimitedError, match="gave up after 3 attempts"):
        client.get_json("https://api.binance.com/api/v3/klines", {})
    assert len(transport.calls) == 3
    assert sleep.delays == [1.0, 2.0]


def test_non_retryable_status_fails_immediately_with_the_real_cause() -> None:
    # A 400 (unknown symbol, or a history window the exchange does not serve) must
    # surface, not decay into an empty list.
    client, sleep, transport = _client([_status(400)])
    with pytest.raises(MarketDataError, match="HTTP 400"):
        client.get_json("https://fapi.binance.com/futures/data/openInterestHist", {})
    assert len(transport.calls) == 1
    assert sleep.delays == []


def test_socket_failure_is_retried_then_fails_closed() -> None:
    policy = RateLimitPolicy(max_attempts=2)
    client, _, _ = _client(
        [TransportUnavailableError("dns"), TransportUnavailableError("dns")], policy=policy
    )
    with pytest.raises(RateLimitedError):
        client.get_json("https://api.binance.com/api/v3/klines", {})


def test_transport_recovery_is_transparent_to_the_caller() -> None:
    client, _, _ = _client([TransportUnavailableError("timeout"), _ok([{"a": 1}])])
    assert client.get_json("https://api.binance.com/api/v3/klines", {}) == [{"a": 1}]


# --- proactive weight governance -------------------------------------------


def test_weight_pause_is_skipped_when_no_meter_was_reported() -> None:
    client, sleep, _ = _client([_ok([]), _ok([])])
    client.get_json("https://api.binance.com/api/v3/klines", {})
    client.get_json("https://api.binance.com/api/v3/klines", {})
    assert client.last_used_weight is None
    assert sleep.delays == []


def test_low_weight_does_not_pause() -> None:
    client, sleep, _ = _client([_ok([], {"X-MBX-USED-WEIGHT-1M": "54"}), _ok([])])
    client.get_json("https://api.binance.com/api/v3/klines", {})
    client.get_json("https://api.binance.com/api/v3/klines", {})
    assert client.last_used_weight == 54
    assert sleep.delays == []


def test_weight_near_the_limit_waits_out_the_window_before_the_next_call() -> None:
    policy = RateLimitPolicy(weight_pause_seconds=60.0)
    client, sleep, transport = _client(
        [_ok([], {"X-MBX-USED-WEIGHT-1M": "5400"}), _ok([])], policy=policy
    )
    client.get_json("https://api.binance.com/api/v3/klines", {})
    assert sleep.delays == []  # nothing known yet on the first call
    client.get_json("https://api.binance.com/api/v3/klines", {})
    assert sleep.delays == [60.0]  # paused before the second request, not after a 429
    assert len(transport.calls) == 2


# --- transport-level decoding ----------------------------------------------


def test_decode_of_empty_body_is_none() -> None:
    from nautilus_lab.infrastructure.http_resilience import _decode

    assert _decode(b"") is None


def test_decode_of_non_json_error_page_is_none_not_a_crash() -> None:
    from nautilus_lab.infrastructure.http_resilience import _decode

    assert _decode(b"<html>429 Too Many Requests</html>") is None
