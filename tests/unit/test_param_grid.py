from decimal import Decimal

from nautilus_lab.application.dtos import BacktestRequest
from nautilus_lab.application.param_grid import iter_param_grid
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.trading_mode import TradingMode


def _request(robot: RobotName) -> BacktestRequest:
    return BacktestRequest(
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
        robot=robot,
    )


def test_ema_grid_varies_periods_only() -> None:
    grid = list(iter_param_grid(_request(RobotName.EMA)))
    pairs = {(item.fast_ema, item.slow_ema) for item in grid}
    assert pairs == {(5, 20), (10, 20), (10, 40), (12, 26)}


def test_regime_grid_varies_donchian_and_bands() -> None:
    grid = list(iter_param_grid(_request(RobotName.REGIME)))
    assert len(grid) == 6
    assert {item.donchian_period for item in grid} == {10, 20, 40}
    assert {item.bb_k for item in grid} == {Decimal("2"), Decimal("2.5")}


def test_formulaic_grid_varies_threshold_only() -> None:
    grid = list(iter_param_grid(_request(RobotName.FORMULAIC_LGBM)))
    assert len(grid) == 3
    assert {item.formulaic_threshold for item in grid} == {
        Decimal("0.50"),
        Decimal("0.55"),
        Decimal("0.60"),
    }
