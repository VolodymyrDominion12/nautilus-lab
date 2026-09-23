"""Live closed-bar source: Binance spot WebSocket klines.

Paper mode needs a bar stream that is both *real* and *safe to look at*. Two
properties matter more than throughput here:

* **only closed bars leave this module.** A forming candle carries `k.x == false`;
  its high, low and close still move, so a strategy that reads it is reading the
  future of the bar it trades. The guard lives in `parse_kline_message`, returns
  `None` for that message, and is the invariant every test in
  `tests/unit/test_binance_ws.py` leans on.
* **a dropped socket is routine, not fatal.** The loop reconnects with a bounded,
  strictly positive exponential backoff, so a Binance outage or a local network
  blip cannot turn into a tight reconnect loop — the pattern the exchange answers
  with an IP ban.

Scope is public market data only: no API keys, no signed request, no order path,
nothing that could submit anything. That is why the endpoint is `wss://stream.
binance.com:9443/ws` and not a user-data stream.

Parsing is a module-level pure function so it can be tested with real payload
fixtures and no socket; `BinanceKlineStream` is a thin loop around it, and every
seam it touches (connector, sleep, clock) is injectable.
"""

from __future__ import annotations

import json
import logging
import math
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from types import TracebackType
from typing import Protocol

from websockets.exceptions import WebSocketException
from websockets.sync.client import connect

from nautilus_lab.domain.bars import OhlcvBar, validate_bar
from nautilus_lab.domain.errors import InvalidBarError
from nautilus_lab.infrastructure.nautilus.instrument import binance_symbol_to_instrument_id

BINANCE_WS_BASE_URL = "wss://stream.binance.com:9443/ws"

# Intervals Binance serves for klines. Validated up front so a typo fails in the
# constructor with a named cause instead of opening a socket that Binance answers
# with an error frame (or, worse, with a silent subscription to nothing).
_VALID_INTERVALS = frozenset(
    {
        "1s",
        "1m",
        "3m",
        "5m",
        "15m",
        "30m",
        "1h",
        "2h",
        "4h",
        "6h",
        "8h",
        "12h",
        "1d",
        "3d",
        "1w",
        "1M",
    }
)

# Exponential growth saturates here: `2.0 ** 1030` raises OverflowError, and a long
# outage must produce a number, never an exception out of the backoff ladder.
_LOG_SATURATION = 64.0

_RETRYABLE_ERRORS = (WebSocketException, OSError)


class KlinePayloadError(ValueError):
    """A message claimed to be a kline event but cannot be read as one.

    Raised instead of returning `None`, because `None` already means "this message
    carries no closed bar" (a still-forming candle, a subscription ack, a different
    event type). Reusing it for a corrupt frame would make a broken feed
    indistinguishable from a quiet market, which is exactly the failure mode that
    hides for days. The socket loop logs and skips these so one bad frame cannot
    kill a live feed, but the pure parser fails loudly so a test sees it.
    """


class KlineStreamUnavailableError(RuntimeError):
    """The stream failed too many times in a row and gave up.

    Fail closed rather than retrying forever: an endless ladder at the cap looks
    healthy from the outside while no bar ever arrives, and a strategy judging a
    stale last price is a worse outcome than a loud stop.
    """


@dataclass(frozen=True, slots=True)
class ReconnectPolicy:
    """Bounded exponential backoff for a dropped stream.

    The floor is strictly positive on purpose: `base_delay_seconds = 0` is a tight
    reconnect loop, which Binance treats as abuse. `max_consecutive_failures` turns a
    *permanent* fault (unknown symbol, blocked network) into a named exception
    instead of a retry loop that never delivers a bar.
    """

    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 30.0
    factor: float = 2.0
    max_consecutive_failures: int = 10

    def __post_init__(self) -> None:
        if self.base_delay_seconds <= 0:
            raise ValueError("base_delay_seconds must be > 0: a zero floor is a tight loop")
        if self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("max_delay_seconds must be >= base_delay_seconds")
        if self.factor < 1:
            raise ValueError("factor must be >= 1")
        if self.max_consecutive_failures < 1:
            raise ValueError("max_consecutive_failures must be >= 1")

    def delay_seconds(self, failure: int) -> float:
        """Seconds to wait before retry number `failure` (1-based).

        Always `> 0` and never above `max_delay_seconds`, so the caller can sleep on
        it unconditionally.
        """
        if failure < 1:
            raise ValueError("failure must be >= 1")
        exponent = failure - 1
        if exponent * math.log(self.factor) > _LOG_SATURATION:
            return self.max_delay_seconds
        return min(self.max_delay_seconds, self.base_delay_seconds * self.factor**exponent)


