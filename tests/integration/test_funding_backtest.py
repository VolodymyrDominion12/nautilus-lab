from collections.abc import Sequence
from decimal import Decimal

import pytest

from nautilus_lab.application.dtos import BacktestRequest
from nautilus_lab.application.run_paper import RunPaperSession
from nautilus_lab.application.run_research_backtest import RunResearchBacktest
from nautilus_lab.domain.bars import BarOrigin, OhlcvBar
from nautilus_lab.domain.funding import FundingParams
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.infrastructure.nautilus.backtest_runner import NautilusResearchBacktest
from nautilus_lab.infrastructure.nautilus.bar_feed import ResearchBarFeed


def _limits() -> RiskLimits:
    return RiskLimits(
        risk_per_trade=Decimal("0.005"),
        stop_pct=Decimal("0.01"),
        max_daily_loss=Decimal("0.02"),
        max_drawdown=Decimal("0.06"),
    )


class _UnusedCatalog:
    def write(
        self,
        bars: Sequence[OhlcvBar],
        *,
        bar_type: str,
        instrument_id: str = "",
    ) -> int:
        raise AssertionError("synthetic path must not touch catalog")

    def load(self, *args: object, **kwargs: object) -> list[OhlcvBar]:
        raise AssertionError("synthetic path must not load catalog")

    def load_multi(self, request: BacktestRequest) -> dict[str, list[OhlcvBar]]:
        raise AssertionError("synthetic path must not load catalog")


@pytest.mark.integration
def test_funding_research_backtest_synthetic() -> None:
    use_case = RunResearchBacktest(NautilusResearchBacktest(), ResearchBarFeed(_UnusedCatalog()))
    request = BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="ETH/USDT.SIM",
        bar_count=200,
        starting_equity=Decimal("100000"),
        risk=_limits(),
        robot=RobotName.FUNDING,
        source=BarOrigin.SYNTHETIC,
        funding=FundingParams(
            min_net_apy=Decimal("0.10"),
            holding_periods=30,
            basis_max=Decimal("0.005"),
            close_on_negative=True,
        ),
        funding_spot_id="ETH/USDT.SIM",
        funding_perp_id="ETHUSDT-PERP.SIM",
    )
    report = use_case.execute(request)

    assert report.fills == 2
    assert report.positions == 2
    assert report.ending_balance is not None
    assert report.ending_balance > Decimal("100000")
    assert report.metrics is not None
    assert report.metrics.fees_paid > Decimal("0")
    assert "funding synthetic backtest with fees" in report.notes


@pytest.mark.integration
def test_funding_paper_session_synthetic() -> None:
    use_case = RunPaperSession(NautilusResearchBacktest(), ResearchBarFeed(_UnusedCatalog()))
    request = BacktestRequest(
        mode=TradingMode.PAPER,
        instrument_id="ETH/USDT.SIM",
        bar_count=200,
        starting_equity=Decimal("100000"),
        risk=_limits(),
        robot=RobotName.FUNDING,
        source=BarOrigin.SYNTHETIC,
        funding=FundingParams(
            min_net_apy=Decimal("0.10"),
            holding_periods=30,
            basis_max=Decimal("0.005"),
            close_on_negative=True,
        ),
        funding_spot_id="ETH/USDT.SIM",
        funding_perp_id="ETHUSDT-PERP.SIM",
    )
    report = use_case.execute(request)

    assert len(report.fills) == 2
    sides = {fill.side for fill in report.fills}
    assert sides == {"BUY", "SELL"}
    instruments = {fill.instrument_id for fill in report.fills}
    assert instruments == {"ETH/USDT.SIM", "ETHUSDT-PERP.SIM"}
    assert report.fees_paid > Decimal("0")
    summary = report.summary_line()
    assert "paper funding ETH/USDT.SIM mode=paper" in summary
    assert "(no exchange submission)" in summary


@pytest.mark.integration
def test_funding_settlements_after_the_window_never_reach_the_balance() -> None:
    """Audit A4: settlements dated after the last bar used to be accrued anyway."""
    from dataclasses import replace
    from datetime import timedelta

    from nautilus_lab.infrastructure.nautilus.synthetic_pairs import synthetic_funding_pair

    bars, snapshots = synthetic_funding_pair(count=200, seed=42)
    request = BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="ETH/USDT.SIM",
        bar_count=200,
        starting_equity=Decimal("100000"),
        risk=_limits(),
        robot=RobotName.FUNDING,
        source=BarOrigin.CATALOG,
        bar_type="ETH/USDT.SIM-1-HOUR-LAST-EXTERNAL",
        funding=FundingParams(
            min_net_apy=Decimal("0.10"),
            holding_periods=30,
            basis_max=Decimal("0.005"),
            close_on_negative=True,
        ),
        funding_spot_id="ETH/USDT.SIM",
        funding_perp_id="ETHUSDT-PERP.SIM",
    )
    last = snapshots[-1]
    future = [
        replace(last, ts_utc=last.ts_utc + timedelta(hours=8 * step), funding_rate=Decimal("0.01"))
        for step in range(1, 50)
    ]
    engine = NautilusResearchBacktest()
    clean = engine.run_spread(request, bars, funding=snapshots)
    polluted = engine.run_spread(request, bars, funding=[*snapshots, *future])
    assert clean.ending_balance == polluted.ending_balance
