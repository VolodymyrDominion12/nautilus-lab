from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.signals import SignalSide


class BarrierTouch(StrEnum):
    PROFIT = "profit"
    STOP = "stop"
    VERTICAL = "vertical"


@dataclass(frozen=True, slots=True)
class TripleBarrierConfig:
    """Volatility-scaled take-profit / stop-loss plus a holding-time cap.

    Distances are multiples of close-to-close return volatility at the event,
    not fixed percentages, so the same config applies in quiet and violent regimes.
    """

    profit_multiple: Decimal = Decimal("2")
    stop_multiple: Decimal = Decimal("1")
    horizon: int = 5

    def __post_init__(self) -> None:
        if self.profit_multiple <= 0 or self.stop_multiple <= 0:
            raise ValueError("barrier multiples must be > 0")
        if self.horizon < 1:
            raise ValueError("horizon must be >= 1")


@dataclass(frozen=True, slots=True)
class TripleBarrierOutcome:
    touch: BarrierTouch
    label: int
    bars_held: int
    exit_price: Decimal
    return_fraction: Decimal
    profit_level: Decimal
    stop_level: Decimal

    @property
    def is_win(self) -> bool:
        return self.touch is BarrierTouch.PROFIT


def rolling_volatility(
    bars: Sequence[OhlcvBar],
    index: int,
    *,
    window: int,
) -> Decimal | None:
    """Sample std of `window` close-to-close returns ending at `index`. None if degenerate."""
    if window < 2 or index < window or index >= len(bars):
        return None
    closes = [bar.close for bar in bars[: index + 1]]
    returns: list[Decimal] = []
    for pos in range(len(closes) - window, len(closes)):
        previous = closes[pos - 1]
        if previous <= 0:
            return None
        returns.append((closes[pos] - previous) / previous)
    if len(returns) < 2:
        return None
    mean = sum(returns, Decimal("0")) / Decimal(len(returns))
    variance = sum((item - mean) ** 2 for item in returns) / Decimal(len(returns) - 1)
    if variance <= 0:
        return None
    return variance.sqrt()


def label_triple_barrier(
    bars: Sequence[OhlcvBar],
    entry_index: int,
    *,
    volatility: Decimal,
    config: TripleBarrierConfig,
    side: SignalSide = SignalSide.BUY,
) -> TripleBarrierOutcome | None:
    """Which barrier the *subsequent* path hits first.

    The fill is the close of `entry_index`, so that bar itself is not on the path.
    Incomplete paths (not enough future bars and no hit) return None. If both
    barriers print inside one bar, STOP wins: OHLC has no intra-bar order.
    """
    if side not in (SignalSide.BUY, SignalSide.SELL):
        raise ValueError("triple-barrier labels are defined for BUY or SELL entries only")
    if volatility <= 0:
        raise ValueError("volatility must be > 0")
    if entry_index < 0 or entry_index >= len(bars):
        return None
    entry = bars[entry_index].close
    if entry <= 0:
        return None
    profit_distance = entry * config.profit_multiple * volatility
    stop_distance = entry * config.stop_multiple * volatility
    if side is SignalSide.BUY:
        profit_level = entry + profit_distance
        stop_level = entry - stop_distance
    else:
        profit_level = entry - profit_distance
        stop_level = entry + stop_distance
    if stop_level <= 0:
        return None

    last_needed = entry_index + config.horizon
    last_available = len(bars) - 1
    scan_end = min(last_available, last_needed)
    if scan_end <= entry_index:
        return None

    for index in range(entry_index + 1, scan_end + 1):
        bar = bars[index]
        hit_profit, hit_stop = _touches(
            bar, side=side, profit_level=profit_level, stop_level=stop_level
        )
        held = index - entry_index
        if hit_profit and hit_stop:
            return _outcome(
                BarrierTouch.STOP,
                side=side,
                entry=entry,
                exit_price=stop_level,
                bars_held=held,
                profit_level=profit_level,
                stop_level=stop_level,
            )
        if hit_stop:
            return _outcome(
                BarrierTouch.STOP,
                side=side,
                entry=entry,
                exit_price=stop_level,
                bars_held=held,
                profit_level=profit_level,
                stop_level=stop_level,
            )
        if hit_profit:
            return _outcome(
                BarrierTouch.PROFIT,
                side=side,
                entry=entry,
                exit_price=profit_level,
                bars_held=held,
                profit_level=profit_level,
                stop_level=stop_level,
            )

    if last_available < last_needed:
        return None
    exit_price = bars[last_needed].close
    return _outcome(
        BarrierTouch.VERTICAL,
        side=side,
        entry=entry,
        exit_price=exit_price,
        bars_held=config.horizon,
        profit_level=profit_level,
        stop_level=stop_level,
    )


def _touches(
    bar: OhlcvBar,
    *,
    side: SignalSide,
    profit_level: Decimal,
    stop_level: Decimal,
) -> tuple[bool, bool]:
    if side is SignalSide.BUY:
        return bar.high >= profit_level, bar.low <= stop_level
    return bar.low <= profit_level, bar.high >= stop_level


def _outcome(
    touch: BarrierTouch,
    *,
    side: SignalSide,
    entry: Decimal,
    exit_price: Decimal,
    bars_held: int,
    profit_level: Decimal,
    stop_level: Decimal,
) -> TripleBarrierOutcome:
    labels = {
        BarrierTouch.PROFIT: 1,
        BarrierTouch.STOP: -1,
        BarrierTouch.VERTICAL: 0,
    }
    ret = (exit_price - entry) / entry if side is SignalSide.BUY else (entry - exit_price) / entry
    return TripleBarrierOutcome(
        touch=touch,
        label=labels[touch],
        bars_held=bars_held,
        exit_price=exit_price,
        return_fraction=ret,
        profit_level=profit_level,
        stop_level=stop_level,
    )
