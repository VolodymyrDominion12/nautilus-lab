from __future__ import annotations

import statistics
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from nautilus_lab.domain.bars import BarOrigin, OhlcvBar
from nautilus_lab.domain.fees import FeeSchedule
from nautilus_lab.domain.metrics import BacktestMetrics
from nautilus_lab.domain.pairs.params import PairsParams
from nautilus_lab.domain.regime import RegimeParams, RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.risk_overlay import RiskOverlay
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.domain.walk_forward import WalkForwardWindow


@dataclass(frozen=True, slots=True)
class BacktestRequest:
    mode: TradingMode
    instrument_id: str
    bar_count: int
    starting_equity: Decimal
    risk: RiskLimits
    risk_overlay: RiskOverlay = field(default_factory=RiskOverlay)
    robot: RobotName = RobotName.REGIME
    fast_ema: int = 10
    slow_ema: int = 20
    regime: RegimeParams = field(default_factory=RegimeParams)
    pairs: PairsParams = field(default_factory=PairsParams)
    seed: int = 42
    source: BarOrigin = BarOrigin.SYNTHETIC
    bar_type: str = "ETH/USDT.SIM-1-MINUTE-LAST-EXTERNAL"
    bar_types: tuple[str, ...] = ()
    instrument_ids: tuple[str, ...] = ()
    start: datetime | None = None
    end: datetime | None = None
    fee_schedule: FeeSchedule = field(default_factory=FeeSchedule.binance_spot_vip0)
    embargo_bars: int = 0
    stress_slice: str | None = None
    use_bar_vpin: bool = False
    vpin_bucket_volume: Decimal = Decimal("1000")
    vpin_toxic_threshold: Decimal = Decimal("0.7")
    vpin_momentum_ema_period: int = 50
    vpin_momentum_atr_multiple: Decimal = Decimal("2")
    formulaic_model_path: str | None = None
    formulaic_threshold: Decimal = Decimal("0.55")
    tearsheet_path: str | None = None


@dataclass(frozen=True, slots=True)
class BacktestReport:
    fills: int
    positions: int
    ending_balance: Decimal | None
    notes: str
    metrics: BacktestMetrics | None = None
    tearsheet_path: str | None = None


@dataclass(frozen=True, slots=True)
class IngestRequest:
    mode: TradingMode
    symbol: str
    interval: str
    instrument_id: str
    bar_type: str
    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class IngestReport:
    bars_written: int
    first_ts: datetime
    last_ts: datetime
    catalog_path: str
    source: str
    symbol: str = ""


@dataclass(frozen=True, slots=True)
class WalkForwardRequest:
    backtest: BacktestRequest
    window: WalkForwardWindow | None = None
    in_sample_fraction: Decimal = Decimal("0.7")
    embargo_bars: int = 0
    use_optuna: bool = False
    optuna_trials: int = 20
    tearsheet_path: str | None = None
    folds: int = 1


@dataclass(frozen=True, slots=True)
class SelectedParams:
    fast_ema: int
    slow_ema: int
    donchian_period: int
    bb_period: int
    bb_k: Decimal
    enter_trend_er: Decimal
    exit_trend_er: Decimal
    z_entry: Decimal = Decimal("2")
    z_exit: Decimal = Decimal("0.5")
    vpin_ema_period: int = 50
    vpin_atr_multiple: Decimal = Decimal("2")

    def label(self) -> str:
        return (
            f"fast_ema={self.fast_ema} slow_ema={self.slow_ema} "
            f"donchian={self.donchian_period} bb_k={self.bb_k} "
            f"z_entry={self.z_entry}"
        )


@dataclass(frozen=True, slots=True)
class WalkForwardReport:
    selected: SelectedParams
    candidates_tried: int
    in_sample: BacktestReport
    out_of_sample: BacktestReport
    window: WalkForwardWindow
    notes: str


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    """One rolling fold: parameters chosen on its in-sample block, scored on its OOS."""

    index: int
    selected: SelectedParams
    candidates_tried: int
    in_sample: BacktestReport
    out_of_sample: BacktestReport
    window: WalkForwardWindow
    oos_return: Decimal | None = None
    buy_and_hold_return: Decimal | None = None


