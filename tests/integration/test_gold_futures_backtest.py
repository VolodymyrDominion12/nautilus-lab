"""Integration test: COMEX gold FuturesContract (`MGCZ26.XCEC`) inside Nautilus BacktestEngine."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from nautilus_lab.application.dtos import BacktestRequest
from nautilus_lab.domain.bars import BarOrigin, OhlcvBar
from nautilus_lab.domain.fees import COMEX_MGC_IBKR, COMEX_STRESS_X2
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.infrastructure.nautilus.backtest_runner import NautilusResearchBacktest


def _mgc_hourly_bars() -> list[OhlcvBar]:
    """Deterministic 1h COMEX MGC series on CME 23x5 hours ending inside an open long."""
    from nautilus_lab.domain.calendar import TradingCalendar, is_trading_bar_close

    cursor = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)  # Monday
    bars: list[OhlcvBar] = []
    # 160 trading hours: dip -> strong rally -> dip -> rally (ends while in an open long).
    price = Decimal("2620.00")
    while len(bars) < 160:
        if not is_trading_bar_close(
            cursor,
            interval=timedelta(hours=1),
            calendar=TradingCalendar.CME_GLOBEX_23_5,
        ):
            cursor += timedelta(hours=1)
            continue
        idx = len(bars)
        if idx < 30:
            delta = Decimal("-1.20")
        elif idx < 80:
            delta = Decimal("2.40")
        elif idx < 110:
            delta = Decimal("-2.50")
        else:
            delta = Decimal("2.20")
        o = price
        c = (price + delta).quantize(Decimal("0.10"))
        h = (max(o, c) + Decimal("0.80")).quantize(Decimal("0.10"))
        lo = (min(o, c) - Decimal("0.80")).quantize(Decimal("0.10"))
        bars.append(
            OhlcvBar(
                instrument_id="MGCZ26.XCEC",
                ts_utc=cursor,
                open=o.quantize(Decimal("0.10")),
                high=h,
                low=lo,
                close=c,
                volume=Decimal("250"),
            )
        )
        price = c
        cursor += timedelta(hours=1)
    return bars


@pytest.mark.integration
def test_comex_mgc_usd_account_and_per_contract_fees() -> None:
    """Verify MGCZ26.XCEC USD settlement, multiplier=10 sizing/PnL, and per-contract fees."""
    bars = _mgc_hourly_bars()
    bar_type = "MGCZ26.XCEC-1-HOUR-LAST-EXTERNAL"

    base_request = BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="MGCZ26.XCEC",
        bar_type=bar_type,
        bar_count=len(bars),
        starting_equity=Decimal("100000"),
        risk=RiskLimits(
            risk_per_trade=Decimal("0.01"),
            stop_pct=Decimal("0.015"),
            max_daily_loss=Decimal("0.05"),
            max_drawdown=Decimal("0.15"),
        ),
        robot=RobotName.EMA,
        fast_ema=5,
        slow_ema=15,
        source=BarOrigin.CATALOG,
        futures_fees=COMEX_MGC_IBKR,
    )

    engine = NautilusResearchBacktest()
    paper = engine.run_paper(base_request, bars)
    report = engine.run(base_request, bars)

    assert len(paper.fills) >= 2
    assert paper.metrics is not None
    assert "USD" in report.notes
    assert "comex_mgc_ibkr" in report.notes

    # 1. Per-contract IBKR fee ($0.85/contract/side) matches exact fill quantities.
    expected_fees = sum((Decimal("0.85") * fill.qty for fill in paper.fills), Decimal("0"))
    assert paper.fees_paid == expected_fees
    for fill in paper.fills:
        assert fill.commission == Decimal("0.85") * fill.qty
        # With $100k equity and multiplier=10 (~$26k/contract), 1x leverage allows <= 3 lots.
        assert Decimal("1") <= fill.qty <= Decimal("3")

    # 2. Traded notional includes contract multiplier=10.
    expected_notional = sum(
        (fill.price * fill.qty * Decimal("10") for fill in paper.fills),
        Decimal("0"),
    )
    assert paper.traded_notional == expected_notional

    # 3. Account balance & closed positions reflect USD settlement with multiplier=10.
    assert len(paper.positions) >= 2
    total_realized = sum((pos.realized_pnl for pos in paper.positions), Decimal("0"))
    assert total_realized > Decimal("0")
    assert report.ending_balance == base_request.starting_equity + total_realized
    # First round-trip (short) PnL equals price delta * qty * multiplier(10) - 2*fee.
    first_entry, first_exit = paper.fills[0], paper.fills[1]
    assert first_entry.qty == first_exit.qty
    expected_first_gross = (first_entry.price - first_exit.price) * first_entry.qty * Decimal("10")
    expected_first_net = expected_first_gross - (first_entry.commission + first_exit.commission)
    assert paper.positions[0].realized_pnl == expected_first_net

    # 4. Calendar-aware Sharpe annualization uses CME_GLOBEX_23_5 1h (5796 bars/yr), not 8760.
    assert paper.metrics.sharpe_like is not None
    assert paper.metrics.sharpe_like != Decimal("0")
    assert paper.metrics.sharpe_annualized is not None
    annual_ratio = float(paper.metrics.sharpe_annualized / paper.metrics.sharpe_like)
    assert abs(annual_ratio) == pytest.approx(math.sqrt(5796), rel=1e-4)

    # 5. COMEX stress x2 profile charges $1.70/contract/side.
    stress_request = BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="MGCZ26.XCEC",
        bar_type=bar_type,
        bar_count=len(bars),
        starting_equity=Decimal("100000"),
        risk=base_request.risk,
        robot=RobotName.EMA,
        fast_ema=5,
        slow_ema=15,
        source=BarOrigin.CATALOG,
        futures_fees=COMEX_STRESS_X2,
    )
    stressed = engine.run_paper(stress_request, bars)
    assert "comex_stress_x2" in engine.run(stress_request, bars).notes
    assert len(stressed.fills) >= 2
    for fill in stressed.fills:
        assert fill.commission == Decimal("1.70") * fill.qty
    assert stressed.fees_paid > paper.fees_paid
