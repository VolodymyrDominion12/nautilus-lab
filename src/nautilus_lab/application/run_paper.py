"""Paper session: a frozen configuration run forward, with the ledger to prove it.

What this is **not**: an out-of-sample report. A walk-forward run selects parameters
on in-sample bars and reports on held-out bars; a paper session selects nothing — it
runs the configuration it was handed, over a window, and records every fill, every
position, and what was still open at the last bar. That makes it the rehearsal step
between "the research says this is a candidate" and "let it touch a real venue",
which is exactly the gap `lab live` is not allowed to fill yet.

Nothing here reaches an exchange: no order is ever submitted anywhere but into the
Nautilus simulation engine, and `require_simulated_mode` refuses `live` outright.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from nautilus_lab.application.dtos import (
    BacktestRequest,
    BarFeed,
    FundingFeed,
    OrderBookFeed,
    PaperBacktestPort,
    PaperSessionReport,
    TickFeed,
)
from nautilus_lab.application.risk import (
    evaluate_entry,
    require_simulated_mode,
    size_position,
    stop_distance,
)
from nautilus_lab.application.run_research_backtest import minimum_bars
from nautilus_lab.domain.adaptive_ema import AdaptiveEmaRouter
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.ema_crossover import EmaCrossover
from nautilus_lab.domain.formulaic_lgbm_strategy import FormulaicLgbmStrategy
from nautilus_lab.domain.regime import RobotName, require_backtest_support
from nautilus_lab.domain.regime_router import RegimeRouter
from nautilus_lab.domain.risk import AccountSnapshot
from nautilus_lab.domain.signals import SignalSide
from nautilus_lab.domain.vpin import BarVpin
from nautilus_lab.domain.vpin_momentum import VpinMomentum
from nautilus_lab.domain.windowing import warmup_tail
from nautilus_lab.infrastructure.lightgbm_classifier import HeuristicDirectionClassifier
from nautilus_lab.infrastructure.paper_trading import PaperTradingLogger

#: Robots a paper session can actually build, mirroring the engine's `_build_robot`.
#: The CLI and the API both validate against this set: a name that is missing here
#: would otherwise run whichever robot the engine falls back to while the artifact
#: recorded the name that was asked for.
PAPER_SUPPORTED_ROBOTS: frozenset[RobotName] = frozenset(
    {
        RobotName.REGIME,
        RobotName.EMA,
        RobotName.PAIRS,
        RobotName.VPIN_MOMENTUM,
        RobotName.FORMULAIC_LGBM,
        RobotName.META_LABEL,
        RobotName.ADAPTIVE_EMA,
        RobotName.ML_OBI,
        RobotName.FUNDING,
    }
)


def require_paper_support(robot: RobotName) -> None:
    """Fail closed when a robot has no paper path, instead of substituting one."""
    require_backtest_support(robot)
    if robot not in PAPER_SUPPORTED_ROBOTS:
        supported = ", ".join(sorted(item.value for item in PAPER_SUPPORTED_ROBOTS))
        msg = (
            f"paper mode cannot build robot {robot.value!r}; supported: {supported}. "
            "Refusing rather than substituting a different robot."
        )
        raise ValueError(msg)


class RunPaperSession:
    """Run one paper session: load bars, run the engine, return the ledger.

    The bar source is a `BarFeed`, so the historical catalog and a future streaming
    feed are interchangeable here — the session does not care where closed bars came
    from, only that they are closed.
    """

    def __init__(
        self,
        engine: PaperBacktestPort,
        feed: BarFeed,
        tick_feed: TickFeed | None = None,
        book_feed: OrderBookFeed | None = None,
        funding_feed: FundingFeed | None = None,
    ) -> None:
        self._engine = engine
        self._feed = feed
        self._tick_feed = tick_feed
        self._book_feed = book_feed
        self._funding_feed = funding_feed

    def execute(self, request: BacktestRequest) -> PaperSessionReport:
        require_simulated_mode(request.mode)
        require_paper_support(request.robot)
        minimum = minimum_bars(request.robot)
        if request.bar_count < minimum:
            raise ValueError(f"bar_count must be >= {minimum} so indicators can warm up")

        if request.robot is RobotName.PAIRS:
            multi = self._feed.load_multi(request)
            # Both legs are tailed by the same count; they arrive aligned by an inner
            # join, so equal tails stay aligned and the spread never sees a stale leg.
            return self._engine.run_paper_spread(
                request, {key: _tail(value, request.bar_count) for key, value in multi.items()}
            )

        if request.robot is RobotName.FUNDING:
            multi = self._feed.load_multi(request)
            funding = self._funding_feed.load(request) if self._funding_feed is not None else None
            return self._engine.run_paper_spread(
                request,
                {key: _tail(value, request.bar_count) for key, value in multi.items()},
                funding=funding,
            )

        # `bar_count` is a window length here, not a floor: a session runs the most
        # recent closed bars forward, which is what makes it a rehearsal rather than
        # another look at the whole history.
        history = self._feed.load(request)
        bars = _tail(history, request.bar_count)
        # The session window is traded from its first bar: the bars right before it only
        # warm the indicators (a regime robot otherwise sat silent for ~150 bars).
        warm = [] if request.robot is RobotName.ML_OBI else warmup_tail(history, bars, minimum)
        if warm:
            request = replace(request, trade_start=bars[0].ts_utc)
            bars = [*warm, *bars]

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

        return self._engine.run_paper(request, bars, ticks, books)


def _tail(bars: list[OhlcvBar], count: int) -> list[OhlcvBar]:
    """The last `count` bars, or all of them when the window is not shorter."""
    if count <= 0:
        return list(bars)
    return list(bars[-count:])


class RunPaperResearch:
    """Dry-run order preview: which orders *would* be sent, and nothing else.

    Kept separate from `RunPaperSession` on purpose. This one holds no account, no
    position and no PnL — it answers "does the robot produce signals at all", which is
    a useful smoke check but must never be mistaken for a session result. `lab paper`
    runs the session; the API preview and the smoke tests use this.
    """

    def __init__(self, logger: PaperTradingLogger | None = None) -> None:
        self._logger = logger or PaperTradingLogger()

    def execute(self, request: BacktestRequest, bars: list[OhlcvBar]) -> PaperTradingLogger:
        equity = request.starting_equity
        peak = equity
        day_start = equity
        robot = _build_robot(request)
        for bar in bars:
            signal = robot.on_bar(bar)
            if signal is None or signal.side is SignalSide.FLAT:
                continue
            snapshot = AccountSnapshot(
                equity=equity,
                peak_equity=peak,
                day_start_equity=day_start,
                open_positions=0,
            )
            if not evaluate_entry(snapshot, request.risk).allowed:
                continue
            distance = stop_distance(bar.close, request.risk)
            qty = size_position(
                equity=equity,
                price=bar.close,
                stop_distance=distance,
                risk_fraction=request.risk.risk_per_trade,
                qty_step=Decimal("0.001"),
            )
            if qty > 0:
                self._logger.log_signal(signal, qty)
        return self._logger


def _build_robot(
    request: BacktestRequest,
) -> EmaCrossover | RegimeRouter | VpinMomentum | FormulaicLgbmStrategy | AdaptiveEmaRouter:
    """Build the domain robot for a dry-run paper preview.

    Each branch is an explicit mapping so that a new `PAPER_SUPPORTED_ROBOTS` entry
    cannot silently fall through to `regime` and hide a missing implementation.
    `RunPaperSession` uses the Nautilus engine instead and has its own `_build_robot`
    there; this function is only for `RunPaperResearch`.
    """
    if request.robot is RobotName.EMA:
        return EmaCrossover(
            instrument_id=request.instrument_id,
            fast_period=request.fast_ema,
            slow_period=request.slow_ema,
        )
    if request.robot is RobotName.ADAPTIVE_EMA:
        return AdaptiveEmaRouter(
            instrument_id=request.instrument_id,
            params=request.adaptive_params,
        )
    if request.robot is RobotName.VPIN_MOMENTUM:
        vpin = BarVpin(
            bucket_volume=request.vpin_bucket_volume,
            toxic_threshold=request.vpin_toxic_threshold,
        )
        return VpinMomentum(
            instrument_id=request.instrument_id,
            vpin=vpin,
            ema_period=request.vpin_momentum_ema_period,
            atr_multiple=request.vpin_momentum_atr_multiple,
        )
    if request.robot is RobotName.FORMULAIC_LGBM:
        # Dry-run preview uses the heuristic classifier: the offline-trained model is only
        # required for the Nautilus engine run (RunPaperSession), not for signal counting.
        classifier = HeuristicDirectionClassifier()
        return FormulaicLgbmStrategy(
            instrument_id=request.instrument_id,
            classifier=classifier,
            threshold=request.formulaic_threshold,
        )
    if request.robot is RobotName.REGIME:
        return RegimeRouter(
            instrument_id=request.instrument_id,
            params=request.regime,
        )
    # All remaining PAPER_SUPPORTED_ROBOTS (pairs, meta_label, ml_obi) run through
    # RunPaperSession/the engine and cannot produce a dry-run signal count here.
    raise NotImplementedError(
        f"robot {request.robot.value!r} has no dry-run path in RunPaperResearch; "
        "use RunPaperSession for a full paper session with this robot."
    )
