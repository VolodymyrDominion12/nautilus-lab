from decimal import Decimal
from pathlib import Path

import pytest

from nautilus_lab.application.dtos import BacktestRequest
from nautilus_lab.domain.bars import BarOrigin
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.infrastructure.nautilus.backtest_runner import NautilusResearchBacktest
from nautilus_lab.infrastructure.nautilus.synthetic_bars import synthetic_regime_ohlcv


@pytest.mark.integration
def test_tearsheet_html_generated(tmp_path: Path) -> None:
    output_html = tmp_path / "reports" / "tearsheet.html"
    bars = synthetic_regime_ohlcv(instrument_id="ETH/USDT.SIM", count=200, seed=42)
    request = BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="ETH/USDT.SIM",
        bar_count=200,
        starting_equity=Decimal("100000"),
        risk=RiskLimits(
            risk_per_trade=Decimal("0.005"),
            stop_pct=Decimal("0.01"),
            max_daily_loss=Decimal("0.02"),
            max_drawdown=Decimal("0.06"),
        ),
        robot=RobotName.REGIME,
        source=BarOrigin.SYNTHETIC,
        tearsheet_path=str(output_html),
    )
    runner = NautilusResearchBacktest()
    report = runner.run(request, bars)

    assert output_html.exists()
    assert output_html.stat().st_size > 0
    assert report.tearsheet_path == str(output_html)
    content = output_html.read_text(encoding="utf-8")
    assert "html" in content.lower()
