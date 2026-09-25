from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.metrics import (
    buy_and_hold_return,
    return_series_from_bars,
    return_series_from_equity,
    sample_volatility,
    vol_matched_buy_and_hold_return,
)


def _bar(price: str, index: int) -> OhlcvBar:
    return OhlcvBar(
        instrument_id="BTCUSDT",
        ts_utc=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=index),
        open=Decimal(price),
        high=Decimal(price),
        low=Decimal(price),
        close=Decimal(price),
        volume=Decimal("10"),
    )


def test_buy_and_hold_return() -> None:
    bars = [_bar("100", 0), _bar("110", 1), _bar("120", 2)]
    assert buy_and_hold_return(bars) == Decimal("0.2")

    # Single bar or empty
    assert buy_and_hold_return([]) is None
    assert buy_and_hold_return([_bar("100", 0)]) is None


def test_return_series_from_bars_and_equity() -> None:
    bars = [_bar("100", 0), _bar("110", 1), _bar("121", 2)]
    returns = return_series_from_bars(bars)
    assert len(returns) == 2
    assert returns[0] == Decimal("0.1")
    assert returns[1] == Decimal("0.1")

    equity_curve = (Decimal("1000"), Decimal("1050"), Decimal("1102.5"))
    eq_returns = return_series_from_equity(equity_curve)
    assert len(eq_returns) == 2
    assert eq_returns[0] == Decimal("0.05")
    assert eq_returns[1] == Decimal("0.05")


def test_sample_volatility() -> None:
    returns = [Decimal("0.01"), Decimal("0.02"), Decimal("0.03")]
    vol = sample_volatility(returns)
    assert vol is not None
    assert round(vol, 4) == Decimal("0.0100")

    assert sample_volatility([Decimal("0.01")]) is None
    assert sample_volatility([]) is None


def test_vol_matched_buy_and_hold_identical_volatility() -> None:
    # Asset moves: 100 -> 110 -> 100 -> 110 (+10%, -9.09%, +10%)
    # Strategy moves identically: 1000 -> 1100 -> 1000 -> 1100
    bars = [_bar("100", 0), _bar("110", 1), _bar("100", 2), _bar("110", 3)]
    equity = (Decimal("1000"), Decimal("1100"), Decimal("1000"), Decimal("1100"))

    bnh = buy_and_hold_return(bars)
    vol_bnh = vol_matched_buy_and_hold_return(bars=bars, equity_curve=equity)

    assert bnh is not None
    assert vol_bnh is not None
    assert round(vol_bnh, 6) == round(bnh, 6)


def test_vol_matched_buy_and_hold_scaled_down_for_conservative_strategy() -> None:
    # Asset moves with high vol: 100 -> 120 -> 90 -> 130 (+30% overall)
    bars = [_bar("100", 0), _bar("120", 1), _bar("90", 2), _bar("130", 3)]
    # Strategy took half the swings (e.g. 50% cash allocation):
    # 1000 -> 1100 -> 950 -> 1150
    equity = (Decimal("1000"), Decimal("1100"), Decimal("950"), Decimal("1150"))

    bnh = buy_and_hold_return(bars)
    vol_bnh = vol_matched_buy_and_hold_return(bars=bars, equity_curve=equity)

    assert bnh == Decimal("0.3")
    assert vol_bnh is not None
    # Strategy had approximately half the volatility, so benchmark return is scaled down
    assert Decimal("0.10") < vol_bnh < Decimal("0.20")


def test_vol_matched_buy_and_hold_zero_for_all_cash_strategy() -> None:
    # Asset moves +50%
    bars = [_bar("100", 0), _bar("120", 1), _bar("110", 2), _bar("150", 3)]
    # Strategy sat 100% in cash (equity flat at $10,000)
    equity = (Decimal("10000"), Decimal("10000"), Decimal("10000"), Decimal("10000"))

    vol_bnh = vol_matched_buy_and_hold_return(bars=bars, equity_curve=equity)
    assert vol_bnh == Decimal("0")


def test_vol_matched_buy_and_hold_leverage_capped() -> None:
    # Asset barely moves (very low vol): 100 -> 100.1 -> 99.9 -> 100.2
    bars = [_bar("100.0", 0), _bar("100.1", 1), _bar("99.9", 2), _bar("100.2", 3)]
    # Highly leveraged strategy with 10x volatility
    equity = (Decimal("1000"), Decimal("1100"), Decimal("900"), Decimal("1200"))

    vol_bnh = vol_matched_buy_and_hold_return(
        bars=bars, equity_curve=equity, max_leverage=Decimal("2.0")
    )
    bnh = buy_and_hold_return(bars)
    assert bnh is not None
    assert vol_bnh is not None
    assert vol_bnh == Decimal("2.0") * bnh
