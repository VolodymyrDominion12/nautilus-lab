from __future__ import annotations

from nautilus_lab.application.dtos import (
    BacktestReport,
    BacktestRequest,
    BarFeed,
    ResearchBacktestPort,
)
from nautilus_lab.application.risk import require_simulated_mode
from nautilus_lab.domain.regime import RobotName


class RunResearchBacktest:
    def __init__(self, engine: ResearchBacktestPort, feed: BarFeed) -> None:
        self._engine = engine
        self._feed = feed

    def execute(self, request: BacktestRequest) -> BacktestReport:
        require_simulated_mode(request.mode)
        bars = self._feed.load(request)
        minimum = 150 if request.robot is RobotName.REGIME else 50
        if len(bars) < minimum:
            raise ValueError(f"bar_count must be >= {minimum} so indicators can warm up")
        return self._engine.run(request, bars)
