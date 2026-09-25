"""Unit tests for the public Binance WebSocket kline stream.

Every test here runs without a socket and without a network: the payloads are real
Binance message bodies, and the stream loop is driven through its injected connector.
The centre of gravity is the lookahead guard — an open candle (`k.x == false`) must
never produce a bar — and the mapping of a closed candle onto the domain's `OhlcvBar`.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from decimal import Decimal
from types import TracebackType
from typing import Any

import pytest

from nautilus_lab.domain.bars import OhlcvBar, validate_bar
from nautilus_lab.domain.errors import InvalidBarError
from nautilus_lab.infrastructure.binance_klines import parse_binance_kline
from nautilus_lab.infrastructure.binance_ws import (
    BinanceKlineStream,
    KlinePayloadError,
    KlineStreamUnavailableError,
    ReconnectPolicy,
    SocketLike,
    parse_kline_message,
)

# A genuine `ethusdt@kline_1m` message body, copied verbatim from Binance's stream
# documentation (the example in the task statement). `x: false` means the candle is
# still forming, which is exactly the case the lookahead guard has to reject.
OPEN_KLINE_MESSAGE: dict[str, Any] = {
    "e": "kline",
    "E": 1561737563000,
    "s": "ETHUSDT",
    "k": {
        "t": 1561737540000,
        "T": 1561737599999,
        "s": "ETHUSDT",
        "i": "1m",
        "f": 100,
        "L": 200,
        "o": "293.78000000",
        "c": "293.90000000",
        "h": "293.96000000",
        "l": "293.78000000",
        "v": "85.98300000",
        "n": 42,
        "x": False,
        "q": "25275.72000000",
        "V": "50.00000000",
        "Q": "14700.00000000",
        "B": "0",
    },
}

# `k.T` of the fixture above: the candle's CLOSE time, which is what the bar carries.
# Close time, not open time, because the catalog ingest (`binance_klines`) anchors the
# same bar on field 6 (close), and the taker-flow series is keyed on that timestamp.
CLOSE_TIME_UTC = datetime(2019, 6, 28, 15, 59, 59, 999000, tzinfo=UTC)


def _closed_message() -> dict[str, Any]:
    """The same real payload with `x: true`, i.e. the candle Binance calls complete."""
    message: dict[str, Any] = copy.deepcopy(OPEN_KLINE_MESSAGE)
    message["k"]["x"] = True
    return message


class _FakeSocket:
    """Scripted stand-in for a `websockets.sync.client.ClientConnection`.

    Satisfies the module's `SocketLike` protocol structurally, so the real socket
    loop — reconnect, skip, stop — is exercised with no socket and no network. A
    frame may be an exception instance, which `recv` then raises.
    """

    def __init__(self, frames: list[object]) -> None:
        self._frames = frames
        self.received = 0
        self.closed = False

    def __enter__(self) -> _FakeSocket:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.closed = True

    def recv(self) -> str:
        frame = self._frames.pop(0)
        self.received += 1
        if isinstance(frame, BaseException):
            raise frame
        return str(frame)

    def close(self) -> None:
        self.closed = True


def _never_connect(url: str) -> SocketLike:
    raise AssertionError(f"a unit test must not open a socket ({url})")


def _unexpected_sleep(seconds: float) -> None:
    raise AssertionError(f"the stream slept {seconds}s where no reconnect was expected")


def test_open_candle_emits_nothing_so_a_forming_bar_cannot_leak_lookahead() -> None:
    """`k.x == false` is the lookahead guard: the bar's high/low/close still move."""
    assert parse_kline_message(OPEN_KLINE_MESSAGE) is None


def test_closed_candle_maps_payload_fields_to_decimal_bar() -> None:
    bar = parse_kline_message(_closed_message())

    assert bar is not None
    assert bar.instrument_id == "ETH/USDT.SIM"
    # `k.t` (open time) is the bar's timestamp, not `k.T` (close time).
    assert bar.ts_utc == CLOSE_TIME_UTC
    assert bar.ts_utc.tzinfo is not None
    assert bar.ts_utc.utcoffset() == CLOSE_TIME_UTC.utcoffset()
    assert (bar.open, bar.high, bar.low, bar.close, bar.volume) == (
        Decimal("293.78000000"),
        Decimal("293.96000000"),
        Decimal("293.78000000"),
        Decimal("293.90000000"),
        Decimal("85.98300000"),
    )
    # Money is never float in this project, and the payload's text form must survive
    # verbatim rather than round-trip through binary floating point.
    assert all(
        isinstance(value, Decimal) for value in (bar.open, bar.high, bar.low, bar.close, bar.volume)
    )


