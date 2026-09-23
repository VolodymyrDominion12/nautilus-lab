from __future__ import annotations

import statistics
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from nautilus_lab.domain.adaptive_ema import AdaptiveEmaParams
from nautilus_lab.domain.bars import BarOrigin, OhlcvBar
from nautilus_lab.domain.deflated_sharpe import DeflatedSharpeResult
from nautilus_lab.domain.fees import FeeSchedule
from nautilus_lab.domain.metrics import BacktestMetrics
from nautilus_lab.domain.order_book import OrderBookSnapshot
from nautilus_lab.domain.pairs.params import PairsParams
from nautilus_lab.domain.regime import RegimeParams, RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.risk_overlay import RiskOverlay
from nautilus_lab.domain.ticks import AggTrade
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
    use_tick_vpin: bool = False
    vpin_bucket_volume: Decimal = Decimal("1000")
    vpin_toxic_threshold: Decimal = Decimal("0.7")
    use_hawkes: bool = False
    hawkes_baseline: Decimal = Decimal("0.1")
    hawkes_alpha: Decimal = Decimal("0.5")
    hawkes_beta: Decimal = Decimal("1.0")
    hawkes_toxic_threshold: Decimal = Decimal("2.0")
    vpin_momentum_ema_period: int = 50
    vpin_momentum_atr_multiple: Decimal = Decimal("2")
    formulaic_model_path: str | None = None
    formulaic_threshold: Decimal = Decimal("0.55")
    meta_label_model_path: str | None = None
    meta_label_threshold: Decimal = Decimal("0.55")
    adaptive_params: AdaptiveEmaParams = field(default_factory=AdaptiveEmaParams)
    tearsheet_path: str | None = None


@dataclass(frozen=True, slots=True)
class BacktestReport:
    fills: int
    positions: int
    ending_balance: Decimal | None
    notes: str
    metrics: BacktestMetrics | None = None
    tearsheet_path: str | None = None
    # (reason, count) per circuit breaker that refused at least one entry, in the
    # order each first fired. Empty means no entry was ever blocked — which is
    # itself information, and different from "we did not look".
    risk_breaches: tuple[tuple[str, int], ...] = ()


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
    # Rows in the taker-flow series written alongside the bars (kline field 9). Zero
    # means either "the feed does not carry the field" or "no taker-flow store was
    # wired" — both are visible in the CLI line instead of being a silent absence.
    taker_flow_rows: int = 0


@dataclass(frozen=True, slots=True)
class IngestAggTradesRequest:
    """Ingest request for the aggregated-trade (tick) series.

    No ``interval`` and no ``bar_type``: tick data is event-driven, not periodic.
    The ``instrument_id`` is derived from ``symbol`` by the composition root using
    the same ``binance_symbol_to_instrument_id`` helper as the kline ingest.
    """

    mode: TradingMode
    symbol: str
    instrument_id: str
    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class IngestAggTradesReport:
    trades_written: int
    first_ts: datetime
    last_ts: datetime
    catalog_path: str
    source: str
    symbol: str


