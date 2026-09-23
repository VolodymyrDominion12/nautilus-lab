from datetime import UTC, datetime, timedelta
from decimal import Decimal

from nautilus_lab.application.dtos import (
    BacktestReport,
    MultiWindowReport,
    OverfitAuditReport,
    SelectedParams,
    WalkForwardFold,
)
from nautilus_lab.application.promotion_gate import CheckStatus, evaluate_gate
from nautilus_lab.domain.deflated_sharpe import DeflatedSharpeResult
from nautilus_lab.domain.walk_forward import WalkForwardWindow

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _fold(index: int, oos_return: str, buy_hold: str, fills: int = 10) -> WalkForwardFold:
    start = T0 + timedelta(days=30 * index)
    window = WalkForwardWindow(
        in_sample_start=start,
        in_sample_end=start + timedelta(days=20),
        out_of_sample_start=start + timedelta(days=20),
        out_of_sample_end=start + timedelta(days=30),
    )
    report = BacktestReport(fills=fills, positions=1, ending_balance=Decimal("1"), notes="")
    return WalkForwardFold(
        index=index,
        selected=SelectedParams(
            fast_ema=10,
            slow_ema=20,
            donchian_period=20,
            bb_period=20,
            bb_k=Decimal("2"),
            enter_trend_er=Decimal("0.3"),
            exit_trend_er=Decimal("0.2"),
        ),
        candidates_tried=1,
        in_sample=report,
        out_of_sample=report,
        window=window,
        oos_return=Decimal(oos_return),
        buy_and_hold_return=Decimal(buy_hold),
    )


def _multi(returns: list[str], buy_hold: str = "0.01") -> MultiWindowReport:
    return MultiWindowReport(
        folds=tuple(_fold(i, value, buy_hold) for i, value in enumerate(returns)),
        starting_equity=Decimal("100000"),
        notes="",
    )


def _audit(pbo: str, dsr: str | None) -> OverfitAuditReport:
    return OverfitAuditReport(
        pbo=Decimal(pbo),
        split_count=70,
        configuration_count=4,
        blocks=8,
        block_returns=((Decimal("0.01"),) * 4,) * 8,
        labels=("a", "b", "c", "d"),
        notes="",
        deflated_sharpe=DeflatedSharpeResult(
            probability=None if dsr is None else Decimal(dsr),
            sharpe=None,
            threshold_sharpe=None,
            observations=8,
            trials=4,
            note="",
        ),
    )


def test_all_evidence_passing_promotes() -> None:
    verdict = evaluate_gate(_multi(["0.05"] * 6), _audit("0.1", "0.97"))
    assert verdict.promoted
    assert verdict.label == "PROMOTE"


def test_missing_audit_is_incomplete_never_a_pass() -> None:
    verdict = evaluate_gate(_multi(["0.05"] * 6), None)
    assert not verdict.promoted
    assert verdict.label == "INCOMPLETE"
    assert {check.name for check in verdict.checks if check.status is CheckStatus.NOT_MEASURED} == {
        "pbo",
        "dsr",
    }


def test_losing_to_buy_and_hold_rejects() -> None:
    verdict = evaluate_gate(_multi(["0.02"] * 6, buy_hold="0.10"), _audit("0.1", "0.97"))
    assert verdict.label == "REJECT"
    failed = [check.name for check in verdict.checks if check.status is CheckStatus.FAIL]
    assert failed == ["beats_buy_hold"]


def test_too_few_profitable_folds_and_folds_reject() -> None:
    verdict = evaluate_gate(_multi(["0.05", "-0.01", "0.03", "-0.02"]), _audit("0.1", "0.97"))
    failed = {check.name for check in verdict.checks if check.status is CheckStatus.FAIL}
    assert {"folds", "profitable_folds"} <= failed


def test_undefined_dsr_is_not_measured() -> None:
    verdict = evaluate_gate(_multi(["0.05"] * 6), _audit("0.1", None))
    dsr = next(check for check in verdict.checks if check.name == "dsr")
    assert dsr.status is CheckStatus.NOT_MEASURED
    assert verdict.label == "INCOMPLETE"
