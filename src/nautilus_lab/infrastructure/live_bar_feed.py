"""Live paper feed: warm up on history, then trade bars as the socket closes them.

A live session needs both halves. Indicators need warm-up bars that already exist, and
the point of the exercise is the bars that arrive *after* the decision to start — so
this feed concatenates the tail of the catalog with closed bars pulled from the public
Binance WebSocket stream.

What it is not: an execution path. Bars arrive here; orders still go nowhere but the
simulated venue, and the same engine, fees and fill model run as in a replay session.
That is deliberate — if the live path filled orders differently, the replay results
would say nothing about it.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from nautilus_lab.application.dtos import BacktestRequest, BarFeed
from nautilus_lab.domain.bars import OhlcvBar


class LiveBarSource(Protocol):
    """Anything that yields closed bars in order and can be stopped."""

    def bars(self) -> Iterator[OhlcvBar]: ...

    def stop(self) -> None: ...


@dataclass(frozen=True, slots=True)
class LiveCollectionResult:
    bars: tuple[OhlcvBar, ...]
    requested: int
    timed_out: bool


@dataclass
class LiveBarCollector:
    """Pull `count` closed bars from a live source, with a deadline.

    Stopping deliberately: the stream is infinite, so the collector stops the source
    as soon as the window is full instead of leaving a socket open behind a
    short-lived process. A deadline turns "the market is quiet" into a reported
    shortfall rather than a hang.
    """

    source: LiveBarSource
    count: int
    timeout_seconds: float
    now: Callable[[], float] = field(default=time.monotonic)
    sleep: Callable[[float], None] = field(default=time.sleep)

    def collect(self) -> LiveCollectionResult:
        if self.count < 1:
            raise ValueError("count must be >= 1")
        deadline = self.now() + self.timeout_seconds
        collected: list[OhlcvBar] = []
        timed_out = False
        try:
            for bar in self.source.bars():
                collected.append(bar)
                if len(collected) >= self.count:
                    break
                if self.now() >= deadline:
                    timed_out = True
                    break
        finally:
            self.source.stop()
        return LiveCollectionResult(
            bars=tuple(collected), requested=self.count, timed_out=timed_out
        )


class SeededLiveBarFeed:
    """`BarFeed` = history tail (warm-up) + bars closed live after that."""

    def __init__(self, *, history: BarFeed, collector: LiveBarCollector, live_bars: int) -> None:
        if live_bars < 1:
            raise ValueError("live_bars must be >= 1")
        self._history = history
        self._collector = collector
        self._live_bars = live_bars

    def load(self, request: BacktestRequest) -> list[OhlcvBar]:
        if request.bar_count <= self._live_bars:
            raise ValueError(
                f"bar_count={request.bar_count} must exceed live_bars={self._live_bars}: "
                "a live session still needs warm-up bars before its first live one"
            )
        history = self._history.load(request)
        result = self._collector.collect()
        if not result.bars:
            raise ValueError(
                f"no closed bars arrived within the collection window "
                f"({self._collector.timeout_seconds:g}s); nothing to run a session on"
            )
        merged = _merge_by_timestamp(history, result.bars)
        return merged[-request.bar_count :]

    def load_multi(self, request: BacktestRequest) -> dict[str, list[OhlcvBar]]:
        # Two-leg live paper would need a synchronised pair of sockets and a decision
        # about what to do when one leg goes quiet. Refusing beats faking it.
        raise ValueError("live paper supports single-instrument robots only")


def _merge_by_timestamp(history: list[OhlcvBar], live: tuple[OhlcvBar, ...]) -> list[OhlcvBar]:
    """History plus live bars, in time order, with no duplicate timestamps.

    A live bar whose timestamp is already in the history replaces it: the socket value
    is the one the session would actually have seen, and a duplicate would corrupt
    every indicator's warm-up.
    """
    by_ts: dict[datetime, OhlcvBar] = {bar.ts_utc: bar for bar in history}
    for bar in live:
        by_ts[bar.ts_utc] = bar
    return [by_ts[key] for key in sorted(by_ts)]
