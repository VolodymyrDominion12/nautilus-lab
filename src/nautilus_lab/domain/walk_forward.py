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
    embargo_bars: int = 0,
) -> WalkForwardWindow:
    """First `in_sample_fraction` for selection; remainder for OOS after embargo gap."""
    if in_sample_fraction <= 0 or in_sample_fraction >= 1:
        raise InvalidWindowError("in_sample_fraction must be in (0, 1)")
    if embargo_bars < 0:
        raise InvalidWindowError("embargo_bars must be >= 0")
    if len(bars) < 2:
        raise InvalidWindowError("need at least 2 bars to split")
    split_at = int((Decimal(len(bars)) * in_sample_fraction).to_integral_value(rounding=ROUND_DOWN))
    oos_start_at = split_at + embargo_bars
    if split_at < 1 or oos_start_at >= len(bars):
        raise InvalidWindowError("anchored split leaves an empty fold (check embargo_bars)")
    ordered = tuple(bars)
    last = ordered[-1]
    return WalkForwardWindow(
        in_sample_start=ordered[0].ts_utc,
        in_sample_end=ordered[split_at].ts_utc,
        out_of_sample_start=ordered[oos_start_at].ts_utc,
        out_of_sample_end=last.ts_utc + timedelta(microseconds=1),
    )


def rolling_windows(
    bars: Sequence[OhlcvBar],
    *,
    folds: int,
    in_sample_fraction: Decimal,
    embargo_bars: int = 0,
) -> tuple[WalkForwardWindow, ...]:
    """One window per fold, with the selection window sliding behind each OOS block.

    A single anchored split reports one number from one stretch of history, so it
    cannot separate an edge from luck: the same robot scored +14.9% and -10.1% on two
    different out-of-sample stretches of the same pair of symbols.

    Layout: the first in-sample block spans ``in_sample_fraction`` of the bars, then a
    one-fold embargo gap, then ``folds`` contiguous out-of-sample blocks filling the
    rest. Fold *i* selects on ``[i * per_fold, i * per_fold + in_sample_bars)`` and
    reports on the block that follows it, so the selection window slides forward by
    one OOS block per fold and every fold is a genuine forecast rather than a re-read
    of the same selection data. The last fold absorbs the integer-division remainder,
    so the final window always reaches the most recent bar.
    """
    if folds < 1:
        raise InvalidWindowError("folds must be >= 1")
    if in_sample_fraction <= 0 or in_sample_fraction >= 1:
        raise InvalidWindowError("in_sample_fraction must be in (0, 1)")
    if embargo_bars < 0:
        raise InvalidWindowError("embargo_bars must be >= 0")
    total = len(bars)
    if total < 3:
        raise InvalidWindowError("need at least 3 bars to roll windows")

    ordered = tuple(bars)
    in_sample_bars = int(
        (Decimal(total) * in_sample_fraction).to_integral_value(rounding=ROUND_DOWN)
    )
    per_fold = (total - in_sample_bars - embargo_bars) // folds
    if in_sample_bars < 1 or per_fold < 1:
        raise InvalidWindowError(
            f"{total} bars cannot fill {folds} folds at in_sample_fraction="
            f"{in_sample_fraction} with embargo_bars={embargo_bars}; "
            "use fewer folds, a smaller in_sample_fraction or more bars"
        )

    windows: list[WalkForwardWindow] = []
    last_index = total - 1
    for fold in range(folds):
        is_start = fold * per_fold
        is_end = is_start + in_sample_bars
        oos_start = is_end + embargo_bars
        oos_end = total if fold == folds - 1 else oos_start + per_fold
        # `out_of_sample_end` is exclusive, so a mid-series fold ends exactly on the
        # next bar's open. Only the final fold needs the +1 microsecond, which is what
        # makes the very last bar part of the window at all.
        oos_end_ts = (
            ordered[last_index].ts_utc + timedelta(microseconds=1)
            if oos_end >= total
            else ordered[oos_end].ts_utc
        )
        windows.append(
            WalkForwardWindow(
                in_sample_start=ordered[is_start].ts_utc,
                in_sample_end=ordered[is_end].ts_utc,
                out_of_sample_start=ordered[oos_start].ts_utc,
                out_of_sample_end=oos_end_ts,
            )
        )
    return tuple(windows)


def _require_utc(ts: datetime, name: str) -> None:
    if ts.tzinfo is None:
        raise InvalidWindowError(f"{name} must be timezone-aware UTC")
    if ts.utcoffset() != timedelta(0):
        raise InvalidWindowError(f"{name} must be UTC")
