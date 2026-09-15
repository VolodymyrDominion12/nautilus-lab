"""Deterministic stop that the strategy (and any LLM) cannot rewrite.

Two phases, from the Pathia-style DSL engine:
1. Loss protection: the tighter of a percent stop and an ATR stop.
2. Profit locking: once price travels `arm_pct` in favour, the floor only ratchets
   up (long) or down (short). It never gives back locked profit.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.errors import InvalidRiskError
from nautilus_lab.domain.signals import SignalSide


@dataclass(frozen=True, slots=True)
class RatchetParams:
    max_loss_pct: Decimal = Decimal("0.01")
    arm_pct: Decimal = Decimal("0.0125")
    # (trigger_pct, floor_pct) — both measured from entry, favourable direction.
    lock_levels: tuple[tuple[Decimal, Decimal], ...] = (
        (Decimal("0.08"), Decimal("0.04")),
        (Decimal("0.15"), Decimal("0.08")),
    )

    def __post_init__(self) -> None:
        for name, value in (
            ("max_loss_pct", self.max_loss_pct),
            ("arm_pct", self.arm_pct),
        ):
            if value <= 0 or value > 1:
                raise InvalidRiskError(f"{name} must be in (0, 1]")
        previous_trigger = Decimal("0")
        for trigger, floor in self.lock_levels:
            if trigger <= 0 or trigger > 1 or floor < 0 or floor > 1:
                raise InvalidRiskError("lock levels must be fractions in [0, 1]")
            if floor >= trigger:
                raise InvalidRiskError("lock floor must be below its trigger")
            if trigger <= previous_trigger:
                raise InvalidRiskError("lock triggers must increase")
            previous_trigger = trigger


@dataclass(frozen=True, slots=True)
class RatchetState:
    entry_price: Decimal
    side: SignalSide
    stop_price: Decimal
    armed: bool = False


def initial_ratchet(
    *,
    entry_price: Decimal,
    side: SignalSide,
    params: RatchetParams,
    atr_distance: Decimal | None = None,
) -> RatchetState:
    """Start of a trade: the tighter of percent and ATR protective stops."""
    if entry_price <= 0:
        raise InvalidRiskError("entry_price must be > 0")
    if side not in {SignalSide.BUY, SignalSide.SELL}:
        raise InvalidRiskError("ratchet only applies to a long or short entry")
    percent_distance = entry_price * params.max_loss_pct
    distance = percent_distance
    if atr_distance is not None and atr_distance > 0:
        distance = min(distance, atr_distance)
    stop = entry_price - distance if side is SignalSide.BUY else entry_price + distance
    if stop <= 0:
        raise InvalidRiskError("protective stop must stay strictly positive")
    return RatchetState(entry_price=entry_price, side=side, stop_price=stop, armed=False)


def update_ratchet(state: RatchetState, price: Decimal, params: RatchetParams) -> RatchetState:
    """Advance the floor. Never loosens the stop, regardless of later adverse ticks."""
    if price <= 0:
        raise InvalidRiskError("price must be > 0")
    favourable = _favourable_pct(state, price)
    stop = state.stop_price
    armed = state.armed
    if favourable >= params.arm_pct:
        armed = True
        stop = _tighten(state.side, stop, state.entry_price)
    for trigger, floor_pct in params.lock_levels:
        if favourable >= trigger:
            locked = _price_at(state, floor_pct)
            stop = _tighten(state.side, stop, locked)
    return RatchetState(
        entry_price=state.entry_price,
        side=state.side,
        stop_price=stop,
        armed=armed,
    )


def ratchet_hit(state: RatchetState, price: Decimal) -> bool:
    if price <= 0:
        raise InvalidRiskError("price must be > 0")
    if state.side is SignalSide.BUY:
        return price <= state.stop_price
    return price >= state.stop_price


def step_ratchet(
    state: RatchetState,
    bar: OhlcvBar,
    params: RatchetParams,
) -> tuple[RatchetState | None, bool]:
    """Advance one closed bar. `(None, True)` means the stop was hit — flatten.

    The stop that was known *entering* the bar is checked against the adverse
    extreme (low for a long, high for a short). Only if it holds is the floor
    updated from the close. The strategy never sees this; the adapter does.
    """
    adverse = bar.low if state.side is SignalSide.BUY else bar.high
    if ratchet_hit(state, adverse):
        return None, True
    updated = update_ratchet(state, bar.close, params)
    if ratchet_hit(updated, bar.close):
        return None, True
    return updated, False


def _favourable_pct(state: RatchetState, price: Decimal) -> Decimal:
    if state.side is SignalSide.BUY:
        return (price - state.entry_price) / state.entry_price
    return (state.entry_price - price) / state.entry_price


def _price_at(state: RatchetState, floor_pct: Decimal) -> Decimal:
    if state.side is SignalSide.BUY:
        return state.entry_price * (Decimal("1") + floor_pct)
    return state.entry_price * (Decimal("1") - floor_pct)


def _tighten(side: SignalSide, current: Decimal, candidate: Decimal) -> Decimal:
    if side is SignalSide.BUY:
        return max(current, candidate)
    return min(current, candidate)