def test_closed_bar_passes_the_project_bar_validator() -> None:
    """The parser output is a domain bar; the project's own validator must accept it."""
    bar = parse_kline_message(_closed_message())

    assert bar is not None
    validate_bar(bar, now=datetime(2019, 6, 29, tzinfo=UTC))
    assert isinstance(bar, OhlcvBar)


def test_taker_buy_volume_matches_the_batch_ingest_field_nine() -> None:
    """`k.V` is the maker/taker split: field 9 of `/api/v3/klines`, same quantity.

    This is what lets the live stream and the ingested catalog feed the same
    order-flow features without a tick-rule proxy. The check is cross-path on
    purpose: the two parsers must not drift apart.
    """
    live = parse_kline_message(_closed_message())
    # REST row for the identical candle: [open, o, h, l, c, v, close, q, n, V, Q, B].
    batch = parse_binance_kline(
        [
            1561737540000,
            "293.78000000",
            "293.96000000",
            "293.78000000",
            "293.90000000",
            "85.98300000",
            1561737599999,
            "25275.72000000",
            42,
            "50.00000000",
            "14700.00000000",
            "0",
        ],
        instrument_id="ETH/USDT.SIM",
    )

    assert live is not None
    assert live.taker_buy_base_volume == batch.taker_buy_base_volume == Decimal("50.00000000")


def test_missing_taker_buy_field_stays_unknown_not_zero() -> None:
    """A trimmed payload cannot answer "how much did takers buy?" — None, never 0."""
    message = _closed_message()
    del message["k"]["V"]

    bar = parse_kline_message(message)

    assert bar is not None
    assert bar.taker_buy_base_volume is None


def test_malformed_kline_frame_raises_a_named_error() -> None:
    """Structural breakage raises `KlinePayloadError`; only "no closed bar" is None.

    Silence would be indistinguishable from a quiet market, so a corrupt frame is an
    error here; the socket loop logs and skips it (see the loop test below).
    """
    missing_field = _closed_message()
    del missing_field["k"]["c"]
    with pytest.raises(KlinePayloadError, match="missing required field 'c'"):
        parse_kline_message(missing_field)

    not_a_number = _closed_message()
    not_a_number["k"]["o"] = "not a price"
    with pytest.raises(KlinePayloadError, match="not a decimal number"):
        parse_kline_message(not_a_number)

    unknown_symbol = _closed_message()
    unknown_symbol["k"]["s"] = "ETHBTC"
    with pytest.raises(KlinePayloadError, match="unsupported binance symbol"):
        parse_kline_message(unknown_symbol)

    non_finite = _closed_message()
    non_finite["k"]["h"] = "NaN"
    # `Decimal("NaN")` slips past every comparison in validate_bar, so it needs its own
    # guard rather than relying on the bar invariants.
    with pytest.raises(KlinePayloadError, match="must be finite"):
        parse_kline_message(non_finite)

    closure_unknown = _closed_message()
    del closure_unknown["k"]["x"]
    with pytest.raises(KlinePayloadError, match="'x' must be a boolean"):
        parse_kline_message(closure_unknown)

    not_an_object: object = ["kline", "but", "a", "list"]
    with pytest.raises(KlinePayloadError, match="must be a JSON object"):
        parse_kline_message(not_an_object)


def test_inconsistent_candle_is_rejected_by_the_project_validator() -> None:
    """A high below the open is a bad bar, and the parser runs the project's check."""
    inverted = _closed_message()
    inverted["k"]["h"] = "290.00000000"

    with pytest.raises(InvalidBarError, match="high must be"):
        parse_kline_message(inverted)


def test_parser_rejects_a_bar_that_is_in_the_future_for_the_injected_clock() -> None:
    """The clock is a seam, so the future-bar guard is testable instead of implicit."""
    with pytest.raises(InvalidBarError, match="future"):
        parse_kline_message(_closed_message(), now=datetime(2019, 1, 1, tzinfo=UTC))


def test_subscription_ack_and_foreign_events_carry_no_bar() -> None:
    assert parse_kline_message({"result": None, "id": 1}) is None
    assert parse_kline_message({"e": "depthUpdate", "s": "ETHUSDT"}) is None


