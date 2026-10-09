"""Chandelier Exit — volatility-adaptive trailing stop.

References:
- Chuck LeBeau (1992): "Chandelier Exit" trails a stop from the highest high (longs)
  or lowest low (shorts) over an N-bar lookback, offset by k * ATR.
- Never loosens: the stop only ratchets in the favorable direction as new extremes
  are achieved or volatility contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.errors import InvalidRiskError
from nautilus_lab.domain.signals import SignalSide


@dataclass(frozen=True, slots=True)
class ChandelierParams:
    atr_multiple: Decimal = Decimal("3.0")
    lookback: int = 22

    def __post_init__(self) -> None:
        if self.atr_multiple <= 0:
            raise InvalidRiskError("atr_multiple must be > 0")
        if self.lookback < 1:
            raise InvalidRiskError("lookback must be >= 1")


@dataclass(frozen=True, slots=True)
class ChandelierState:
    entry_price: Decimal
    side: SignalSide
    stop_price: Decimal
    extreme: Decimal


def initial_chandelier(
    *,
    entry_price: Decimal,
    side: SignalSide,
    atr: Decimal,
    params: ChandelierParams,
    lookback_extreme: Decimal | None = None,
) -> ChandelierState:
    """Initialize Chandelier stop at trade entry.

    For longs: anchor to lookback high (or entry price), offset downwards by k * ATR.
    For shorts: anchor to lookback low (or entry price), offset upwards by k * ATR.
    Guarantees positive stop_price and valid distance from entry_price.
    """
    if entry_price <= 0:
        raise InvalidRiskError("entry_price must be > 0")
    if side not in {SignalSide.BUY, SignalSide.SELL}:
        raise InvalidRiskError("chandelier only applies to a long or short entry")
    if atr <= 0:
        raise InvalidRiskError("atr must be > 0")

    offset = params.atr_multiple * atr
    if side is SignalSide.BUY:
        extreme = (
            max(entry_price, lookback_extreme) if lookback_extreme is not None else entry_price
        )
        stop = extreme - offset
        if stop >= entry_price:
            stop = entry_price - offset
        if stop <= 0:
            stop = entry_price * Decimal("0.5")
    else:
        extreme = (
            min(entry_price, lookback_extreme) if lookback_extreme is not None else entry_price
        )
        stop = extreme + offset
        if stop <= entry_price:
            stop = entry_price + offset

    return ChandelierState(
        entry_price=entry_price,
        side=side,
        stop_price=stop,
        extreme=extreme,
    )


def chandelier_hit(state: ChandelierState, price: Decimal) -> bool:
    if price <= 0:
        raise InvalidRiskError("price must be > 0")
    if state.side is SignalSide.BUY:
        return price <= state.stop_price
    return price >= state.stop_price


def update_chandelier(
    state: ChandelierState,
    bar: OhlcvBar,
    atr: Decimal,
    params: ChandelierParams,
    lookback_high: Decimal | None = None,
    lookback_low: Decimal | None = None,
) -> ChandelierState:
    """Update Chandelier stop on closed bar. Never loosens the stop."""
    if atr <= 0:
        raise InvalidRiskError("atr must be > 0")

    offset = params.atr_multiple * atr
    stop = state.stop_price

    if state.side is SignalSide.BUY:
        extreme = max(state.extreme, bar.high)
        if lookback_high is not None:
            extreme = max(extreme, lookback_high)
        candidate = extreme - offset
        if candidate > stop:
            stop = candidate
    else:
        extreme = min(state.extreme, bar.low)
        if lookback_low is not None:
            extreme = min(extreme, lookback_low)
        candidate = extreme + offset
        if candidate < stop:
            stop = candidate

    return ChandelierState(
        entry_price=state.entry_price,
        side=state.side,
        stop_price=stop,
        extreme=extreme,
    )


def step_chandelier(
    state: ChandelierState,
    bar: OhlcvBar,
    atr: Decimal,
    params: ChandelierParams,
    lookback_high: Decimal | None = None,
    lookback_low: Decimal | None = None,
) -> tuple[ChandelierState | None, bool]:
    """Advance one closed bar.

    Returns (None, True) if the adverse price touched the prior stop (stop hit).
    Otherwise returns (updated_state, False).
    """
    adverse = bar.low if state.side is SignalSide.BUY else bar.high
    if chandelier_hit(state, adverse):
        return None, True

    updated = update_chandelier(
        state,
        bar,
        atr,
        params,
        lookback_high=lookback_high,
        lookback_low=lookback_low,
    )
    if chandelier_hit(updated, bar.close):
        return None, True

    return updated, False
