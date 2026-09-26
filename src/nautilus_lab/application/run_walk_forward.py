from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from decimal import Decimal

from nautilus_lab.application.dtos import (
    BacktestReport,
    BacktestRequest,
    BarFeed,
    FundingFeed,
    MultiWindowReport,
    OrderBookFeed,
    ResearchBacktestPort,
    SelectedParams,
    TickFeed,
    WalkForwardFold,
    WalkForwardReport,
    WalkForwardRequest,
    apply_selected,
    selected_from_request,
)
from nautilus_lab.application.param_grid import iter_param_grid
from nautilus_lab.application.risk import require_simulated_mode
from nautilus_lab.application.run_research_backtest import minimum_bars
from nautilus_lab.application.score import in_sample_score
from nautilus_lab.application.trial_ledger import TrialLedger, record_trials
from nautilus_lab.domain.align import split_aligned_by_window
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.errors import InvalidWindowError
from nautilus_lab.domain.funding import FundingSnapshot
from nautilus_lab.domain.metrics import buy_and_hold_return, vol_matched_from_volatility
from nautilus_lab.domain.order_book import OrderBookSnapshot
from nautilus_lab.domain.regime import RobotName, require_backtest_support
from nautilus_lab.domain.ticks import AggTrade
from nautilus_lab.domain.walk_forward import (
    WalkForwardWindow,
    anchored_window,
    rolling_windows,
    split_by_window,
)
from nautilus_lab.domain.windowing import warmup_tail


