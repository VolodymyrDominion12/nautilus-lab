from __future__ import annotations

from nautilus_lab.application.dtos import BacktestRequest
from nautilus_lab.application.risk import require_simulated_mode
from nautilus_lab.application.run_research_backtest import RunResearchBacktest
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.infrastructure.nautilus.backtest_runner import NautilusResearchBacktest
from nautilus_lab.infrastructure.settings import Settings


def settings() -> Settings:
    return Settings()


def research_use_case() -> RunResearchBacktest:
    return RunResearchBacktest(NautilusResearchBacktest())


def research_request(
    cfg: Settings,
    *,
    bar_count: int,
    robot: RobotName | None = None,
) -> BacktestRequest:
    require_simulated_mode(cfg.trading_mode)
    return BacktestRequest(
        mode=cfg.trading_mode,
        instrument_id=cfg.instrument_id,
        bar_count=bar_count,
        starting_equity=cfg.starting_equity,
        risk=cfg.risk_limits(),
        robot=robot or cfg.robot,
        fast_ema=cfg.fast_ema,
        slow_ema=cfg.slow_ema,
        regime=cfg.regime_params(),
    )
