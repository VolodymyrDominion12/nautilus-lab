from __future__ import annotations

import logging
from collections.abc import Callable
from decimal import Decimal

from nautilus_lab.application.dtos import (
    BacktestReport,
    BacktestRequest,
    SelectedParams,
    apply_selected,
    selected_from_request,
)
from nautilus_lab.application.score import in_sample_score
from nautilus_lab.domain.regime import RobotName

logger = logging.getLogger(__name__)


class OptunaParamOptimizer:
    """Bayesian hyperparameter optimization using Optuna TPE.

    Fits on in-sample bars only; never peeks at out-of-sample data.
    """

    def __init__(self, n_trials: int = 20, seed: int = 42) -> None:
        self._n_trials = n_trials
        self._seed = seed

    def optimize(
        self,
        request: BacktestRequest,
        run_is: Callable[[BacktestRequest], BacktestReport],
    ) -> tuple[SelectedParams, BacktestReport, int]:
        try:
            import optuna
        except ImportError as exc:
            raise RuntimeError("optuna is not installed; run: uv sync --extra research") from exc

        # Reduce logging noise during optimization trials
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        sampler = optuna.samplers.TPESampler(seed=self._seed)
        study = optuna.create_study(direction="maximize", sampler=sampler)

        base = selected_from_request(request)
        best_report: BacktestReport | None = None
        best_params: SelectedParams = base

        def objective(trial: optuna.Trial) -> float:
            nonlocal best_report, best_params

            if request.robot is RobotName.PAIRS:
                z_entry = Decimal(str(round(trial.suggest_float("z_entry", 1.2, 3.0, step=0.2), 2)))
                z_exit = Decimal(str(round(trial.suggest_float("z_exit", 0.1, 1.0, step=0.1), 2)))
                params = SelectedParams(
                    fast_ema=base.fast_ema,
                    slow_ema=base.slow_ema,
                    donchian_period=base.donchian_period,
                    bb_period=base.bb_period,
                    bb_k=base.bb_k,
                    enter_trend_er=base.enter_trend_er,
                    exit_trend_er=base.exit_trend_er,
                    z_entry=z_entry,
                    z_exit=z_exit,
                )
            elif request.robot is RobotName.EMA:
                fast = trial.suggest_int("fast_ema", 5, 20)
                slow = trial.suggest_int("slow_ema", fast + 5, 60)
                params = SelectedParams(
                    fast_ema=fast,
                    slow_ema=slow,
                    donchian_period=base.donchian_period,
                    bb_period=base.bb_period,
                    bb_k=base.bb_k,
                    enter_trend_er=base.enter_trend_er,
                    exit_trend_er=base.exit_trend_er,
                    z_entry=base.z_entry,
                    z_exit=base.z_exit,
                )
            elif request.robot is RobotName.VPIN_MOMENTUM:
                params = SelectedParams(
                    fast_ema=base.fast_ema,
                    slow_ema=base.slow_ema,
                    donchian_period=base.donchian_period,
                    bb_period=base.bb_period,
                    bb_k=base.bb_k,
                    enter_trend_er=base.enter_trend_er,
                    exit_trend_er=base.exit_trend_er,
                    z_entry=base.z_entry,
                    z_exit=base.z_exit,
                    vpin_ema_period=trial.suggest_int("vpin_ema_period", 20, 100, step=10),
                    vpin_atr_multiple=Decimal(
                        str(round(trial.suggest_float("vpin_atr_multiple", 1.0, 4.0, step=0.5), 2))
                    ),
                )
            elif request.robot is RobotName.FORMULAIC_LGBM:
                params = SelectedParams(
                    fast_ema=base.fast_ema,
                    slow_ema=base.slow_ema,
                    donchian_period=base.donchian_period,
                    bb_period=base.bb_period,
                    bb_k=base.bb_k,
                    enter_trend_er=base.enter_trend_er,
                    exit_trend_er=base.exit_trend_er,
                    z_entry=base.z_entry,
                    z_exit=base.z_exit,
                    formulaic_threshold=Decimal(
                        str(
                            round(
                                trial.suggest_float("formulaic_threshold", 0.35, 0.75, step=0.05), 2
                            )
                        )
                    ),
                )
            elif request.robot is RobotName.META_LABEL:
                params = SelectedParams(
                    fast_ema=base.fast_ema,
                    slow_ema=base.slow_ema,
                    donchian_period=base.donchian_period,
                    bb_period=base.bb_period,
                    bb_k=base.bb_k,
                    enter_trend_er=base.enter_trend_er,
                    exit_trend_er=base.exit_trend_er,
                    z_entry=base.z_entry,
                    z_exit=base.z_exit,
                    meta_label_threshold=Decimal(
                        str(
                            round(
                                trial.suggest_float("meta_label_threshold", 0.35, 0.75, step=0.05),
                                2,
                            )
                        )
                    ),
                )
            else:
                donchian = trial.suggest_int("donchian_period", 10, 50, step=5)
                bb_period = trial.suggest_int("bb_period", 10, 50, step=5)
                bb_k = Decimal(str(round(trial.suggest_float("bb_k", 1.5, 3.0, step=0.25), 2)))
                enter_er = Decimal(
                    str(round(trial.suggest_float("enter_trend_er", 0.20, 0.45, step=0.05), 2))
                )
                # `RegimeParams` requires enter_trend_er > exit_trend_er. Sampling the two
                # independently threw away roughly a third of every study: those trials died
                # on the invariant instead of being scored, and a dead trial teaches the TPE
                # sampler nothing. Bounding exit by the already-drawn enter keeps every trial
                # a real observation.
                exit_er = Decimal(
                    str(
                        round(
                            trial.suggest_float(
                                "exit_trend_er",
                                0.10,
                                # Round the bound to the grid, otherwise binary float
                                # arithmetic hands Optuna `0.35000000000000003` and it
                                # warns that the range is not divisible by the step.
                                round(float(enter_er) - 0.05, 2),
                                step=0.05,
                            ),
                            2,
                        )
                    )
                )
                params = SelectedParams(
                    fast_ema=base.fast_ema,
                    slow_ema=base.slow_ema,
                    donchian_period=donchian,
                    bb_period=bb_period,
                    bb_k=bb_k,
                    enter_trend_er=enter_er,
                    exit_trend_er=exit_er,
                    z_entry=base.z_entry,
                    z_exit=base.z_exit,
                )

            candidate = apply_selected(request, params)
            report = run_is(candidate)
            score = in_sample_score(report)

            if best_report is None or score > in_sample_score(best_report):
                best_report = report
                best_params = params

            return float(score)

        study.optimize(objective, n_trials=self._n_trials)

        if best_report is None:
            raise ValueError("Optuna failed to find any valid parameters")

        return best_params, best_report, len(study.trials)
