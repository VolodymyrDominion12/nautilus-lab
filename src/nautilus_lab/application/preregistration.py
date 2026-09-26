"""Build the terms of a walk-forward test and check them against registrations (R-2).

`lab research --folds N --register "hypothesis"` computes the terms, fold windows
included, **without running a single backtest**, and writes them down. A later run with
the same settings computes its terms again from what it actually did; the gate promotes
only when the two hash to the same value and the registration predates the run.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Protocol

from nautilus_lab.application.dtos import WalkForwardRequest
from nautilus_lab.application.param_grid import iter_param_grid
from nautilus_lab.application.promotion_gate import GateCriteria
from nautilus_lab.application.trial_ledger import dataset_key
from nautilus_lab.domain.preregistration import (
    Preregistration,
    PreregistrationVerdict,
    ResearchTerms,
    check_preregistration,
)
from nautilus_lab.domain.walk_forward import WalkForwardWindow


class PreregistrationStore(Protocol):
    def load_all(self) -> list[Preregistration]: ...

    def save(self, registration: Preregistration) -> str:
        """Persist; return where it went (for the log line)."""
        ...


def research_terms(
    request: WalkForwardRequest,
    windows: Sequence[WalkForwardWindow],
    criteria: GateCriteria | None = None,
) -> ResearchTerms:
    """The terms of this walk-forward: what it tries, on what, against which bar."""
    backtest = request.backtest
    if request.use_optuna:
        # A seeded study replays the same trial sequence: seed + count name the search.
        grid: tuple[str, ...] = (f"optuna seed={backtest.seed} trials={request.optuna_trials}",)
    else:
        grid = tuple(params.label() for params in iter_param_grid(backtest))
    rules = criteria or GateCriteria()
    gate = tuple((item.name, str(getattr(rules, item.name))) for item in dataclasses.fields(rules))
    options = (
        ("bar_type", backtest.bar_type),
        ("fee_schedule", repr(backtest.fee_schedule)),
        ("risk", repr(backtest.risk)),
        ("risk_overlay", repr(backtest.risk_overlay)),
        ("starting_equity", str(backtest.starting_equity)),
        ("stress_slice", backtest.stress_slice or ""),
        ("use_bar_vpin", str(backtest.use_bar_vpin)),
        ("use_hawkes", str(backtest.use_hawkes)),
        ("use_tick_vpin", str(backtest.use_tick_vpin)),
    )
    return ResearchTerms(
        robot=backtest.robot.value,
        dataset=dataset_key(backtest),
        grid=grid,
        folds=request.folds,
        in_sample_fraction=str(request.in_sample_fraction),
        embargo_bars=request.embargo_bars or backtest.embargo_bars,
        selection_metric=backtest.selection_metric.value,
        oos_windows=tuple(
            (window.out_of_sample_start.isoformat(), window.out_of_sample_end.isoformat())
            for window in windows
        ),
        gate=gate,
        options=options,
    )


def register(
    terms: ResearchTerms,
    *,
    hypothesis: str,
    registered_at: datetime,
    store: PreregistrationStore,
) -> tuple[Preregistration, str]:
    """Write the terms down before anything is measured. Refuses an empty hypothesis."""
    if not hypothesis.strip():
        raise ValueError("a registration needs a hypothesis: what should the OOS show, and why")
    registration = Preregistration(
        terms=terms,
        hypothesis=hypothesis.strip(),
        registered_at=registered_at,
        terms_sha256=terms.sha256(),
    )
    return registration, store.save(registration)


def verdict_for(
    request: WalkForwardRequest,
    windows: Iterable[WalkForwardWindow],
    store: PreregistrationStore,
    *,
    run_started_at: datetime,
    criteria: GateCriteria | None = None,
) -> PreregistrationVerdict:
    terms = research_terms(request, tuple(windows), criteria)
    return check_preregistration(terms, store.load_all(), run_started_at=run_started_at)
