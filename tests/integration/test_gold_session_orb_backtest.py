"""Integration test: `gold_session_orb` end-to-end inside Nautilus BacktestEngine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.persistence.catalog.singleton import clear_singleton_instances

from nautilus_lab.application.dtos import BacktestRequest
from nautilus_lab.application.run_research_backtest import RunResearchBacktest
from nautilus_lab.domain.bars import BarOrigin, OhlcvBar
from nautilus_lab.domain.gold_session_orb import GoldSessionOrbParams
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.infrastructure.nautilus.backtest_runner import NautilusResearchBacktest
from nautilus_lab.infrastructure.nautilus.bar_feed import ResearchBarFeed
from nautilus_lab.infrastructure.nautilus.parquet_catalog import NautilusParquetCatalog


def _gold_hourly_bars(days: int = 16) -> list[OhlcvBar]:
    """Deterministic hourly series on PAXGUSDT-PERP.SIM with clean Asia boxes + London breakouts."""
    start = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)  # Monday
    bars: list[OhlcvBar] = []
    base = Decimal("2600.00")
    for day in range(days):
        day_start = start + timedelta(days=day)
        day_open = base + Decimal(day) * Decimal("12.00")
        for hour in range(24):
            ts = day_start + timedelta(hours=hour)
            if 0 <= hour < 7:
                # Tight Asia range: +/- 2.50 around day_open (box width ~ 5.00)
                c = day_open + Decimal("0.20") * Decimal(hour - 3)
                h = day_open + Decimal("2.50")
                lo = day_open - Decimal("2.50")
                o = day_open
            elif 7 <= hour < 14:
                # London / overlap impulsive upward breakout above Asia high
                step = Decimal(hour - 6) * Decimal("3.00")
                o = day_open + step - Decimal("2.00")
                c = day_open + step + Decimal("2.00")
                h = c + Decimal("2.00")
                lo = o - Decimal("2.00")
            else:
                # Calm NY afternoon / overnight drift
                level = day_open + Decimal("14.00")
                o = level
                c = level + Decimal("0.50")
                h = level + Decimal("3.00")
                lo = level - Decimal("3.00")
            bars.append(
                OhlcvBar(
                    instrument_id="PAXGUSDT-PERP.SIM",
                    ts_utc=ts,
                    open=o.quantize(Decimal("0.01")),
                    high=h.quantize(Decimal("0.01")),
                    low=lo.quantize(Decimal("0.01")),
                    close=c.quantize(Decimal("0.01")),
                    volume=Decimal("500"),
                )
            )
    return bars


@pytest.mark.integration
def test_gold_session_orb_runs_deterministically_on_paxg_perp(tmp_path: Path) -> None:
    clear_singleton_instances(ParquetDataCatalog)
    bar_type = "PAXGUSDT-PERP.SIM-1-HOUR-LAST-EXTERNAL"
    bars = _gold_hourly_bars(days=16)  # 384 hourly bars (> 200 EMA warmup)
    store = NautilusParquetCatalog(tmp_path)
    store.write(bars, bar_type=bar_type)

    request = BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="PAXGUSDT-PERP.SIM",
        bar_type=bar_type,
        bar_count=len(bars),
        starting_equity=Decimal("100000"),
        risk=RiskLimits(
            risk_per_trade=Decimal("0.005"),
            stop_pct=Decimal("0.015"),
            max_daily_loss=Decimal("0.03"),
            max_drawdown=Decimal("0.10"),
        ),
        robot=RobotName.GOLD_SESSION_ORB,
        source=BarOrigin.CATALOG,
        gold_session_orb=GoldSessionOrbParams(
            atr_period=14,
            trend_ema_period=200,
            min_box_atr=Decimal("0.2"),
            max_box_atr=Decimal("1.5"),
            buffer_atr=Decimal("0.15"),
            max_hold_bars=12,
        ),
    )

    use_case = RunResearchBacktest(NautilusResearchBacktest(), ResearchBarFeed(store))
    first = use_case.execute(request)
    second = use_case.execute(request)

    assert first.fills > 0
    assert first.positions > 0
    assert first.ending_balance is not None
    assert first.ending_balance > Decimal("0")
    assert "gold_session_orb" in first.notes
    assert first.ending_balance == second.ending_balance
    assert first.fills == second.fills
