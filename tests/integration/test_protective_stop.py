"""The protective stop turns `risk_per_trade` from a sizing assumption into a loss cap.

Fixture: a book that is permanently bid-heavy (the heuristic ml_obi classifier says
BUY on every update) while the price falls 1% per bar for 20 bars. A strategy that
never exits on its own is exactly the case the stop exists for: without it the first
long rides the whole ~18% decline; with it every position is cut near its stop.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from nautilus_lab.application.dtos import BacktestRequest
from nautilus_lab.domain.bars import BarOrigin, OhlcvBar
from nautilus_lab.domain.order_book import BookLevel, OrderBookSnapshot
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.risk_overlay import RiskOverlay
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.infrastructure.nautilus.backtest_runner import NautilusResearchBacktest

START = datetime(2024, 1, 1, tzinfo=UTC)
STARTING_EQUITY = Decimal("100000")


def _limits() -> RiskLimits:
    return RiskLimits(
        risk_per_trade=Decimal("0.005"),
        stop_pct=Decimal("0.01"),
        # Wide breakers: this test is about the stop, not about the breakers ending it.
        max_daily_loss=Decimal("0.5"),
        max_drawdown=Decimal("0.5"),
        max_var_99=Decimal("1"),
    )


def _falling_bars(count: int = 20) -> list[OhlcvBar]:
    bars: list[OhlcvBar] = []
    price = Decimal("3500")
    for index in range(count):
        close = (price * Decimal("0.99")).quantize(Decimal("0.01"))
        bars.append(
            OhlcvBar(
                instrument_id="ETH/USDT.SIM",
                ts_utc=START + timedelta(minutes=index + 1),
                open=price,
                high=price,
                low=close,
                close=close,
                volume=Decimal("100"),
            )
        )
        price = close
    return bars


def _bid_heavy_books(bars: list[OhlcvBar], per_bar: int = 20) -> list[OrderBookSnapshot]:
    snapshots: list[OrderBookSnapshot] = []
    for bar in bars:
        for step in range(per_bar):
            snapshots.append(
                OrderBookSnapshot(
                    instrument_id=bar.instrument_id,
                    ts_utc=bar.ts_utc + timedelta(seconds=step),
                    bids=tuple(
                        BookLevel(
                            price=bar.close - Decimal("0.1") * (index + 1), size=Decimal("30")
                        )
                        for index in range(10)
                    ),
                    asks=tuple(
                        BookLevel(price=bar.close + Decimal("0.1") * (index + 1), size=Decimal("5"))
                        for index in range(10)
                    ),
                )
            )
    return snapshots


def _request(*, protective_stop: bool) -> BacktestRequest:
    return BacktestRequest(
        mode=TradingMode.PAPER,
        instrument_id="ETH/USDT.SIM",
        bar_count=20,
        starting_equity=STARTING_EQUITY,
        risk=_limits(),
        risk_overlay=replace(RiskOverlay(), use_protective_stop=protective_stop),
        robot=RobotName.ML_OBI,
        seed=7,
        source=BarOrigin.SYNTHETIC,
    )


@pytest.mark.integration
def test_protective_stop_caps_the_loss_of_a_position_the_strategy_never_exits() -> None:
    bars = _falling_bars()
    books = _bid_heavy_books(bars)
    risk_cash = STARTING_EQUITY * _limits().risk_per_trade
    # The price moves in 1% steps, so a stop can be jumped by up to one step (a gap):
    # a position sized for a 2% (2x ATR) stop can lose ~3%, i.e. 1.5 risk units, plus
    # two taker fees. 3 units is the honest ceiling; unprotected loses ~18 units.
    cap = -3 * risk_cash

    stopped = NautilusResearchBacktest().run_paper(
        _request(protective_stop=True), bars, None, books
    )
    assert stopped.fills, "the bid-heavy book must make ml_obi trade"
    for position in stopped.positions:
        if not position.is_open:
            assert position.realized_pnl >= cap, position
    assert stopped.unrealized_pnl >= cap

    unprotected = NautilusResearchBacktest().run_paper(
        _request(protective_stop=False), bars, None, books
    )
    # The control: without the stop the same fixture loses far more than one risk unit.
    worst_closed = min(
        (p.realized_pnl for p in unprotected.positions if not p.is_open), default=Decimal("0")
    )
    assert min(worst_closed, unprotected.unrealized_pnl) < cap