class RunWalkForward:
    """Fit parameters on in-sample bars; report only the out-of-sample run."""

    def __init__(
        self,
        engine: ResearchBacktestPort,
        feed: BarFeed,
        tick_feed: TickFeed | None = None,
        book_feed: OrderBookFeed | None = None,
        funding_feed: FundingFeed | None = None,
        *,
        trial_ledger: TrialLedger | None = None,
    ) -> None:
        self._engine = engine
        self._feed = feed
        self._tick_feed = tick_feed
        self._book_feed = book_feed
        self._funding_feed = funding_feed
        # A walk-forward search is a search on the same data: its configurations count
        # toward the trials a later DSR is deflated by (docs/27 R-3).
        self._trial_ledger = trial_ledger

    def execute(self, request: WalkForwardRequest) -> WalkForwardReport:
        require_simulated_mode(request.backtest.mode)
        require_backtest_support(request.backtest.robot)
        embargo = request.embargo_bars or request.backtest.embargo_bars
        if request.backtest.robot in (RobotName.PAIRS, RobotName.FUNDING):
            return self._execute_pairs(request, embargo)
        return self._execute_single(request, embargo)

    def _execute_single(self, request: WalkForwardRequest, embargo: int) -> WalkForwardReport:
        bars = self._feed.load(request.backtest)
        window = request.window or anchored_window(
            bars,
            in_sample_fraction=request.in_sample_fraction,
            embargo_bars=embargo,
        )
        folds = split_by_window(bars, window)
        _require_warmup(request.backtest.robot, len(folds.in_sample), "in-sample")
        _require_warmup(request.backtest.robot, len(folds.out_of_sample), "out-of-sample")
        ticks, books = self._load_events(request.backtest)

        return self._select_and_evaluate(
            request,
            window,
            run_is=lambda candidate: self._engine.run(
                candidate, list(folds.in_sample), ticks, books
            ),
            run_oos=self._single_oos_runner(request, bars, folds.out_of_sample, ticks, books),
        )

    def _single_oos_runner(
        self,
        request: WalkForwardRequest,
        history: Sequence[OhlcvBar],
        oos: Sequence[OhlcvBar],
        ticks: list[AggTrade] | None,
        books: list[OrderBookSnapshot] | None,
    ) -> Callable[[BacktestRequest], BacktestReport]:
        """OOS run over warm-up + window bars, trading only from the window's first bar."""
        warm = warmup_tail(history, oos, _oos_warmup_count(request))
        bars = [*warm, *oos]
        trade_start = oos[0].ts_utc if warm else None

        def run(candidate: BacktestRequest) -> BacktestReport:
            return self._engine.run(replace(candidate, trade_start=trade_start), bars, ticks, books)

        return run

    def _pairs_oos_runner(
        self,
        request: WalkForwardRequest,
        all_bars: dict[str, list[OhlcvBar]],
        oos_bars: dict[str, list[OhlcvBar]],
        funding: list[FundingSnapshot] | None = None,
    ) -> Callable[[BacktestRequest], BacktestReport]:
        ref = _ref_leg(request.backtest)
        warm_ref = warmup_tail(all_bars[ref], oos_bars[ref], _oos_warmup_count(request))
        warm_ts = {bar.ts_utc for bar in warm_ref}
        # Every leg is warmed on the same timestamps as the reference leg, so the spread
        # model never sees one leg's bar without the other's.
        bars = {
            instrument_id: [
                *(bar for bar in all_bars[instrument_id] if bar.ts_utc in warm_ts),
                *oos_bars[instrument_id],
            ]
            for instrument_id in oos_bars
        }
        trade_start = oos_bars[ref][0].ts_utc if warm_ref else None

        def run(candidate: BacktestRequest) -> BacktestReport:
            return self._engine.run_spread(
                replace(candidate, trade_start=trade_start), bars, funding=funding
            )

        return run

    def _load_events(
        self, request: BacktestRequest
    ) -> tuple[list[AggTrade] | None, list[OrderBookSnapshot] | None]:
        """Tick and book series the robot needs, loaded once for all folds.

        The engine cuts them to each run's bar span, so handing the whole series to
        every fold is safe; loading it per fold only re-read the same parquet files.
        Without the book series `ml_obi` never receives a depth update and a
        walk-forward over it reported zero trades as if that were a result.
        """
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
        return ticks, books

    def _execute_pairs(self, request: WalkForwardRequest, embargo: int) -> WalkForwardReport:
        all_bars = self._feed.load_multi(request.backtest)
        ref = _ref_leg(request.backtest)
        reference = list(all_bars[ref])
        window = request.window or anchored_window(
            reference,
            in_sample_fraction=request.in_sample_fraction,
            embargo_bars=embargo,
        )
        is_bars, oos_bars = split_aligned_by_window(all_bars, window)
        _require_warmup(
            request.backtest.robot,
            len(is_bars[ref]),
            "in-sample",
        )
        _require_warmup(
            request.backtest.robot,
            len(oos_bars[ref]),
            "out-of-sample",
        )
        funding = (
            self._funding_feed.load(request.backtest) if self._funding_feed is not None else None
        )
        return self._select_and_evaluate(
            request,
            window,
            run_is=lambda candidate: self._engine.run_spread(candidate, is_bars, funding=funding),
            run_oos=self._pairs_oos_runner(request, all_bars, oos_bars, funding=funding),
        )

    def execute_multi(self, request: WalkForwardRequest) -> MultiWindowReport:
        """Run one walk-forward per rolling fold and aggregate the out-of-sample folds.

        Each fold re-selects parameters on its own in-sample window, so the reported
        spread across folds is a forecast spread rather than one number from one
        arbitrary split. The aggregate is what a single run cannot give: how often the
        robot made money out of sample and how it compares with simply holding.
        """
        require_simulated_mode(request.backtest.mode)
        require_backtest_support(request.backtest.robot)
        if request.folds < 2:
            raise ValueError("multi-window walk-forward needs folds >= 2")
        if request.window is not None:
            raise InvalidWindowError(
                "multi-window runs derive their own windows; drop --is-start/--oos-start"
            )
        embargo = request.embargo_bars or request.backtest.embargo_bars

        if request.backtest.robot in (RobotName.PAIRS, RobotName.FUNDING):
            return self._execute_pairs_multi(request, embargo)
        return self._execute_single_multi(request, embargo)

    def _execute_single_multi(
        self,
        request: WalkForwardRequest,
        embargo: int,
    ) -> MultiWindowReport:
        bars = self._feed.load(request.backtest)
        windows = rolling_windows(
            bars,
            folds=request.folds,
            in_sample_fraction=request.in_sample_fraction,
            embargo_bars=embargo,
        )
        ticks, books = self._load_events(request.backtest)
        folds = [
            self._evaluate_single_fold(request, index, bars, window, ticks, books)
            for index, window in enumerate(windows)
        ]
        return _multi_report(request, folds, len(windows))

    def _evaluate_single_fold(
        self,
        request: WalkForwardRequest,
        index: int,
        bars: Sequence[OhlcvBar],
        window: WalkForwardWindow,
        ticks: list[AggTrade] | None,
        books: list[OrderBookSnapshot] | None,
    ) -> WalkForwardFold:
        split = split_by_window(bars, window)
        _require_warmup(request.backtest.robot, len(split.in_sample), f"fold {index} in-sample")
        _require_warmup(
            request.backtest.robot, len(split.out_of_sample), f"fold {index} out-of-sample"
        )
        return self._run_fold(
            request,
            index,
            window,
            run_is=lambda candidate: self._engine.run(
                candidate, list(split.in_sample), ticks, books
            ),
            run_oos=self._single_oos_runner(request, bars, split.out_of_sample, ticks, books),
            oos_reference=split.out_of_sample,
        )

    def _execute_pairs_multi(
        self,
        request: WalkForwardRequest,
        embargo: int,
    ) -> MultiWindowReport:
        all_bars = self._feed.load_multi(request.backtest)
        ref = _ref_leg(request.backtest)
        windows = rolling_windows(
            list(all_bars[ref]),
            folds=request.folds,
            in_sample_fraction=request.in_sample_fraction,
            embargo_bars=embargo,
        )
        funding = (
            self._funding_feed.load(request.backtest) if self._funding_feed is not None else None
        )
        folds = [
            self._evaluate_pairs_fold(request, index, all_bars, window, funding=funding)
            for index, window in enumerate(windows)
        ]
        return _multi_report(request, folds, len(windows))

    def _evaluate_pairs_fold(
        self,
        request: WalkForwardRequest,
        index: int,
        all_bars: dict[str, list[OhlcvBar]],
        window: WalkForwardWindow,
        funding: list[FundingSnapshot] | None = None,
    ) -> WalkForwardFold:
        ref = _ref_leg(request.backtest)
        is_bars, oos_bars = split_aligned_by_window(all_bars, window)
        _require_warmup(request.backtest.robot, len(is_bars[ref]), f"fold {index} in-sample")
        _require_warmup(request.backtest.robot, len(oos_bars[ref]), f"fold {index} out-of-sample")
        return self._run_fold(
            request,
            index,
            window,
            run_is=lambda candidate: self._engine.run_spread(candidate, is_bars, funding=funding),
            run_oos=self._pairs_oos_runner(request, all_bars, oos_bars, funding=funding),
            oos_reference=oos_bars[ref],
        )

    def _run_fold(
        self,
        request: WalkForwardRequest,
        index: int,
        window: WalkForwardWindow,
        *,
        run_is: Callable[[BacktestRequest], BacktestReport],
        run_oos: Callable[[BacktestRequest], BacktestReport],
        oos_reference: Sequence[OhlcvBar],
    ) -> WalkForwardFold:
        best_params, best_is_report, tried = self._select(request, run_is)
        selected_request = apply_selected(request.backtest, best_params)
        # Only the final fold owns the tearsheet path, otherwise every fold would
        # overwrite the same file and the last one would look like the only result.
        if request.tearsheet_path and index == request.folds - 1:
            selected_request = replace(selected_request, tearsheet_path=request.tearsheet_path)
        oos = run_oos(selected_request)
        return WalkForwardFold(
            index=index,
            selected=best_params,
            candidates_tried=tried,
            in_sample=best_is_report,
            out_of_sample=oos,
            window=window,
            oos_return=window_return(oos, request.backtest.starting_equity),
            buy_and_hold_return=buy_and_hold_return(oos_reference),
            vol_matched_buy_and_hold_return=vol_matched_from_volatility(
                bars=oos_reference,
                strategy_volatility=None if oos.metrics is None else oos.metrics.return_volatility,
            ),
        )

    def _select_and_evaluate(
        self,
        request: WalkForwardRequest,
        window: WalkForwardWindow,
        *,
        run_is: Callable[[BacktestRequest], BacktestReport],
        run_oos: Callable[[BacktestRequest], BacktestReport],
    ) -> WalkForwardReport:
        best_params, best_is_report, tried = self._select(request, run_is)

        selected_request = apply_selected(request.backtest, best_params)
        if request.tearsheet_path:
            selected_request = replace(selected_request, tearsheet_path=request.tearsheet_path)

        oos = run_oos(selected_request)
        return WalkForwardReport(
            selected=best_params,
            candidates_tried=tried,
            in_sample=best_is_report,
            out_of_sample=oos,
            window=window,
            notes=_notes(window, best_params, tried, is_optuna=request.use_optuna),
        )

    def _select(
        self,
        request: WalkForwardRequest,
        run_is: Callable[[BacktestRequest], BacktestReport],
    ) -> tuple[SelectedParams, BacktestReport, int]:
        if request.use_optuna:
            from nautilus_lab.application.optuna_optimizer import OptunaParamOptimizer

            optimizer = OptunaParamOptimizer(
                n_trials=request.optuna_trials,
                seed=request.backtest.seed,
            )
            selected = optimizer.optimize(request.backtest, run_is)
            # Optuna's parameters are not kept per trial; a seeded study replays the same
            # sequence, so "seed + trial number" names the same attempt across runs.
            seed = request.backtest.seed
            labels = [f"optuna seed={seed} trial={index}" for index in range(selected[2])]
        else:
            selected = self._grid_search_params(request, run_is)
            labels = [params.label() for params in iter_param_grid(request.backtest)]
        record_trials(self._trial_ledger, request.backtest, labels)
        return selected

    def _grid_search_params(
        self,
        request: WalkForwardRequest,
        run_is: Callable[[BacktestRequest], BacktestReport],
    ) -> tuple[SelectedParams, BacktestReport, int]:
        best_score: Decimal | None = None
        best_params = selected_from_request(request.backtest)
        best_is_report: BacktestReport | None = None
        tried = 0
        for params in iter_param_grid(request.backtest):
            tried += 1
            candidate = apply_selected(request.backtest, params)
            report = run_is(candidate)
            score = in_sample_score(
                report,
                metric=request.backtest.selection_metric,
                starting_equity=request.backtest.starting_equity,
            )
            if best_is_report is None or best_score is None or score > best_score:
                best_score = score
                best_params = params
                best_is_report = report

        if best_is_report is None:
            raise ValueError("parameter grid is empty")

        return best_params, best_is_report, tried


