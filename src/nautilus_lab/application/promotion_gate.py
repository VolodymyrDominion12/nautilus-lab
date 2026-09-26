"""Pre-registered promotion gate: when may a robot leave research for a paper trial.

The thresholds are fixed here, before any run is looked at, on purpose. Choosing the
bar after seeing the numbers is the quiet way every backtest ends up "promising".
Each check reports PASS, FAIL or NOT MEASURED; a robot is promoted only when every
check was measured and passed — an unmeasured check is never read as a pass.

Evidence comes from two separate commands:

* `lab research --folds N` — the rolling walk-forward (`MultiWindowReport`);
* `lab research --pbo` — the overfitting audit (`OverfitAuditReport`: PBO and DSR).

A single command only ever sees half of it, so its verdict is at best INCOMPLETE.
"""

from __future__ import annotations

from collections.abc import Sized
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from nautilus_lab.application.dtos import OverfitAuditReport


class WalkForwardEvidence(Protocol):
    """What the gate reads from a rolling walk-forward, whichever robot produced it.

    `MultiWindowReport` (single-instrument robots) and `XsMomWalkForwardReport`
    (the basket rotation) both satisfy it.
    """

    @property
    def folds(self) -> Sized: ...

    @property
    def oos_returns(self) -> tuple[Decimal, ...]: ...

    @property
    def profitable_folds(self) -> int: ...

    @property
    def total_oos_fills(self) -> int: ...

    def beats_buy_and_hold(self) -> bool | None: ...


class CheckStatus(StrEnum):
    PASS = "pass"  # noqa: S105 — a check outcome, not a password
    FAIL = "fail"
    NOT_MEASURED = "not measured"


@dataclass(frozen=True, slots=True)
class GateCriteria:
    min_folds: int = 6
    #: Share of out-of-sample folds that must end in profit after fees (5 of 6).
    min_profitable_share: Decimal = Decimal("0.83")
    #: Out-of-sample fills across all folds; fewer is an anecdote, not a sample.
    min_oos_fills: int = 30
    max_pbo: Decimal = Decimal("0.3")
    min_dsr: Decimal = Decimal("0.95")


@dataclass(frozen=True, slots=True)
class GateCheck:
    name: str
    status: CheckStatus
    detail: str


@dataclass(frozen=True, slots=True)
class GateVerdict:
    checks: tuple[GateCheck, ...]

    @property
    def promoted(self) -> bool:
        return all(check.status is CheckStatus.PASS for check in self.checks)

    @property
    def label(self) -> str:
        if self.promoted:
            return "PROMOTE"
        if any(check.status is CheckStatus.FAIL for check in self.checks):
            return "REJECT"
        return "INCOMPLETE"

    def summary_line(self) -> str:
        parts = ", ".join(f"{check.name}={check.status.value}" for check in self.checks)
        return f"promotion_gate={self.label} ({parts})"


def evaluate_gate(
    multi: WalkForwardEvidence | None,
    audit: OverfitAuditReport | None,
    criteria: GateCriteria | None = None,
) -> GateVerdict:
    rules = criteria or GateCriteria()
    return GateVerdict(checks=(*_walk_forward_checks(multi, rules), *_audit_checks(audit, rules)))


def _check(name: str, passed: bool | None, detail: str) -> GateCheck:
    if passed is None:
        return GateCheck(name, CheckStatus.NOT_MEASURED, detail)
    return GateCheck(name, CheckStatus.PASS if passed else CheckStatus.FAIL, detail)


def _walk_forward_checks(
    multi: WalkForwardEvidence | None, rules: GateCriteria
) -> tuple[GateCheck, ...]:
    if multi is None:
        missing = "run `lab research --folds N`"
        return (
            _check("folds", None, missing),
            _check("profitable_folds", None, missing),
            _check("beats_buy_hold", None, missing),
            _check("beats_vol_matched", None, missing),
            _check("oos_fills", None, missing),
        )
    fold_count = len(multi.folds)
    measured = len(multi.oos_returns)
    share = Decimal(multi.profitable_folds) / Decimal(measured) if measured else None
    return (
        _check(
            "folds",
            fold_count >= rules.min_folds,
            f"{fold_count} folds (need >= {rules.min_folds})",
        ),
        _check(
            "profitable_folds",
            None if share is None else share >= rules.min_profitable_share,
            f"{multi.profitable_folds}/{measured} profitable "
            f"(need >= {rules.min_profitable_share * 100:.0f}%)",
        ),
        _check(
            "beats_buy_hold",
            multi.beats_buy_and_hold(),
            "mean out-of-sample return vs mean buy&hold over the same folds",
        ),
        *_vol_matched_check(multi),
        _check(
            "oos_fills",
            multi.total_oos_fills >= rules.min_oos_fills,
            f"{multi.total_oos_fills} fills (need >= {rules.min_oos_fills})",
        ),
    )


def _vol_matched_check(multi: WalkForwardEvidence) -> tuple[GateCheck, ...]:
    """Beat buy & hold scaled to the robot's own OOS volatility (docs/27 R-4, ADR 0007).

    Raw buy & hold asks whether trading was worth more than holding; this asks whether
    it was worth more than holding the same risk. A robot that beats raw buy & hold only
    by running twice the asset's volatility fails here. Evidence that cannot state a
    volatility-matched baseline (the basket rotation compares against its own
    equal-weight basket) gets no such check rather than a permanent NOT MEASURED.
    """
    measure = getattr(multi, "beats_vol_matched_buy_and_hold", None)
    if not callable(measure):
        return ()
    verdict = measure()
    return (
        _check(
            "beats_vol_matched",
            verdict if isinstance(verdict, bool) or verdict is None else None,
            "mean out-of-sample return vs mean volatility-matched buy&hold (same folds)",
        ),
    )


def _audit_checks(audit: OverfitAuditReport | None, rules: GateCriteria) -> tuple[GateCheck, ...]:
    if audit is None:
        missing = "run `lab research --pbo`"
        return (_check("pbo", None, missing), _check("dsr", None, missing))
    pbo_passed = audit.pbo <= rules.max_pbo if audit.is_meaningful else None
    dsr = audit.deflated_sharpe.probability
    trials = audit.deflated_sharpe.n_trials_total
    return (
        _check("pbo", pbo_passed, f"PBO={audit.pbo} (need <= {rules.max_pbo})"),
        _check(
            "dsr",
            None if dsr is None else dsr >= rules.min_dsr,
            f"DSR={dsr} over n_trials_total={trials} (need >= {rules.min_dsr})",
        ),
    )
