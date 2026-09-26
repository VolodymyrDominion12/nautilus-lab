"""How many configurations were ever tried on a dataset (docs/27 R-3).

The Deflated Sharpe Ratio punishes a winner by the number of trials behind it. If only
the current run's grid counts, the search can be "laundered": run 8 configurations, look,
change the grid, run 8 more. Each run is then judged as if it were the first. The ledger
remembers every configuration a search has run on a dataset, and DSR is deflated by that
total.

What counts as one trial: one robot with one parameter set (`trial_id`). Running the same
configuration again adds nothing, because it is the same attempt. A new grid point, a new
robot or an Optuna trial adds one.

What counts as one dataset: the bar series (`dataset_key`). An instrument and bar interval
are one dataset whatever window a run loads, because stress slices and walk-forward folds
are views of the same history, and a trial on a subset has still looked at it. This
over-counts rather than under-counts, which is the right direction for a deflation.

Synthetic runs are never recorded: they are tests of the plumbing, not searches over
market data.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from nautilus_lab.application.dtos import BacktestRequest
from nautilus_lab.domain.bars import BarOrigin


class TrialLedger(Protocol):
    def record(self, dataset: str, trial_ids: Iterable[str]) -> int:
        """Remember these trials; return how many distinct ones the dataset now has."""
        ...


def dataset_key(request: BacktestRequest) -> str:
    """The bar series a search looks at: every leg of a pair, in a stable order."""
    if request.bar_types:
        return ",".join(sorted(request.bar_types))
    return request.bar_type


def trial_id(request: BacktestRequest, label: str) -> str:
    return f"{request.robot.value}|{label}"


def is_recorded(request: BacktestRequest) -> bool:
    return request.source is BarOrigin.CATALOG


def record_trials(
    ledger: TrialLedger | None, request: BacktestRequest, labels: Iterable[str]
) -> int | None:
    """Record a search's configurations; None when nothing is kept for this run."""
    if ledger is None or not is_recorded(request):
        return None
    return ledger.record(dataset_key(request), (trial_id(request, label) for label in labels))


class InMemoryTrialLedger:
    """A ledger that lives as long as the process: tests, notebooks, one-off scripts."""

    def __init__(self) -> None:
        self.trials: dict[str, set[str]] = {}

    def record(self, dataset: str, trial_ids: Iterable[str]) -> int:
        seen = self.trials.setdefault(dataset, set())
        seen.update(trial_ids)
        return len(seen)