@dataclass(frozen=True, slots=True)
class MultiWindowReport:
    """Out-of-sample results from several consecutive folds.

    A single anchored split reports one number from one stretch of history, which
    cannot separate an edge from luck — the same robot scored +14.9% and -10.1% on
    two different out-of-sample stretches of the same symbol. The aggregate here is
    the honest summary: how often the robot made money out of sample, how far the
    folds disagree, and how it compares with simply holding the instrument.
    """

    folds: tuple[WalkForwardFold, ...]
    starting_equity: Decimal
    notes: str

    @property
    def oos_returns(self) -> tuple[Decimal, ...]:
        return tuple(fold.oos_return for fold in self.folds if fold.oos_return is not None)

    @property
    def profitable_folds(self) -> int:
        return sum(1 for value in self.oos_returns if value > 0)

    @property
    def mean_oos_return(self) -> Decimal | None:
        values = self.oos_returns
        if not values:
            return None
        return sum(values, Decimal("0")) / Decimal(len(values))

    @property
    def median_oos_return(self) -> Decimal | None:
        values = self.oos_returns
        return statistics.median(values) if values else None

    @property
    def worst_oos_return(self) -> Decimal | None:
        values = self.oos_returns
        return min(values) if values else None

    @property
    def best_oos_return(self) -> Decimal | None:
        values = self.oos_returns
        return max(values) if values else None

    @property
    def mean_buy_and_hold_return(self) -> Decimal | None:
        values = tuple(
            fold.buy_and_hold_return for fold in self.folds if fold.buy_and_hold_return is not None
        )
        if not values:
            return None
        return sum(values, Decimal("0")) / Decimal(len(values))

    @property
    def total_oos_fills(self) -> int:
        return sum(fold.out_of_sample.fills for fold in self.folds)

    def beats_buy_and_hold(self) -> bool | None:
        """True when the robot out-earned holding the instrument on average.

        None when either side is unmeasurable — never guess a verdict.
        """
        robot = self.mean_oos_return
        baseline = self.mean_buy_and_hold_return
        if robot is None or baseline is None:
            return None
        return robot > baseline

    def summary_line(self) -> str:
        """One-line out-of-sample verdict, safe to paste into a notification."""

        def percent(value: Decimal | None) -> str:
            return "n/a" if value is None else f"{value * 100:.2f}%"

        verdict = self.beats_buy_and_hold()
        comparison = (
            "n/a" if verdict is None else "beats buy&hold" if verdict else "does not beat buy&hold"
        )
        return (
            f"folds={len(self.folds)} profitable={self.profitable_folds}/{len(self.folds)} "
            f"mean_oos={percent(self.mean_oos_return)} "
            f"median_oos={percent(self.median_oos_return)} "
            f"worst={percent(self.worst_oos_return)} best={percent(self.best_oos_return)} "
            f"mean_buy_hold={percent(self.mean_buy_and_hold_return)} ({comparison}) "
            f"oos_fills={self.total_oos_fills}"
        )


class ResearchBacktestPort(Protocol):
    def run(self, request: BacktestRequest, bars: list[OhlcvBar]) -> BacktestReport: ...

    def run_spread(
        self,
        request: BacktestRequest,
        bars_by_instrument: dict[str, list[OhlcvBar]],
    ) -> BacktestReport: ...


class BarFeed(Protocol):
    def load(self, request: BacktestRequest) -> list[OhlcvBar]: ...

    def load_multi(self, request: BacktestRequest) -> dict[str, list[OhlcvBar]]: ...


def selected_from_request(request: BacktestRequest) -> SelectedParams:
    return SelectedParams(
        fast_ema=request.fast_ema,
        slow_ema=request.slow_ema,
        donchian_period=request.regime.donchian_period,
        bb_period=request.regime.bb_period,
        bb_k=request.regime.bb_k,
        enter_trend_er=request.regime.enter_trend_er,
        exit_trend_er=request.regime.exit_trend_er,
        z_entry=request.pairs.z_entry,
        z_exit=request.pairs.z_exit,
        vpin_ema_period=request.vpin_momentum_ema_period,
        vpin_atr_multiple=request.vpin_momentum_atr_multiple,
    )


def apply_selected(request: BacktestRequest, params: SelectedParams) -> BacktestRequest:
    return replace(
        request,
        fast_ema=params.fast_ema,
        slow_ema=params.slow_ema,
        regime=replace(
            request.regime,
            donchian_period=params.donchian_period,
            bb_period=params.bb_period,
            bb_k=params.bb_k,
            enter_trend_er=params.enter_trend_er,
            exit_trend_er=params.exit_trend_er,
        ),
        pairs=replace(
            request.pairs,
            z_entry=params.z_entry,
            z_exit=params.z_exit,
        ),
        vpin_momentum_ema_period=params.vpin_ema_period,
        vpin_momentum_atr_multiple=params.vpin_atr_multiple,
    )