class SocketLike(Protocol):
    """The slice of `websockets.sync.client.ClientConnection` this module uses.

    Narrowing to these four members is what makes the socket loop testable: a fake
    connection in `tests/unit/test_binance_ws.py` satisfies this protocol without a
    socket, and the real client satisfies it structurally (checked by mypy).
    """

    def __enter__(self) -> SocketLike: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...

    def recv(self) -> str | bytes: ...

    def close(self) -> None: ...


ConnectFn = Callable[[str], SocketLike]


def binance_stream_url(symbol: str, interval: str, *, base_url: str = BINANCE_WS_BASE_URL) -> str:
    """Single-stream URL for one symbol's klines, e.g. `.../ethusdt@kline_1m`.

    Binance stream names are lowercase; an uppercase name is accepted by the server
    as a subscription to *nothing*, which is a silent stall rather than an error.
    """
    return f"{base_url.rstrip('/')}/{symbol.strip().lower()}@kline_{interval}"


def parse_kline_message(payload: object, *, now: datetime | None = None) -> OhlcvBar | None:
    """Map one raw stream message to a closed `OhlcvBar`, or `None` if there is none.

    `None` is returned for the two shapes that legitimately carry no closed bar:
    a frame that is not a kline event (combined-stream subscription ack), and a
    kline whose `k.x` is false — the candle is still forming, so emitting it would
    be lookahead.

    `KlinePayloadError` is raised for a kline event that is structurally broken or
    internally inconsistent: missing field, unparsable number, non-boolean `x`,
    unsupported symbol, non-finite price, or a bar that `validate_bar` rejects.

    `ts_utc` is the candle **close** time (`k.T`), matching the batch ingest
    (`binance_klines.py` anchors on field 6, the close time) and Nautilus' own
    convention that a bar's event time is its close. Latest-first anchoring here would
    silently mis-join the two series by one interval — the taker-flow catalog is keyed
    on this same timestamp, so a live bar would pick up its neighbour's flow.

    `now` is the clock `validate_bar` uses for its future-bar check; inject it to
    keep a test deterministic instead of implicitly depending on the wall clock.
    """
    message = _as_message(payload)
    if message.get("e") != "kline":
        return None

    kline = message.get("k")
    if not isinstance(kline, Mapping):
        raise KlinePayloadError(f"kline event without a 'k' object: {_summarise(message)}")

    closed = kline.get("x")
    if not isinstance(closed, bool):
        # Never guess: "unknown closure state" must not be read as either answer, so
        # it is an error rather than an emitted bar.
        raise KlinePayloadError(f"kline field 'x' must be a boolean, got {closed!r}")
    if not closed:
        return None

    symbol = kline.get("s") if kline.get("s") is not None else message.get("s")
    if not isinstance(symbol, str) or not symbol:
        raise KlinePayloadError(f"kline payload carries no symbol: {_summarise(message)}")
    try:
        instrument_id = binance_symbol_to_instrument_id(symbol.upper())
    except ValueError as exc:
        raise KlinePayloadError(f"unsupported binance symbol {symbol!r}: {exc}") from exc

    # Binance kline field map (`@kline_<interval>`, spot stream):
    #   t / T  open / close time in ms        o c h l  OHLC as decimal strings
    #   v      total base volume              q        total quote volume
    #   V      taker BUY base volume          Q        taker buy quote volume
    #   n      trade count                    x        is this kline closed
    #   f / L  first / last trade id          B        documented as "ignore"
    #
    # Uppercase `V` — not `v` — is the maker/taker split, i.e. exactly what the batch
    # path reads as field index 9 of `api/v3/klines` (`takerBuyBaseAssetVolume`). The
    # worked example is decisive: v=85.983, V=50.0, q=25275.72, Q=14700.0 give
    # V/v = Q/q = 0.5815, which only holds if V and Q are the buy side of the *same*
    # bar. So the live and catalog series carry the same flow semantics, and
    # `taker_buy_base_volume` never needs the tick-rule proxy.
    taker_raw = kline.get("V")
    bar = OhlcvBar(
        instrument_id=instrument_id,
        # Close time, not open time: see the docstring — the catalog series is keyed on
        # the close, and a one-interval offset would mis-join the taker-flow series.
        ts_utc=_ms_to_utc(_int_field(kline, "T")),
        open=_decimal_field(kline, "o"),
        high=_decimal_field(kline, "h"),
        low=_decimal_field(kline, "l"),
        close=_decimal_field(kline, "c"),
        volume=_decimal_field(kline, "v"),
        # Absent `V` (an older or trimmed payload shape) stays None: unknown, never
        # zero. Zero would read as "no aggressive buying", a different observation.
        taker_buy_base_volume=None if taker_raw is None else _to_decimal(taker_raw, "V"),
    )
    validate_bar(bar, now=now)
    return bar


