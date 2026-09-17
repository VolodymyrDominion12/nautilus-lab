from __future__ import annotations

from decimal import Decimal

from nautilus_lab.application.dtos import BacktestRequest
from nautilus_lab.application.risk import evaluate_entry, size_position, stop_distance
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.ema_crossover import EmaCrossover
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.regime_router import RegimeRouter
from nautilus_lab.domain.risk import AccountSnapshot
from nautilus_lab.domain.signals import SignalSide
from nautilus_lab.infrastructure.paper_trading import PaperTradingLogger

#: Robots `lab paper` can actually build. `_build_robot` maps only EMA to `EmaCrossover`
#: and everything else to `RegimeRouter`, so any other name would run the regime robot
#: while the artifact recorded the name that was asked for. The CLI restricts its
#: `--robot` choices to exactly this set (cli.py) and the API validates against it too.
PAPER_SUPPORTED_ROBOTS: frozenset[RobotName] = frozenset({RobotName.REGIME, RobotName.EMA})


class RunPaperResearch:
    """Paper mode: public-data path, log hypothetical orders only."""

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


def _build_robot(request: BacktestRequest) -> EmaCrossover | RegimeRouter:
    if request.robot is RobotName.EMA:
        return EmaCrossover(
            instrument_id=request.instrument_id,
            fast_period=request.fast_ema,
            slow_period=request.slow_ema,
        )
    return RegimeRouter(
        instrument_id=request.instrument_id,
        params=request.regime,
    )
