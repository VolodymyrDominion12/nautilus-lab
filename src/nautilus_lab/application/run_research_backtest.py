from __future__ import annotations

from nautilus_lab.application.dtos import BacktestReport, BacktestRequest, ResearchBacktestPort
from nautilus_lab.application.risk import require_simulated_mode
from nautilus_lab.domain.regime import RobotName


class RunResearchBacktest:
    def __init__(self, engine: ResearchBacktestPort) -> None:
        self._engine = engine

    def execute(self, request: BacktestRequest) -> BacktestReport:
        require_simulated_mode(request.mode)
        minimum = 150 if request.robot is RobotName.REGIME else 50
        if request.bar_count < minimum:
            raise ValueError(f"bar_count must be >= {minimum} so indicators can warm up")
        return self._engine.run(request)
