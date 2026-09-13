from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.errors import InvalidWindowError


@dataclass(frozen=True, slots=True)
class WalkForwardWindow:
    """In-sample is for parameter selection only. Out-of-sample is the report.

    Bounds are UTC and half-open: start inclusive, end exclusive. The in-sample
    end must not be after the out-of-sample start (a purge gap is allowed).
    """

    in_sample_start: datetime
    in_sample_end: datetime
    out_of_sample_start: datetime
    out_of_sample_end: datetime

    def __post_init__(self) -> None:
        _require_utc(self.in_sample_start, "in_sample_start")
        _require_utc(self.in_sample_end, "in_sample_end")
        _require_utc(self.out_of_sample_start, "out_of_sample_start")
        _require_utc(self.out_of_sample_end, "out_of_sample_end")
        if self.in_sample_start >= self.in_sample_end:
            raise InvalidWindowError("in-sample start must be before in-sample end")
        if self.out_of_sample_start >= self.out_of_sample_end:
            raise InvalidWindowError("out-of-sample start must be before out-of-sample end")
        if self.in_sample_end > self.out_of_sample_start:
            raise InvalidWindowError("in-sample must not overlap out-of-sample")


@dataclass(frozen=True, slots=True)
class WalkForwardSplit:
    in_sample: tuple[OhlcvBar, ...]
    out_of_sample: tuple[OhlcvBar, ...]


def bars_in_range(
    bars: Sequence[OhlcvBar],
    *,
    start: datetime,
    end: datetime,
) -> tuple[OhlcvBar, ...]:
    """Closed-bar slice `[start, end)`. No look-ahead into `end`."""
    _require_utc(start, "start")
    _require_utc(end, "end")
    if start >= end:
        raise InvalidWindowError("range start must be before end")
    return tuple(bar for bar in bars if start <= bar.ts_utc < end)


def split_by_window(bars: Sequence[OhlcvBar], window: WalkForwardWindow) -> WalkForwardSplit:
    in_sample = bars_in_range(bars, start=window.in_sample_start, end=window.in_sample_end)
    out_of_sample = bars_in_range(
        bars, start=window.out_of_sample_start, end=window.out_of_sample_end
    )
    if not in_sample:
        raise InvalidWindowError("in-sample fold has no bars")
    if not out_of_sample:
        raise InvalidWindowError("out-of-sample fold has no bars")
    if in_sample[-1].ts_utc >= out_of_sample[0].ts_utc:
        raise InvalidWindowError("folds overlap after slicing")
    return WalkForwardSplit(in_sample=in_sample, out_of_sample=out_of_sample)


def anchored_window(
    bars: Sequence[OhlcvBar],
    *,
    in_sample_fraction: Decimal,
) -> WalkForwardWindow:
    """First `in_sample_fraction` of bars for selection, remainder for the report."""
    if in_sample_fraction <= 0 or in_sample_fraction >= 1:
        raise InvalidWindowError("in_sample_fraction must be in (0, 1)")
    if len(bars) < 2:
        raise InvalidWindowError("need at least 2 bars to split")
    split_at = int((Decimal(len(bars)) * in_sample_fraction).to_integral_value(rounding=ROUND_DOWN))
    if split_at < 1 or split_at >= len(bars):
        raise InvalidWindowError("anchored split leaves an empty fold")
    ordered = tuple(bars)
    last = ordered[-1]
    return WalkForwardWindow(
        in_sample_start=ordered[0].ts_utc,
        in_sample_end=ordered[split_at].ts_utc,
        out_of_sample_start=ordered[split_at].ts_utc,
        out_of_sample_end=last.ts_utc + timedelta(microseconds=1),
    )


def _require_utc(ts: datetime, name: str) -> None:
    if ts.tzinfo is None:
        raise InvalidWindowError(f"{name} must be timezone-aware UTC")
    if ts.utcoffset() != timedelta(0):
        raise InvalidWindowError(f"{name} must be UTC")
