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
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from nautilus_lab.application.dtos import OverfitAuditReport
from nautilus_lab.domain.preregistration import PreregistrationVerdict


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
    def oos_daily_returns(self) -> tuple[Decimal, ...]: ...

    @property
    def profitable_folds(self) -> int: ...

    @property
    def total_oos_fills(self) -> int: ...

    def beats_buy_and_hold(self) -> bool | None: ...

    @property
    def mean_gross_return(self) -> Decimal | None: ...

    @property
    def mean_breakeven_bps(self) -> Decimal | None: ...

    @property
    def mean_turnover_per_bar(self) -> Decimal | None: ...

    @property
    def mean_exposure_pct(self) -> Decimal | None: ...

class StrategyClass(StrEnum):
    TREND_FOLLOWING = "trend_following"
    MEAN_REVERSION = "mean_reversion"
    CARRY = "carry"

def class_for_robot(robot: str) -> StrategyClass | None:
    if robot in ("ema", "regime", "adaptive_ema"):
        return StrategyClass.TREND_FOLLOWING
    if robot in ("vpin_momentum", "pairs", "meta_label", "ml_obi", "glft", "tri_scan", "xsmom"):
        return StrategyClass.MEAN_REVERSION
    if robot == "funding":
        return StrategyClass.CARRY
    return None


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
    # Gate v2 additions (Alpha level)
    min_gross_return: Decimal = Decimal("0")
    min_breakeven_bps: Decimal = Decimal("5.0")
    
    def apply_class_thresholds(self, strategy_class: StrategyClass | None) -> GateCriteria:
        """Return a copy of the criteria adjusted for the strategy class."""
        if strategy_class is StrategyClass.CARRY:
            return replace(self, min_profitable_share=Decimal("0.95"))
        if strategy_class is StrategyClass.TREND_FOLLOWING:
            return replace(self, min_profitable_share=Decimal("0.5"))
        return self


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
    *,
    preregistration: PreregistrationVerdict | None = None,
    strategy_class: StrategyClass | None = None,
) -> GateVerdict:
    from dataclasses import replace
    rules = criteria or GateCriteria()
    if strategy_class:
        rules = rules.apply_class_thresholds(strategy_class)

    return GateVerdict(
        checks=(
            _preregistration_check(preregistration),
            *_alpha_level_checks(multi, rules),
            *_walk_forward_checks(multi, rules, strategy_class),
            *_audit_checks(audit, rules, strategy_class, multi),
        )
    )

def _alpha_level_checks(
    multi: WalkForwardEvidence | None, rules: GateCriteria
) -> tuple[GateCheck, ...]:
    if multi is None:
        missing = "run `lab research --folds N`"
        return (_check("alpha_gross", None, missing), _check("alpha_breakeven", None, missing))
    
    gross = multi.mean_gross_return
    breakeven = multi.mean_breakeven_bps
    
    return (
        _check(
            "alpha_gross", 
            None if gross is None else gross > rules.min_gross_return, 
            f"Gross={gross} (need > {rules.min_gross_return})"
        ),
        _check(
            "alpha_breakeven", 
            None if breakeven is None else breakeven > rules.min_breakeven_bps, 
            f"Breakeven={breakeven}bps (need > {rules.min_breakeven_bps}bps)"
        ),
    )


def _preregistration_check(verdict: PreregistrationVerdict | None) -> GateCheck:
    """PROMOTE needs a registration whose terms match this run (docs/27 R-2).

    Without one the check is NOT MEASURED, so the verdict is INCOMPLETE at best: numbers
    from a test whose terms were not written down first cannot be told apart from the
    best of many silent retries.
    """
    if verdict is None:
        return _check(
            "preregistered",
            None,
            "no registration checked; `lab research --folds N --register ...` before the run",
        )
    return _check("preregistered", verdict.passed, verdict.summary_line())


def _check(name: str, passed: bool | None, detail: str) -> GateCheck:
    if passed is None:
        return GateCheck(name, CheckStatus.NOT_MEASURED, detail)
    return GateCheck(name, CheckStatus.PASS if passed else CheckStatus.FAIL, detail)