def window_return(report: BacktestReport, starting_equity: Decimal) -> Decimal | None:
    """Fraction gained or lost over one window. None when the engine reported no balance.

    Public because the CLI journals the single-split out-of-sample number with the same
    definition the rolling folds use; two definitions of "the OOS return" would drift.
    """
    if report.ending_balance is None or starting_equity <= 0:
        return None
    return (report.ending_balance - starting_equity) / starting_equity


def _multi_report(
    request: WalkForwardRequest,
    folds: Sequence[WalkForwardFold],
    fold_count: int,
) -> MultiWindowReport:
    method = "optuna" if request.use_optuna else "grid"
    first, last = folds[0], folds[-1]
    return MultiWindowReport(
        folds=tuple(folds),
        starting_equity=request.backtest.starting_equity,
        notes=(
            f"multi-window walk-forward ({method}): {fold_count} rolling folds, parameters "
            f"re-selected on each fold's own in-sample window; report the out-of-sample "
            f"aggregate. windows=[{first.window.in_sample_start.isoformat()}, "
            f"{last.window.out_of_sample_end.isoformat()})"
        ),
    )


def _oos_warmup_count(request: WalkForwardRequest) -> int:
    if request.oos_warmup_bars is not None:
        return max(0, request.oos_warmup_bars)
    # A book-driven robot has no bar indicators to warm; its window is the book series.
    if request.backtest.robot is RobotName.ML_OBI:
        return 0
    # The same rule `_require_warmup` enforces (the spec validator keeps the two equal).
    return minimum_bars(request.backtest.robot)


