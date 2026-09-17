from __future__ import annotations

from nautilus_lab.application.dtos import (
    BacktestReport,
    BacktestRequest,
    BarFeed,
    ResearchBacktestPort,
)
from nautilus_lab.application.risk import require_simulated_mode
from nautilus_lab.domain.regime import RobotName, require_backtest_support


class RunResearchBacktest:
    def __init__(self, engine: ResearchBacktestPort, feed: BarFeed) -> None:
        self._engine = engine
        self._feed = feed

    def execute(self, request: BacktestRequest) -> BacktestReport:
        require_simulated_mode(request.mode)
        require_backtest_support(request.robot)
        minimum = minimum_bars(request.robot)
        if request.robot is RobotName.PAIRS:
            bars_by_instrument = self._feed.load_multi(request)
            count = min(len(series) for series in bars_by_instrument.values())
            if count < minimum:
                raise ValueError(f"bar_count must be >= {minimum} so indicators can warm up")
            return self._engine.run_spread(request, bars_by_instrument)
        bars = self._feed.load(request)
        if len(bars) < minimum:
            raise ValueError(f"bar_count must be >= {minimum} so indicators can warm up")
        return self._engine.run(request, bars)


def minimum_bars(robot: RobotName) -> int:
    if robot in (
        RobotName.REGIME,
        RobotName.VPIN_MOMENTUM,
        RobotName.META_LABEL,
        RobotName.ADAPTIVE_EMA,
    ):
        return 150
    if robot is RobotName.PAIRS:
        return 200
    if robot is RobotName.FORMULAIC_LGBM:
        return 80
    return 50
