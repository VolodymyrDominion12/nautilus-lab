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