def _walk_forward_checks(
    multi: WalkForwardEvidence | None, rules: GateCriteria, strategy_class: StrategyClass | None = None
) -> tuple[GateCheck, ...]:
    if multi is None:
        missing = "run `lab research --folds N`"
        checks = [
            _check("folds", None, missing),
            _check("profitable_folds", None, missing),
            _check("beats_buy_hold", None, missing),
        ]
        if strategy_class is StrategyClass.TREND_FOLLOWING:
            checks.append(_check("beats_vol_matched", None, missing))
        checks.append(_check("oos_fills", None, missing))
        return tuple(checks)
    fold_count = len(multi.folds)
    measured = len(multi.oos_returns)
    share = Decimal(multi.profitable_folds) / Decimal(measured) if measured else None
    checks = [
        _check(
            "folds",
            measured >= rules.min_folds,
            f"{measured}/{fold_count} folds measured (need >= {rules.min_folds})",
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
        )
    ]
    
    if strategy_class is StrategyClass.TREND_FOLLOWING:
        checks.extend(_vol_matched_check(multi))
        
    checks.append(
        _check(
            "oos_fills",
            multi.total_oos_fills >= rules.min_oos_fills,
            f"{multi.total_oos_fills} fills (need >= {rules.min_oos_fills})",
        )
    )
    return tuple(checks)


def _vol_matched_check(multi: WalkForwardEvidence) -> tuple[GateCheck, ...]:
    """Beat buy & hold scaled to the robot's own OOS volatility (docs/27 R-4, ADR 0007).

    Raw buy & hold asks whether trading was worth more than holding; this asks whether
    it was worth more than holding the same risk. A robot that beats raw buy & hold only
    by running twice the asset's volatility fails here. Evidence that cannot state a
    volatility-matched baseline (today: the basket rotation) reports NOT MEASURED, so
    its verdict stays INCOMPLETE until it can (audit B4) — a check that silently
    disappears can never hold a verdict back.
    """
    measure = getattr(multi, "beats_vol_matched_buy_and_hold", None)
    if not callable(measure):
        return (
            _check(
                "beats_vol_matched",
                None,
                "this evidence has no volatility-matched buy&hold baseline yet",
            ),
        )
    verdict = measure()
    return (
        _check(
            "beats_vol_matched",
            verdict if isinstance(verdict, bool) or verdict is None else None,
            "mean out-of-sample return vs mean volatility-matched buy&hold (same folds)",
        ),
    )


def _audit_checks(
    audit: OverfitAuditReport | None, rules: GateCriteria, strategy_class: StrategyClass | None = None, multi: WalkForwardEvidence | None = None
) -> tuple[GateCheck, ...]:
    if audit is None:
        missing = "run `lab research --pbo`"
        return (_check("pbo", None, missing), _check("dsr", None, missing))
    pbo_passed = audit.pbo <= rules.max_pbo if audit.is_meaningful else None
    
    if multi is not None and getattr(multi, "oos_daily_returns", None) is not None and getattr(audit, "daily_trial_sharpes", None):
        from nautilus_lab.domain.deflated_sharpe import deflated_sharpe_ratio
        dsr_result = deflated_sharpe_ratio(
            multi.oos_daily_returns,
            list(audit.daily_trial_sharpes),
            total_trials=audit.deflated_sharpe.n_trials_total
        )
        dsr = dsr_result.probability
        trials = dsr_result.n_trials_total
        dsr_str = f"DSR={dsr} (OOS daily returns)"
    else:
        dsr = None
        trials = audit.deflated_sharpe.n_trials_total
        missing = "run `lab research --folds N` for OOS daily returns"
        dsr_str = missing

    return (
        _check("pbo", pbo_passed, f"PBO={audit.pbo} (need <= {rules.max_pbo})"),
        _check(
            "dsr",
            None if dsr is None else dsr >= rules.min_dsr,
            f"{dsr_str} over n_trials_total={trials} (need >= {rules.min_dsr})",
        ),
    )
