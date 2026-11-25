"""Data-quality checks for a stored bar series (docs/34, P1 "QC").

`validate_bar` guards one bar against look-ahead and inverted candles. It cannot see
what is *missing* or *suspicious across bars*: a hole in the series, a run of
zero-volume days, a 10x jump where a ticker was re-used by a different coin. These
checks look at the whole series and return findings; a series with a `FAIL` status
should not feed a backtest until someone has looked at it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.calendar import (
    TradingCalendar,
    count_expected_bars_between,
)


class QualityStatus(StrEnum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class Gap:
    """Bars missing between two stored closes: `(after, before)` exclusive."""

    after: datetime
    before: datetime
    missing_bars: int


@dataclass(frozen=True, slots=True)
class Jump:
    ts_utc: datetime
    ratio: Decimal


@dataclass(frozen=True, slots=True)
class RollBoundary:
    """Detected or declared futures contract roll boundary in a continuous series."""

    ts_utc: datetime
    from_contract: str | None = None
    to_contract: str | None = None
    price_jump_pct: Decimal = Decimal("0")
    source: str = "contract_switch"


@dataclass(frozen=True, slots=True)
class QualityThresholds:
    #: |close/prev_close - 1| above this is an extreme move worth a look (50%).
    extreme_return: Decimal = Decimal("0.5")
    #: close/prev_close beyond this factor (either way) after a gap = re-used ticker.
    relisting_ratio: Decimal = Decimal("3")
    #: Share of zero-volume bars above which the series is a warning (dead market).
    zero_volume_warn_share: Decimal = Decimal("0.02")
    #: Share of missing bars above which the series fails.
    missing_fail_share: Decimal = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class QualityReport:
    bars: int
    first: datetime | None
    last: datetime | None
    expected_bars: int
    gaps: tuple[Gap, ...] = ()
    zero_volume: int = 0
    extreme_moves: tuple[Jump, ...] = ()
    #: Big jumps right after a gap: the classic sign of a ticker re-used by a new coin.
    relisting_suspects: tuple[Jump, ...] = ()
    partial_dropped: int = 0
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def missing_bars(self) -> int:
        return sum(gap.missing_bars for gap in self.gaps)

    def status(self, thresholds: QualityThresholds | None = None) -> QualityStatus:
        limits = thresholds or QualityThresholds()
        if self.bars == 0:
            return QualityStatus.FAIL
        if self.relisting_suspects:
            return QualityStatus.FAIL
        expected = max(self.expected_bars, 1)
        if Decimal(self.missing_bars) / Decimal(expected) > limits.missing_fail_share:
            return QualityStatus.FAIL
        if (
            self.gaps
            or self.extreme_moves
            or self.partial_dropped
            or Decimal(self.zero_volume) / Decimal(self.bars) > limits.zero_volume_warn_share
        ):
            return QualityStatus.WARN
        return QualityStatus.OK


def check_bars(
    bars: Sequence[OhlcvBar],
    *,
    interval: timedelta,
    partial_dropped: int = 0,
    thresholds: QualityThresholds | None = None,
    calendar: TradingCalendar = TradingCalendar.CRYPTO_24_7,
    roll_timestamps: frozenset[datetime] = frozenset(),
) -> QualityReport:
    """Inspect a sorted bar series. Pure: reads the bars, decides nothing else."""
    limits = thresholds or QualityThresholds()
    if interval <= timedelta(0):
        raise ValueError("interval must be positive")
    if not bars:
        return QualityReport(
            bars=0, first=None, last=None, expected_bars=0, partial_dropped=partial_dropped
        )
    gaps: list[Gap] = []
    extreme: list[Jump] = []
    relisting: list[Jump] = []
    notes: list[str] = []
    zero_volume = sum(1 for bar in bars if bar.volume == 0)
    for previous, current in pairwise(bars):
        step = current.ts_utc - previous.ts_utc
        if calendar is TradingCalendar.CRYPTO_24_7:
            missing = int(step / interval) - 1 if step > interval else 0
        elif step > interval:
            missing = count_expected_bars_between(
                previous.ts_utc, current.ts_utc, interval=interval, calendar=calendar
            )
        else:
            missing = 0
        after_gap = missing > 0
        if after_gap:
            gaps.append(
                Gap(
                    after=previous.ts_utc,
                    before=current.ts_utc,
                    missing_bars=missing,
                )
            )
        if current.ts_utc in roll_timestamps:
            notes.append(f"roll boundary isolated at {current.ts_utc.isoformat()}")
            continue
        if previous.close <= 0:
            continue
        ratio = current.close / previous.close
        if abs(ratio - 1) > limits.extreme_return:
            extreme.append(Jump(ts_utc=current.ts_utc, ratio=ratio))
        if after_gap and (
            ratio > limits.relisting_ratio or ratio < Decimal(1) / limits.relisting_ratio
        ):
            relisting.append(Jump(ts_utc=current.ts_utc, ratio=ratio))
    if calendar is TradingCalendar.CRYPTO_24_7:
        span = bars[-1].ts_utc - bars[0].ts_utc
        expected_bars = int(span / interval) + 1
    else:
        expected_bars = len(bars) + sum(gap.missing_bars for gap in gaps)
    return QualityReport(
        bars=len(bars),
        first=bars[0].ts_utc,
        last=bars[-1].ts_utc,
        expected_bars=expected_bars,
        gaps=tuple(gaps),
        zero_volume=zero_volume,
        extreme_moves=tuple(extreme),
        relisting_suspects=tuple(relisting),
        partial_dropped=partial_dropped,
        notes=tuple(notes),
    )
