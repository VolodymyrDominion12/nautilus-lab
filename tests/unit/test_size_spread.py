"""Spread legs are hedged in quantity, not in risk (audit B1)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from nautilus_lab.application.risk import size_spread
from nautilus_lab.domain.errors import InvalidRiskError

STEP = Decimal("0.0001")


def _eth_btc(hedge: Decimal) -> tuple[Decimal, Decimal]:
    # Real ETH/BTC scale from the audit: stop_A = ATR 62.64 on ETH, BTC ~ 16.8x pricier.
    return size_spread(
        equity=Decimal("100000"),
        price_a=Decimal("3500"),
        price_b=Decimal("60000"),
        stop_distance_a=Decimal("62.64"),
        risk_fraction=Decimal("0.005"),
        hedge_ratio=hedge,
        qty_step_a=STEP,
        qty_step_b=STEP,
    )


def test_leg_b_quantity_is_hedge_ratio_times_leg_a() -> None:
    qty_a, qty_b = _eth_btc(Decimal("0.05"))
    assert qty_a > 0
    assert abs(qty_b - qty_a * Decimal("0.05")) <= STEP


def test_negative_hedge_ratio_uses_its_magnitude() -> None:
    assert _eth_btc(Decimal("-0.05")) == _eth_btc(Decimal("0.05"))


def test_leg_b_over_one_x_notional_shrinks_both_legs_together() -> None:
    qty_a, qty_b = size_spread(
        equity=Decimal("10000"),
        price_a=Decimal("100"),
        price_b=Decimal("100"),
        stop_distance_a=Decimal("0.5"),  # risk sizing alone would buy 100 A (1x notional)
        risk_fraction=Decimal("0.005"),
        hedge_ratio=Decimal("4"),
        qty_step_a=STEP,
        qty_step_b=STEP,
    )
    assert qty_b * Decimal("100") <= Decimal("10000")
    assert abs(qty_b - qty_a * 4) <= 4 * STEP


def test_too_small_to_hedge_returns_no_order() -> None:
    qty_a, qty_b = size_spread(
        equity=Decimal("100"),
        price_a=Decimal("3500"),
        price_b=Decimal("60000"),
        stop_distance_a=Decimal("62.64"),
        risk_fraction=Decimal("0.005"),
        hedge_ratio=Decimal("0.05"),
        qty_step_a=Decimal("0.001"),
        qty_step_b=Decimal("0.001"),
    )
    assert (qty_a, qty_b) == (Decimal("0"), Decimal("0"))


def test_zero_hedge_ratio_is_refused() -> None:
    with pytest.raises(InvalidRiskError):
        _eth_btc(Decimal("0"))
