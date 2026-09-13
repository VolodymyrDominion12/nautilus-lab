from decimal import Decimal

from nautilus_lab.application.dtos import (
    BacktestReport,
    BacktestRequest,
    SelectedParams,
)
from nautilus_lab.application.optuna_optimizer import OptunaParamOptimizer
from nautilus_lab.domain.metrics import BacktestMetrics
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.trading_mode import TradingMode


def _dummy_request(robot: RobotName = RobotName.REGIME) -> BacktestRequest:
    return BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="ETH/USDT.SIM",
        bar_count=500,
        starting_equity=Decimal("100000"),
        risk=RiskLimits(
            risk_per_trade=Decimal("0.005"),
            stop_pct=Decimal("0.01"),
            max_daily_loss=Decimal("0.02"),
            max_drawdown=Decimal("0.06"),
        ),
        robot=robot,
    )


def test_optuna_optimizer_regime() -> None:
    optimizer = OptunaParamOptimizer(n_trials=3, seed=42)
    request = _dummy_request(RobotName.REGIME)

    def mock_run_is(candidate: BacktestRequest) -> BacktestReport:
        # Give higher ending balance for specific donchian_period
        bonus = Decimal(str(candidate.regime.donchian_period * 100))
        return BacktestReport(
            fills=10,
            positions=5,
            ending_balance=Decimal("100000") + bonus,
            notes="mock run",
            metrics=BacktestMetrics(
                fees_paid=Decimal("10"),
                max_drawdown=Decimal("0.02"),
                turnover=Decimal("5000"),
                sharpe_like=Decimal("1.5"),
            ),
        )

    best_params, best_report, trials = optimizer.optimize(request, mock_run_is)

    assert trials == 3
    assert isinstance(best_params, SelectedParams)
    assert best_report.ending_balance is not None
    assert best_report.ending_balance > Decimal("100000")


def test_optuna_optimizer_ema() -> None:
    optimizer = OptunaParamOptimizer(n_trials=3, seed=42)
    request = _dummy_request(RobotName.EMA)

    def mock_run_is(candidate: BacktestRequest) -> BacktestReport:
        return BacktestReport(
            fills=5,
            positions=2,
            ending_balance=Decimal("102000"),
            notes="mock run",
        )

    best_params, _best_report, trials = optimizer.optimize(request, mock_run_is)
    assert trials == 3
    assert best_params.fast_ema < best_params.slow_ema


def test_optuna_optimizer_pairs() -> None:
    optimizer = OptunaParamOptimizer(n_trials=3, seed=42)
    request = _dummy_request(RobotName.PAIRS)

    def mock_run_is(candidate: BacktestRequest) -> BacktestReport:
        return BacktestReport(
            fills=8,
            positions=4,
            ending_balance=Decimal("105000"),
            notes="mock run",
        )

    best_params, _best_report, trials = optimizer.optimize(request, mock_run_is)
    assert trials == 3
    assert best_params.z_entry >= Decimal("1.2")