def _ref_leg(request: BacktestRequest) -> str:
    if request.robot is RobotName.FUNDING:
        return request.funding_spot_id or "ETH/USDT.SIM"
    return request.pairs.leg_a


def _require_warmup(robot: RobotName, bar_count: int, fold: str) -> None:
    if robot is RobotName.PAIRS:
        minimum = 200
    elif robot in (
        RobotName.REGIME,
        RobotName.VPIN_MOMENTUM,
        RobotName.META_LABEL,
        RobotName.ADAPTIVE_EMA,
    ):
        minimum = 150
    elif robot is RobotName.FORMULAIC_LGBM:
        minimum = 80
    else:
        minimum = 50
    if bar_count < minimum:
        raise ValueError(f"{fold} bar_count must be >= {minimum} so indicators can warm up")


def _notes(
    window: WalkForwardWindow,
    params: SelectedParams,
    tried: int,
    *,
    is_optuna: bool = False,
) -> str:
    method = "optuna" if is_optuna else "grid"
    return (
        f"walk-forward ({method}): parameters selected on in-sample only; "
        f"report out-of-sample. tried={tried} selected={params.label()} "
        f"IS=[{window.in_sample_start.isoformat()}, {window.in_sample_end.isoformat()}) "
        f"OOS=[{window.out_of_sample_start.isoformat()}, {window.out_of_sample_end.isoformat()})"
    )
