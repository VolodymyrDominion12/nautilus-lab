from decimal import Decimal

import pytest

from nautilus_lab.domain.position_plan import (
    Holding,
    PositionPlan,
    holding_from_signed_qty,
    plan_for_signal,
)
from nautilus_lab.domain.signals import SignalSide


@pytest.mark.parametrize(
    ("held", "desired", "expected"),
    [
        (Holding.FLAT, SignalSide.FLAT, PositionPlan(exit_position=False, wants_entry=False)),
        (Holding.LONG, SignalSide.FLAT, PositionPlan(exit_position=True, wants_entry=False)),
        (Holding.SHORT, SignalSide.FLAT, PositionPlan(exit_position=True, wants_entry=False)),
        (Holding.FLAT, SignalSide.BUY, PositionPlan(exit_position=False, wants_entry=True)),
        (Holding.FLAT, SignalSide.SELL, PositionPlan(exit_position=False, wants_entry=True)),
        (Holding.LONG, SignalSide.BUY, PositionPlan(exit_position=False, wants_entry=False)),
        (Holding.SHORT, SignalSide.SELL, PositionPlan(exit_position=False, wants_entry=False)),
        (Holding.LONG, SignalSide.SELL, PositionPlan(exit_position=True, wants_entry=True)),
        (Holding.SHORT, SignalSide.BUY, PositionPlan(exit_position=True, wants_entry=True)),
    ],
)
def test_plan_for_signal_truth_table(
    held: Holding, desired: SignalSide, expected: PositionPlan
) -> None:
    assert plan_for_signal(held, desired) == expected


def test_opposite_signal_exits_even_when_the_entry_will_be_refused() -> None:
    """The regression behind 946 refusals in the ema paper session.

    Exit intent must not depend on anything the risk gate knows: the plan says "exit"
    for a short that receives BUY, and the caller only gates `wants_entry`.
    """
    plan = plan_for_signal(Holding.SHORT, SignalSide.BUY)
    entry_allowed_by_risk = False
    assert plan.exit_position
    assert not (plan.wants_entry and entry_allowed_by_risk)


def test_noop_plan() -> None:
    assert plan_for_signal(Holding.LONG, SignalSide.BUY).is_noop
    assert not plan_for_signal(Holding.LONG, SignalSide.SELL).is_noop


@pytest.mark.parametrize(
    ("signed", "holding"),
    [
        (Decimal("1.5"), Holding.LONG),
        (Decimal("-0.001"), Holding.SHORT),
        (Decimal("0"), Holding.FLAT),
    ],
)
def test_holding_from_signed_qty(signed: Decimal, holding: Holding) -> None:
    assert holding_from_signed_qty(signed) is holding