class BinanceKlineStream:
    """Yields closed klines from Binance's public spot WebSocket until stopped.

    Synchronous on purpose: paper mode runs it as one worker thread, and a plain
    generator is far easier to stop (`stop()`) and to fake than an asyncio task
    graph. The connector, the sleep and the clock are injectable, so the message
    loop can be exercised without a socket or a network.
    """

    def __init__(
        self,
        symbol: str,
        interval: str = "1m",
        *,
        base_url: str = BINANCE_WS_BASE_URL,
        policy: ReconnectPolicy | None = None,
        connect_fn: ConnectFn = connect,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        if interval not in _VALID_INTERVALS:
            raise ValueError(
                f"unsupported kline interval {interval!r}; expected one of "
                f"{', '.join(sorted(_VALID_INTERVALS))}"
            )
        normalised = symbol.strip().upper()
        # Fail before opening a socket for a symbol this lab cannot map to an
        # instrument id: the mapping is the only place a symbol becomes a bar.
        self._instrument_id = binance_symbol_to_instrument_id(normalised)
        self._symbol = normalised
        self._interval = interval
        self._url = binance_stream_url(normalised, interval, base_url=base_url)
        self._policy = policy or ReconnectPolicy()
        self._connect = connect_fn
        self._sleep = sleep
        self._now = now or (lambda: datetime.now(UTC))
        self._logger = logger or logging.getLogger(type(self).__name__)
        self._stopped = False
        self._socket: SocketLike | None = None

    @property
    def symbol(self) -> str:
        """Uppercase Binance symbol, e.g. `ETHUSDT`."""
        return self._symbol

    @property
    def interval(self) -> str:
        """Kline interval as sent to Binance, e.g. `1m`."""
        return self._interval

    @property
    def instrument_id(self) -> str:
        """Project instrument id the stream's bars are labelled with."""
        return self._instrument_id

    @property
    def stream_url(self) -> str:
        """Exact WebSocket URL this stream connects to."""
        return self._url

    def bars(self) -> Iterator[OhlcvBar]:
        """Yield closed bars, reconnecting on transport failure until `stop()`.

        Only two things can end the loop: `stop()`, or `KlineStreamUnavailableError`
        after `max_consecutive_failures` failed connections in a row (the failure
        counter is reset by any bar that actually arrives, so a long-lived stream
        that drops once is not punished with the capped delay later).
        """
        failures = 0
        last_ts: datetime | None = None
        while not self._stopped:
            try:
                with self._connect(self._url) as socket:
                    self._socket = socket
                    self._logger.info("connected to %s", self._url)
                    while not self._stopped:
                        bar = self._next_bar(socket)
                        if bar is None:
                            continue
                        if last_ts is not None and bar.ts_utc <= last_ts:
                            # A repeated or rewound bar must not reach a strategy: it
                            # would double-count volume and re-fire a signal on a bar
                            # that was already acted on.
                            self._logger.warning(
                                "skipping non-increasing bar %s (last %s) on %s",
                                bar.ts_utc.isoformat(),
                                last_ts.isoformat(),
                                self._url,
                            )
                            continue
                        failures = 0
                        last_ts = bar.ts_utc
                        yield bar
            except _RETRYABLE_ERRORS as exc:
                if self._stopped:
                    break
                failures += 1
                if failures > self._policy.max_consecutive_failures:
                    raise KlineStreamUnavailableError(
                        f"{self._url}: {failures} consecutive failures, last: {exc}. "
                        "Fail closed: a silent retry loop with no bars looks alive."
                    ) from exc
                delay = self._policy.delay_seconds(failures)
                self._logger.warning(
                    "stream %s dropped (%s); retry %d/%d in %.1fs",
                    self._url,
                    exc,
                    failures,
                    self._policy.max_consecutive_failures,
                    delay,
                )
                self._sleep(delay)
            finally:
                self._socket = None

    def stop(self) -> None:
        """End `bars()` and unblock a `recv()` that is already waiting.

        The flag alone is not enough. `recv()` blocks until Binance sends something —
        for a 1m kline that is up to a minute — so a caller stopping between bars
        would hang in the socket instead of returning. Closing the socket from this
        thread makes the pending `recv()` raise, and the loop then sees the flag and
        exits (this is the documented way to interrupt the sync client).
        """
        self._stopped = True
        socket, self._socket = self._socket, None
        if socket is None:
            return
        try:
            socket.close()
        except (OSError, WebSocketException) as exc:
            self._logger.debug("closing %s raised %s (already gone)", self._url, exc)

    def __enter__(self) -> BinanceKlineStream:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.stop()

    def _next_bar(self, socket: SocketLike) -> OhlcvBar | None:
        """Read and parse one frame; an unusable frame is logged, not fatal.

        A live feed must survive one corrupt or unexpected frame — dropping the whole
        connection would cost the caller every bar until the next reconnect, while the
        warning keeps the degradation visible.
        """
        raw = socket.recv()
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._logger.warning("skipping non-JSON frame from %s: %s", self._url, exc)
            return None
        try:
            return parse_kline_message(payload, now=self._now())
        except (KlinePayloadError, InvalidBarError) as exc:
            self._logger.warning("skipping unusable kline frame from %s: %s", self._url, exc)
            return None


def _as_message(payload: object) -> Mapping[str, object]:
    """Unwrap a combined-stream frame and reject anything that is not an object.

    The combined endpoint (`/stream?streams=...`) wraps every event as
    `{"stream": ..., "data": {...}}`; the single-stream endpoint does not. Unwrapping
    here rather than in the socket loop keeps both endpoints on one tested path.
    """
    message: object = payload
    if isinstance(message, Mapping):
        data = message.get("data")
        if isinstance(data, Mapping):
            message = data
    if not isinstance(message, Mapping):
        raise KlinePayloadError(
            f"stream message must be a JSON object, got {type(payload).__name__}"
        )
    return {str(key): value for key, value in message.items()}


def _int_field(kline: Mapping[str, object], name: str) -> int:
    """Integer field, accepting either a JSON number or Binance's string form."""
    raw = _raw_field(kline, name)
    try:
        return int(str(raw))
    except ValueError as exc:
        raise KlinePayloadError(f"kline field {name!r} is not an integer: {raw!r}") from exc


def _decimal_field(kline: Mapping[str, object], name: str) -> Decimal:
    return _to_decimal(_raw_field(kline, name), name)


def _raw_field(kline: Mapping[str, object], name: str) -> object:
    if name not in kline:
        raise KlinePayloadError(f"kline payload is missing required field {name!r}")
    return kline[name]


def _to_decimal(raw: object, name: str) -> Decimal:
    """Decimal from a JSON string/number, rejecting the two values `Decimal` allows
    but the domain does not: a non-finite one.

    `Decimal("NaN")` survives every comparison in `validate_bar` (each `<` with NaN is
    False), so it would slip past the bar invariants and only detonate inside a
    strategy's arithmetic, far from the cause.
    """
    try:
        value = Decimal(str(raw))
    except InvalidOperation as exc:
        raise KlinePayloadError(f"kline field {name!r} is not a decimal number: {raw!r}") from exc
    if not value.is_finite():
        raise KlinePayloadError(f"kline field {name!r} must be finite: {raw!r}")
    return value


def _ms_to_utc(epoch_ms: int) -> datetime:
    """Binance millisecond epoch to an aware UTC datetime."""
    return datetime.fromtimestamp(epoch_ms / 1000, tz=UTC)


def _summarise(payload: object) -> str:
    text = str(payload)
    return text if len(text) <= 200 else f"{text[:200]}..."


__all__ = [
    "BINANCE_WS_BASE_URL",
    "BinanceKlineStream",
    "KlinePayloadError",
    "KlineStreamUnavailableError",
    "ReconnectPolicy",
    "SocketLike",
    "binance_stream_url",
    "parse_kline_message",
]
