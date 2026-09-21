from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import Decimal

from nautilus_lab.application.dtos import (
    BacktestReport,
    BacktestRequest,
    BarFeed,
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
from nautilus_lab.application.score import in_sample_score
from nautilus_lab.domain.align import split_aligned_by_window
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.errors import InvalidWindowError
from nautilus_lab.domain.metrics import buy_and_hold_return
from nautilus_lab.domain.regime import RobotName, require_backtest_support
from nautilus_lab.domain.walk_forward import (
    WalkForwardWindow,
    anchored_window,
    rolling_windows,
    split_by_window,
)


class RunWalkForward:
    """Fit parameters on in-sample bars; report only the out-of-sample run."""

    def __init__(
        self,
        engine: ResearchBacktestPort,
        feed: BarFeed,
        tick_feed: TickFeed | None = None,
        book_feed: "OrderBookFeed | None" = None,
    ) -> None:
        self._engine = engine
        self._feed = feed
        self._tick_feed = tick_feed
        self._book_feed = book_feed

    def execute(self, request: WalkForwardRequest) -> WalkForwardReport:
        require_simulated_mode(request.backtest.mode)
        require_backtest_support(request.backtest.robot)
        embargo = request.embargo_bars or request.backtest.embargo_bars
        if request.backtest.robot is RobotName.PAIRS:
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
        ticks = None
        if request.backtest.use_tick_vpin or request.backtest.use_hawkes:
            if self._tick_feed is None:
                raise ValueError("Tick feed must be provided to use tick_vpin or hawkes")
            ticks = self._tick_feed.load(request.backtest)

        return self._select_and_evaluate(
            request,
            window,
            run_is=lambda candidate: self._engine.run(candidate, list(folds.in_sample), ticks),
            run_oos=lambda candidate: self._engine.run(candidate, list(folds.out_of_sample), ticks),
        )

    def _execute_pairs(self, request: WalkForwardRequest, embargo: int) -> WalkForwardReport:
        all_bars = self._feed.load_multi(request.backtest)
        reference = list(all_bars[request.backtest.pairs.leg_a])
        window = request.window or anchored_window(
            reference,
            in_sample_fraction=request.in_sample_fraction,
            embargo_bars=embargo,
        )
        is_bars, oos_bars = split_aligned_by_window(all_bars, window)
        _require_warmup(
            request.backtest.robot,
            len(is_bars[request.backtest.pairs.leg_a]),
            "in-sample",
        )
        _require_warmup(
            request.backtest.robot,
            len(oos_bars[request.backtest.pairs.leg_a]),
            "out-of-sample",
        )
        return self._select_and_evaluate(
            request,
            window,
            run_is=lambda candidate: self._engine.run_spread(candidate, is_bars),
            run_oos=lambda candidate: self._engine.run_spread(candidate, oos_bars),
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

        if request.backtest.robot is RobotName.PAIRS:
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
        folds = [
            self._evaluate_single_fold(request, index, bars, window)
            for index, window in enumerate(windows)
        ]
        return _multi_report(request, folds, len(windows))

    def _evaluate_single_fold(
        self,
        request: WalkForwardRequest,
        index: int,
        bars: Sequence[OhlcvBar],
        window: WalkForwardWindow,
    ) -> WalkForwardFold:
        split = split_by_window(bars, window)
        _require_warmup(request.backtest.robot, len(split.in_sample), f"fold {index} in-sample")
        _require_warmup(
            request.backtest.robot, len(split.out_of_sample), f"fold {index} out-of-sample"
        )
        ticks = None
        if request.backtest.use_tick_vpin or request.backtest.use_hawkes:
            if self._tick_feed is None:
                raise ValueError("Tick feed must be provided to use tick_vpin or hawkes")
            ticks = self._tick_feed.load(request.backtest)

        return self._run_fold(
            request,
            index,
            window,
            run_is=lambda candidate: self._engine.run(candidate, list(split.in_sample), ticks),
            run_oos=lambda candidate: self._engine.run(candidate, list(split.out_of_sample), ticks),
            oos_reference=split.out_of_sample,
        )

    def _execute_pairs_multi(
        self,
        request: WalkForwardRequest,
        embargo: int,
    ) -> MultiWindowReport:
        all_bars = self._feed.load_multi(request.backtest)
        leg_a = request.backtest.pairs.leg_a
        windows = rolling_windows(
            list(all_bars[leg_a]),
            folds=request.folds,
            in_sample_fraction=request.in_sample_fraction,
            embargo_bars=embargo,
        )
        folds = [
            self._evaluate_pairs_fold(request, index, all_bars, window)
            for index, window in enumerate(windows)
        ]
        return _multi_report(request, folds, len(windows))

    def _evaluate_pairs_fold(
        self,
        request: WalkForwardRequest,
        index: int,
        all_bars: dict[str, list[OhlcvBar]],
        window: WalkForwardWindow,
    ) -> WalkForwardFold:
        leg_a = request.backtest.pairs.leg_a
        is_bars, oos_bars = split_aligned_by_window(all_bars, window)
        _require_warmup(request.backtest.robot, len(is_bars[leg_a]), f"fold {index} in-sample")
        _require_warmup(request.backtest.robot, len(oos_bars[leg_a]), f"fold {index} out-of-sample")
        return self._run_fold(
            request,
            index,
            window,
            run_is=lambda candidate: self._engine.run_spread(candidate, is_bars),
            run_oos=lambda candidate: self._engine.run_spread(candidate, oos_bars),
            oos_reference=oos_bars[leg_a],
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
            from dataclasses import replace

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
            from dataclasses import replace

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
            return optimizer.optimize(request.backtest, run_is)
        return self._grid_search_params(request, run_is)

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
            score = in_sample_score(report)
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
