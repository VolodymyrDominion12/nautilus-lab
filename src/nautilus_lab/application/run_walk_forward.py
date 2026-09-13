from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from nautilus_lab.application.dtos import (
    BacktestReport,
    BacktestRequest,
    BarFeed,
    ResearchBacktestPort,
    SelectedParams,
    WalkForwardReport,
    WalkForwardRequest,
    apply_selected,
    selected_from_request,
)
from nautilus_lab.application.param_grid import iter_param_grid
from nautilus_lab.application.risk import require_simulated_mode
from nautilus_lab.application.score import in_sample_score
from nautilus_lab.domain.align import split_aligned_by_window
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.walk_forward import (
    WalkForwardWindow,
    anchored_window,
    split_by_window,
)


class RunWalkForward:
    """Fit parameters on in-sample bars; report only the out-of-sample run."""

    def __init__(self, engine: ResearchBacktestPort, feed: BarFeed) -> None:
        self._engine = engine
        self._feed = feed

    def execute(self, request: WalkForwardRequest) -> WalkForwardReport:
        require_simulated_mode(request.backtest.mode)
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
        return self._select_and_evaluate(
            request,
            window,
            run_is=lambda candidate: self._engine.run(candidate, list(folds.in_sample)),
            run_oos=lambda candidate: self._engine.run(candidate, list(folds.out_of_sample)),
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

    def _select_and_evaluate(
        self,
        request: WalkForwardRequest,
        window: WalkForwardWindow,
        *,
        run_is: Callable[[BacktestRequest], BacktestReport],
        run_oos: Callable[[BacktestRequest], BacktestReport],
    ) -> WalkForwardReport:
        if request.use_optuna:
            from nautilus_lab.application.optuna_optimizer import OptunaParamOptimizer

            optimizer = OptunaParamOptimizer(
                n_trials=request.optuna_trials,
                seed=request.backtest.seed,
            )
            best_params, best_is_report, tried = optimizer.optimize(request.backtest, run_is)
        else:
            best_params, best_is_report, tried = self._grid_search_params(request, run_is)

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


def _require_warmup(robot: RobotName, bar_count: int, fold: str) -> None:
    minimum = 200 if robot is RobotName.PAIRS else 150 if robot is RobotName.REGIME else 50
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