def test_combined_stream_wrapper_is_unwrapped() -> None:
    """The combined endpoint wraps each event; the same parser must read it."""
    frame = {"stream": "ethusdt@kline_1m", "data": _closed_message()}

    bar = parse_kline_message(frame)

    assert bar is not None
    assert bar.instrument_id == "ETH/USDT.SIM"


def test_reconnect_backoff_is_non_zero_monotonic_and_bounded() -> None:
    """The reconnect ladder must never be zero (that is a tight loop) nor unbounded."""
    policy = ReconnectPolicy(base_delay_seconds=0.5, max_delay_seconds=30.0, factor=2.0)

    delays = [policy.delay_seconds(failure) for failure in range(1, 12)]

    assert all(delay > 0 for delay in delays)
    assert delays == sorted(delays)
    assert delays[:4] == [0.5, 1.0, 2.0, 4.0]
    assert max(delays) == 30.0
    # A long outage must not overflow the float (`2.0 ** 1030` raises OverflowError).
    assert policy.delay_seconds(10_000) == policy.max_delay_seconds


def test_reconnect_policy_refuses_a_zero_delay() -> None:
    with pytest.raises(ValueError, match="tight loop"):
        ReconnectPolicy(base_delay_seconds=0.0)
    with pytest.raises(ValueError, match="must be >= 1"):
        ReconnectPolicy().delay_seconds(0)


def test_stream_url_is_lowercase_and_interval_is_validated_up_front() -> None:
    stream = BinanceKlineStream("ethusdt", "1h", connect_fn=_never_connect)

    assert stream.stream_url == "wss://stream.binance.com:9443/ws/ethusdt@kline_1h"
    assert stream.instrument_id == "ETH/USDT.SIM"
    with pytest.raises(ValueError, match="unsupported kline interval"):
        BinanceKlineStream("ETHUSDT", "7m", connect_fn=_never_connect)
    with pytest.raises(ValueError, match="unsupported binance symbol"):
        BinanceKlineStream("ETHBTC", connect_fn=_never_connect)


def test_stream_loop_yields_only_closed_bars_and_stops_cleanly() -> None:
    """The socket loop emits the closed candle, drops the open one, and stops.

    No socket is involved: the connector is injected, so this is the real loop code
    running against a scripted connection.
    """
    socket = _FakeSocket([json.dumps(OPEN_KLINE_MESSAGE), json.dumps(_closed_message())])
    stream = BinanceKlineStream(
        "ETHUSDT", "1m", connect_fn=lambda _url: socket, sleep=_unexpected_sleep
    )

    bars = stream.bars()
    bar = next(bars)

    assert bar.ts_utc == CLOSE_TIME_UTC
    assert bar.close == Decimal("293.90000000")

    stream.stop()
    # A stopped stream drains to nothing instead of reconnecting for another bar.
    assert list(bars) == []
    assert socket.closed
    assert socket.received == 2


def test_stream_backs_off_between_reconnects_and_gives_up_loudly() -> None:
    delays: list[float] = []
    policy = ReconnectPolicy(
        base_delay_seconds=0.5, max_delay_seconds=2.0, max_consecutive_failures=3
    )

    def failing_connect(_url: str) -> SocketLike:
        raise OSError("connection reset by peer")

    stream = BinanceKlineStream(
        "ETHUSDT", "1m", policy=policy, connect_fn=failing_connect, sleep=delays.append
    )

    with pytest.raises(KlineStreamUnavailableError, match="consecutive failures"):
        list(stream.bars())

    # Three waits, each strictly positive and inside the cap, then a loud stop rather
    # than an endless retry loop that looks alive.
    assert delays == [0.5, 1.0, 2.0]


def test_duplicate_closed_bar_is_read_but_never_yielded_twice() -> None:
    socket = _FakeSocket(
        [
            json.dumps(_closed_message()),
            json.dumps(_closed_message()),
            RuntimeError("fake connection exhausted"),
        ]
    )
    stream = BinanceKlineStream("ETHUSDT", "1m", connect_fn=lambda _url: socket)

    yielded: list[OhlcvBar] = []
    bars = stream.bars()

    # The fake connection fails with a non-transport error once it runs dry: that is
    # not a reconnect case, so it propagates and ends the loop here.
    def drain() -> None:
        while True:
            yielded.append(next(bars))

    with pytest.raises(RuntimeError, match="fake connection exhausted"):
        drain()

    # The repeated bar was parsed and dropped: a strategy must not see the same bar
    # twice, which would double-count volume and re-fire an already-acted-on signal.
    assert socket.received == 3
    assert len(yielded) == 1
