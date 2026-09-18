from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from nautilus_lab.domain.order_book import BookLevel, OrderBookSnapshot
from nautilus_lab.domain.portfolio_risk import (
    fractional_kelly_cap,
    historical_cvar,
    historical_var,
)


def test_order_book_snapshot_validation() -> None:
    now = datetime(2024, 1, 1, tzinfo=UTC)

    # Empty bids or asks
    with pytest.raises(ValueError, match="book must have bids and asks"):
        OrderBookSnapshot(
            instrument_id="ETH/USDT.SIM",
            ts_utc=now,
            bids=(),
            asks=(BookLevel(price=Decimal("2000"), size=Decimal("1")),),
        ).validate()

    with pytest.raises(ValueError, match="book must have bids and asks"):
        OrderBookSnapshot(
            instrument_id="ETH/USDT.SIM",
            ts_utc=now,
            bids=(BookLevel(price=Decimal("2000"), size=Decimal("1")),),
            asks=(),
        ).validate()

    # Crossed book
    with pytest.raises(ValueError, match="crossed book"):
        OrderBookSnapshot(
            instrument_id="ETH/USDT.SIM",
            ts_utc=now,
            bids=(BookLevel(price=Decimal("2005"), size=Decimal("1")),),
            asks=(BookLevel(price=Decimal("2000"), size=Decimal("1")),),
        ).validate()

    # Bids not descending
    with pytest.raises(ValueError, match="bids must be descending"):
        OrderBookSnapshot(
            instrument_id="ETH/USDT.SIM",
            ts_utc=now,
            bids=(
                BookLevel(price=Decimal("1990"), size=Decimal("1")),
                BookLevel(price=Decimal("1995"), size=Decimal("1")),
            ),
            asks=(BookLevel(price=Decimal("2000"), size=Decimal("1")),),
        ).validate()

    # Asks not ascending
    with pytest.raises(ValueError, match="asks must be ascending"):
        OrderBookSnapshot(
            instrument_id="ETH/USDT.SIM",
            ts_utc=now,
            bids=(BookLevel(price=Decimal("1990"), size=Decimal("1")),),
            asks=(
                BookLevel(price=Decimal("2005"), size=Decimal("1")),
                BookLevel(price=Decimal("2000"), size=Decimal("1")),
            ),
        ).validate()

    # Valid book passes
    valid_book = OrderBookSnapshot(
        instrument_id="ETH/USDT.SIM",
        ts_utc=now,
        bids=(
            BookLevel(price=Decimal("1995"), size=Decimal("1")),
            BookLevel(price=Decimal("1990"), size=Decimal("2")),
        ),
        asks=(
            BookLevel(price=Decimal("2000"), size=Decimal("1")),
            BookLevel(price=Decimal("2005"), size=Decimal("3")),
        ),
    )
    valid_book.validate()


def test_fractional_kelly_cap_edge_cases() -> None:
    # Invalid win rate
    assert fractional_kelly_cap(win_rate=Decimal("0"), reward_risk=Decimal("1.5")) == Decimal("0")
    assert fractional_kelly_cap(win_rate=Decimal("1"), reward_risk=Decimal("1.5")) == Decimal("0")
    zero_cap = fractional_kelly_cap(win_rate=Decimal("-0.1"), reward_risk=Decimal("1.5"))
    assert zero_cap == Decimal("0")

    # Invalid reward_risk
    assert fractional_kelly_cap(win_rate=Decimal("0.5"), reward_risk=Decimal("0")) == Decimal("0")
    assert fractional_kelly_cap(win_rate=Decimal("0.5"), reward_risk=Decimal("-1")) == Decimal("0")

    # Invalid fraction
    with pytest.raises(ValueError, match="fraction must be in"):
        fractional_kelly_cap(
            win_rate=Decimal("0.6"), reward_risk=Decimal("2"), fraction=Decimal("0")
        )
    with pytest.raises(ValueError, match="fraction must be in"):
        fractional_kelly_cap(
            win_rate=Decimal("0.6"), reward_risk=Decimal("2"), fraction=Decimal("1.5")
        )

    # Negative edge
    assert fractional_kelly_cap(win_rate=Decimal("0.3"), reward_risk=Decimal("1")) == Decimal("0")

    # Positive edge
    res = fractional_kelly_cap(
        win_rate=Decimal("0.6"), reward_risk=Decimal("2"), fraction=Decimal("0.5")
    )
    assert res > 0


def test_historical_var_and_cvar() -> None:
    # Empty returns
    assert historical_var(()) is None
    assert historical_cvar(()) is None

    # Invalid confidence
    with pytest.raises(ValueError, match="confidence must be in"):
        historical_var((Decimal("0.01"),), confidence=Decimal("0"))
    with pytest.raises(ValueError, match="confidence must be in"):
        historical_var((Decimal("0.01"),), confidence=Decimal("1"))

    # All positive returns -> var is 0
    pos_returns = tuple(Decimal(str(x)) for x in [0.01, 0.02, 0.03, 0.04])
    assert historical_var(pos_returns) == Decimal("0")
    assert historical_cvar(pos_returns) == Decimal("0")

    # Mixed returns
    mixed = tuple(Decimal(str(x)) for x in [-0.05, -0.02, -0.01, 0.01, 0.02, 0.03])
    var = historical_var(mixed, confidence=Decimal("0.95"))
    assert var is not None and var > 0
    cvar = historical_cvar(mixed, confidence=Decimal("0.95"))
    assert cvar is not None and cvar >= var
