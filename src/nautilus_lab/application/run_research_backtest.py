from __future__ import annotations

from nautilus_lab.application.dtos import (
    BacktestReport,
    BacktestRequest,
    BarFeed,
    OrderBookFeed,
    ResearchBacktestPort,
    TickFeed,
)
from nautilus_lab.application.risk import require_simulated_mode
from nautilus_lab.domain.regime import RobotName, require_backtest_support


class RunResearchBacktest:
    def __init__(
        self,
        engine: ResearchBacktestPort,
        feed: BarFeed,
        tick_feed: TickFeed | None = None,
        book_feed: OrderBookFeed | None = None,
    ) -> None:
        self._engine = engine
        self._feed = feed
        self._tick_feed = tick_feed
        self._book_feed = book_feed

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

        ticks = None
        if request.use_tick_vpin or request.use_hawkes:
            if self._tick_feed is None:
                raise ValueError("Tick feed must be provided to use tick_vpin or hawkes")
            ticks = self._tick_feed.load(request)

        books = None
        if request.robot is RobotName.ML_OBI:
            if self._book_feed is None:
                raise ValueError("OrderBook feed must be provided to use ML_OBI")
            books = self._book_feed.load(request)

        return self._engine.run(request, bars, ticks, books)


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
