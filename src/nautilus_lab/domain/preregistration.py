"""Pre-registration of an out-of-sample test (docs/27 R-2, docs/21 §10).

The terms of a test are fixed before any result is seen: which robot, on which data, over
which parameter grid, on which exact out-of-sample windows, and against which gate
thresholds. Their hash is written down first. A run whose own terms hash to something
else (a grid widened after a bad fold, one more fold because the last one lost, a gate
eased) is a different experiment and cannot be promoted on the registration's authority.

This module holds only values and the comparison. Reading and writing registrations is
`infrastructure/preregistration_store.py`; building terms from a request is
`application/preregistration.py`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class ResearchTerms:
    """Everything that decides what an out-of-sample test measures, and nothing else.

    The hypothesis text is not a term: rewording it changes no number. Windows are ISO
    UTC timestamps of each fold's out-of-sample block, so the same catalog gives the same
    terms, and one ingested bar more gives different ones: new data is a new test.
    """

    robot: str
    dataset: str
    grid: tuple[str, ...]
    folds: int
    in_sample_fraction: str
    embargo_bars: int
    selection_metric: str
    oos_windows: tuple[tuple[str, str], ...]
    gate: tuple[tuple[str, str], ...]
    #: Everything else that changes the numbers: filters, fees, equity, risk limits.
    options: tuple[tuple[str, str], ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "robot": self.robot,
            "dataset": self.dataset,
            "grid": list(self.grid),
            "folds": self.folds,
            "in_sample_fraction": self.in_sample_fraction,
            "embargo_bars": self.embargo_bars,
            "selection_metric": self.selection_metric,
            "oos_windows": [list(window) for window in self.oos_windows],
            "gate": [list(item) for item in self.gate],
            "options": [list(item) for item in self.options],
        }

    def sha256(self) -> str:
        canonical = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> ResearchTerms:
        def strings(key: str) -> tuple[str, ...]:
            value = payload.get(key)
            if not isinstance(value, list):
                raise ValueError(f"{key} must be a list")
            return tuple(str(item) for item in value)

        def pairs(key: str) -> tuple[tuple[str, str], ...]:
            value = payload.get(key)
            if not isinstance(value, list) or not all(
                isinstance(item, list) and len(item) == 2 for item in value
            ):
                raise ValueError(f"{key} must be a list of pairs")
            return tuple((str(item[0]), str(item[1])) for item in value)

        folds, embargo = payload.get("folds"), payload.get("embargo_bars")
        if not isinstance(folds, int) or not isinstance(embargo, int):
            raise ValueError("folds and embargo_bars must be integers")
        return cls(
            robot=str(payload.get("robot", "")),
            dataset=str(payload.get("dataset", "")),
            grid=strings("grid"),
            folds=folds,
            in_sample_fraction=str(payload.get("in_sample_fraction", "")),
            embargo_bars=embargo,
            selection_metric=str(payload.get("selection_metric", "")),
            oos_windows=pairs("oos_windows"),
            gate=pairs("gate"),
            options=pairs("options") if "options" in payload else (),
        )


@dataclass(frozen=True, slots=True)
class Preregistration:
    terms: ResearchTerms
    hypothesis: str
    registered_at: datetime
    #: The hash written at registration time. A file edited afterwards no longer matches
    #: its own terms, and is treated as tampered, never as a registration.
    terms_sha256: str
    source: str = ""

    @property
    def intact(self) -> bool:
        return self.terms.sha256() == self.terms_sha256


class PreregistrationStatus(StrEnum):
    MATCHED = "matched"
    MISMATCH = "mismatch"
    NOT_REGISTERED = "not registered"
    LATE = "registered after the run"


@dataclass(frozen=True, slots=True)
class PreregistrationVerdict:
    status: PreregistrationStatus
    run_sha256: str
    detail: str
    registration: Preregistration | None = None

    @property
    def passed(self) -> bool | None:
        """For the gate: True matched, False a registration exists but differs, None none."""
        if self.status is PreregistrationStatus.MATCHED:
            return True
        if self.status is PreregistrationStatus.NOT_REGISTERED:
            return None
        return False

    def summary_line(self) -> str:
        return f"preregistration={self.status.value} run={self.run_sha256[:12]} ({self.detail})"


def check_preregistration(
    run: ResearchTerms,
    registrations: Iterable[Preregistration],
    *,
    run_started_at: datetime,
) -> PreregistrationVerdict:
    """Compare a run's terms with every registration for the same robot and dataset."""
    run_hash = run.sha256()
    candidates = [
        item
        for item in registrations
        if item.terms.robot == run.robot and item.terms.dataset == run.dataset
    ]
    intact = [item for item in candidates if item.intact]
    for item in intact:
        if item.terms_sha256 == run_hash:
            if item.registered_at >= run_started_at:
                return PreregistrationVerdict(
                    PreregistrationStatus.LATE,
                    run_hash,
                    f"{item.source or 'registration'} is dated after the run started",
                    item,
                )
            return PreregistrationVerdict(
                PreregistrationStatus.MATCHED,
                run_hash,
                f"{item.source or 'registration'} from {item.registered_at.isoformat()}",
                item,
            )
    if intact:
        latest = max(intact, key=lambda item: item.registered_at)
        return PreregistrationVerdict(
            PreregistrationStatus.MISMATCH,
            run_hash,
            "terms differ from "
            f"{latest.source or 'the registration'}: {', '.join(differences(latest.terms, run))}",
            latest,
        )
    if candidates:
        return PreregistrationVerdict(
            PreregistrationStatus.MISMATCH,
            run_hash,
            "the only registrations for this robot and dataset were edited after registering",
            candidates[0],
        )
    return PreregistrationVerdict(
        PreregistrationStatus.NOT_REGISTERED,
        run_hash,
        f"no registration for {run.robot} on {run.dataset}; run `lab register` first",
    )


def differences(registered: ResearchTerms, run: ResearchTerms) -> Sequence[str]:
    """Names of the terms that differ, so a mismatch says what moved."""
    left, right = registered.as_dict(), run.as_dict()
    return [key for key in left if left[key] != right.get(key)] or ["(none)"]
