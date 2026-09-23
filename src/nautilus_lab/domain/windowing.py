"""Cut event series (ticks, book snapshots) to the span a list of bars covers.

Bars carry their CLOSE time. A run over bars `b0..bn` therefore covers the interval
`(b0.close - step, bn.close]`, where `step` is the bar spacing. Events outside that
interval do not belong to the run: before, they warm a filter on history the run is
not about; after, they are the future — an in-sample run that is handed the
out-of-sample ticks keeps the engine running past its last bar and lets the filter
state absorb data the selection was supposed to be blind to.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Protocol

from nautilus_lab.domain.bars import OhlcvBar


class _Timestamped(Protocol):
    @property
    def ts_utc(self) -> datetime: ...


def bar_span(bars: Sequence[OhlcvBar]) -> tuple[datetime, datetime] | None:
    """(exclusive start, inclusive end) the bars cover, or None for no bars."""
    if not bars:
        return None
    end = bars[-1].ts_utc
    step = bars[1].ts_utc - bars[0].ts_utc if len(bars) >= 2 else timedelta(0)
    return bars[0].ts_utc - step, end


def within_bars[EventT: _Timestamped](
    events: Sequence[EventT], bars: Sequence[OhlcvBar]
) -> list[EventT]:
    """Events whose timestamp falls inside `bar_span(bars)`. No bars -> no events."""
    span = bar_span(bars)
    if span is None:
        return []
    start, end = span
    return [event for event in events if start < event.ts_utc <= end]


def warmup_tail(
    history: Sequence[OhlcvBar], window: Sequence[OhlcvBar], count: int
) -> list[OhlcvBar]:
    """The `count` bars of `history` that close right before `window` starts.

    An out-of-sample run used to start cold: a regime robot spends its first ~150 bars
    warming indicators, so a quarter of a short fold was silently not traded. These
    bars are known at the window's start (they close before it), so feeding them to the
    indicators — while forbidding trades until the window opens — leaks nothing.
    """
    if count <= 0 or not window:
        return []
    start = window[0].ts_utc
    before = [bar for bar in history if bar.ts_utc < start]
    return before[-count:]
