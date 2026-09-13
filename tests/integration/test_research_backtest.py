from decimal import Decimal

import pytest

from nautilus_lab.application.dtos import BacktestRequest
from nautilus_lab.application.run_research_backtest import RunResearchBacktest
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.infrastructure.nautilus.backtest_runner import NautilusResearchBacktest


@pytest.mark.integration
def test_research_backtest_runs_locally_without_network() -> None:
    limits = RiskLimits(
        risk_per_trade=Decimal("0.005"),
        stop_pct=Decimal("0.01"),
        max_daily_loss=Decimal("0.02"),
        max_drawdown=Decimal("0.06"),
    )
    use_case = RunResearchBacktest(NautilusResearchBacktest())
    report = use_case.execute(
        BacktestRequest(
            mode=TradingMode.RESEARCH,
            instrument_id="ETH/USDT.SIM",
            bar_count=400,
            starting_equity=Decimal("100000"),
            risk=limits,
            fast_ema=10,
            slow_ema=20,
            seed=7,
        ),
    )

    assert report.fills >= 0
    assert report.positions >= 0
    assert "fees" in report.notes
