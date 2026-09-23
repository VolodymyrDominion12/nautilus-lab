from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from nautilus_lab.application.dtos import BacktestRequest
from nautilus_lab.domain.bars import BarOrigin, OhlcvBar
from nautilus_lab.domain.order_book import BookLevel, OrderBookSnapshot
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.infrastructure.nautilus.backtest_runner import NautilusResearchBacktest
from nautilus_lab.infrastructure.nautilus.synthetic_bars import synthetic_ohlcv

START = datetime(2024, 1, 1, tzinfo=UTC)


def _limits() -> RiskLimits:
    return RiskLimits(
        risk_per_trade=Decimal("0.005"),
        stop_pct=Decimal("0.01"),
        max_daily_loss=Decimal("0.02"),
        max_drawdown=Decimal("0.06"),
    )


def _books_for(
    bars: list[OhlcvBar], *, per_bar: int = 600, levels: int = 20
) -> list[OrderBookSnapshot]:
    """Twenty-level books every 100ms, with the imbalance swept across each bar.

    Both details matter. Twenty levels is what Binance depth actually returns, and the
    engine's container holds ten. 100ms spacing against a 50ms fill latency is the shape
    that used to make the strategy stack entries. Sizes are swept so the imbalance
    feature moves — a perfectly balanced book classifies as `flat` and never trades.
    """
    snapshots: list[OrderBookSnapshot] = []
    for bar in bars:
        for step in range(per_bar):
            phase = step % 10
            bid_size = Decimal(4 + phase)
            ask_size = Decimal(4 + (10 - phase))
            snapshots.append(
                OrderBookSnapshot(
                    instrument_id=bar.instrument_id,
                    ts_utc=bar.ts_utc + timedelta(milliseconds=100 * step),
                    bids=tuple(
                        BookLevel(price=bar.close - Decimal("0.1") * (index + 1), size=bid_size)
                        for index in range(levels)
                    ),
                    asks=tuple(
                        BookLevel(price=bar.close + Decimal("0.1") * (index + 1), size=ask_size)
                        for index in range(levels)
                    ),
                )
            )
    return snapshots


@pytest.mark.integration
def test_paper_session_never_stacks_entries_on_a_book_driven_robot() -> None:
    """One entry per flat-to-position transition, however fast the signals arrive.

    Regression for a risk-control bug: `Portfolio` only shows a position once the fill
    lands, and `cache.orders_open()` is empty while an order is still inflight, so a
    robot fed by 100ms book updates saw `flat=True` while its own orders were pending
    and stacked entries — 13 of them in one second on real ETH depth, about 4x the
    notional that `size_position` caps. Measured: 49,001 with the guard, 98,079 without.

    The bound asserted here is the size a single sized entry can reach:
    `equity * risk_per_trade / stop_pct`, i.e. the 0.5% risk over a 1% stop.
    """
    bars = synthetic_ohlcv(instrument_id="ETH/USDT.SIM", count=8, seed=5)
    request = BacktestRequest(
        mode=TradingMode.PAPER,
        instrument_id="ETH/USDT.SIM",
        bar_count=len(bars),
        starting_equity=Decimal("100000"),
        risk=_limits(),
        robot=RobotName.ML_OBI,
        seed=7,
        source=BarOrigin.SYNTHETIC,
    )

    report = NautilusResearchBacktest().run_paper(request, bars, None, _books_for(bars))

    assert report.fills, "the book-driven robot must trade on this fixture"
    single_entry = request.starting_equity * request.risk.risk_per_trade / request.risk.stop_pct
    ceiling = single_entry * Decimal("1.02")
    positions = list(report.positions)
    if report.open_position is not None:
        positions.append(report.open_position)
    for position in positions:
        notional = position.qty * position.entry_price
        assert notional <= ceiling, (
            f"position {position.qty} @ {position.entry_price} is {notional} notional, "
            f"above one sized entry ({single_entry}); entries were stacked"
        )