@dataclass(frozen=True, slots=True)
class FundingIngestRequest:
    """Ingest request for the funding series.

    No interval and no bar_type: funding settles on the exchange's own schedule, not
    on a chart interval.
    """

    mode: TradingMode
    symbol: str
    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class FundingIngestReport:
    snapshots_written: int
    first_ts: datetime
    last_ts: datetime
    catalog_path: str
    source: str
    symbol: str
    #: Settlements whose index price could not be joined. Non-zero is not an error,
    #: but the basis gate cannot be evaluated on those rows, so the count is reported
    #: instead of hidden behind a fabricated index price.
    missing_index_price: int = 0


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
    formulaic_threshold: Decimal = Decimal("0.55")
    meta_label_threshold: Decimal = Decimal("0.55")
    adaptive_period: int = 40
    adaptive_selectivity: Decimal = Decimal("0.5")

    def label(self) -> str:
        return (
            f"fast_ema={self.fast_ema} slow_ema={self.slow_ema} "
            f"donchian={self.donchian_period} bb_k={self.bb_k} "
            f"z_entry={self.z_entry} formulaic_threshold={self.formulaic_threshold} "
            f"meta_label_threshold={self.meta_label_threshold} "
            f"adaptive_period={self.adaptive_period} "
            f"adaptive_selectivity={self.adaptive_selectivity}"
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

    @property
    def breakeven_costs(self) -> tuple[Decimal, ...]:
        """Per-fold breakeven costs, only from folds that actually traded.

        A fold with no fills has no breakeven (None), and folding it in as zero
        would drag the mean towards a number nobody measured.
        """
        values: list[Decimal] = []
        for fold in self.folds:
            metrics = fold.out_of_sample.metrics
            if metrics is not None and metrics.breakeven_cost is not None:
                values.append(metrics.breakeven_cost)
        return tuple(values)

    @property
    def mean_breakeven_cost(self) -> Decimal | None:
        values = self.breakeven_costs
        if not values:
            return None
        return sum(values, Decimal("0")) / Decimal(len(values))

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
    def run(
        self,
        request: BacktestRequest,
        bars: list[OhlcvBar],
        ticks: list[AggTrade] | None = None,
        books: list[OrderBookSnapshot] | None = None,
    ) -> BacktestReport: ...

    def run_spread(
        self,
        request: BacktestRequest,
        bars_by_instrument: dict[str, list[OhlcvBar]],
    ) -> BacktestReport: ...


@dataclass(frozen=True, slots=True)
class OverfitAuditRequest:
    """One CSCV audit: score every grid configuration on every contiguous block."""

    backtest: BacktestRequest
    blocks: int = 8

    def __post_init__(self) -> None:
        if self.blocks < 2:
            raise ValueError("blocks must be >= 2 for a symmetric split")


def index_of_best_configuration(matrix: tuple[tuple[Decimal | None, ...], ...]) -> int:
    """Index of the configuration (column) with the highest summed block scores.

    Rows are blocks; `zip(*matrix)` yields one column per grid configuration.
    Each total walks only that column — it must not re-iterate every column.
    """
    best_index = 0
    best_total: Decimal | None = None
    for index, column in enumerate(zip(*matrix, strict=True)):
        total = Decimal("0")
        for value in column:
            if value is not None:
                total += value
        if best_total is None or total > best_total:
            best_index = index
            best_total = total
    return best_index


@dataclass(frozen=True, slots=True)
class OverfitAuditReport:
    """Probability of backtest overfitting, plus the matrix it was computed from.

    `block_returns` is `blocks x configurations`; a `None` cell means the engine
    reported no balance for that run, which is scored as the worst possible outcome
    instead of being silently dropped (dropping it would shorten the matrix and
    quietly change which configurations are compared).

    `deflated_sharpe` comes from the same matrix — PBO and DSR must never be computed
    from different evidence. It judges the winning configuration against the best Sharpe
    that the same number of zero-skill trials would have produced, and it may legitimately
    be undefined (too few blocks), in which case its `summary_line()` says so.
    """

    pbo: Decimal
    split_count: int
    configuration_count: int
    blocks: int
    block_returns: tuple[tuple[Decimal | None, ...], ...]
    labels: tuple[str, ...]
    notes: str
    deflated_sharpe: DeflatedSharpeResult

    @property
    def is_meaningful(self) -> bool:
        return self.configuration_count >= 2 and self.split_count >= 2

    def best_configuration_index(self) -> int:
        """Index of the configuration with the best mean score across all blocks."""
        return index_of_best_configuration(self.block_returns)

    def summary_line(self) -> str:
        if not self.is_meaningful:
            return (
                f"PBO undefined: {self.configuration_count} configurations x "
                f"{self.blocks} blocks (need >= 2 configurations)"
            )
        verdict = (
            "selection generalises"
            if self.pbo < Decimal("0.5")
            else "selection is no better than chance"
        )
        return (
            f"PBO={self.pbo} over {self.split_count} splits x "
            f"{self.configuration_count} configurations on {self.blocks} blocks ({verdict})"
        )


class BarFeed(Protocol):
    def load(self, request: BacktestRequest) -> list[OhlcvBar]: ...

    def load_multi(self, request: BacktestRequest) -> dict[str, list[OhlcvBar]]: ...


class TickFeed(Protocol):
    def load(self, request: BacktestRequest) -> list[AggTrade]: ...


class OrderBookFeed(Protocol):
    def load(self, request: BacktestRequest) -> list[OrderBookSnapshot]: ...


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
        formulaic_threshold=request.formulaic_threshold,
        meta_label_threshold=request.meta_label_threshold,
        adaptive_period=request.adaptive_params.base_period,
        adaptive_selectivity=request.adaptive_params.selectivity,
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
        formulaic_threshold=params.formulaic_threshold,
        meta_label_threshold=params.meta_label_threshold,
        adaptive_params=replace(
            request.adaptive_params,
            base_period=params.adaptive_period,
            selectivity=params.adaptive_selectivity,
        ),
    )
