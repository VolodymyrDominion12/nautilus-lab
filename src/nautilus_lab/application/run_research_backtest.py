from __future__ import annotations

from nautilus_lab.application.dtos import BacktestReport, BacktestRequest, ResearchBacktestPort
from nautilus_lab.application.risk import require_simulated_mode


class RunResearchBacktest:
    def __init__(self, engine: ResearchBacktestPort) -> None:
        self._engine = engine

    def execute(self, request: BacktestRequest) -> BacktestReport:
        require_simulated_mode(request.mode)
        if request.bar_count < 50:
            raise ValueError("bar_count must be >= 50 so EMAs can warm up")
        return self._engine.run(request)
