from decimal import Decimal

from nautilus_lab.application.dtos import OverfitAuditReport
from nautilus_lab.domain.deflated_sharpe import DeflatedSharpeResult

_DSR = DeflatedSharpeResult(
    probability=None,
    sharpe=None,
    threshold_sharpe=None,
    observations=0,
    trials=0,
    note="n/a",
)


def _report(
    rows: tuple[tuple[Decimal | None, ...], ...], *, splits: int, pbo: str = "0.04"
) -> OverfitAuditReport:
    return OverfitAuditReport(
        pbo=Decimal(pbo),
        split_count=splits,
        configuration_count=len(rows[0]),
        blocks=len(rows),
        block_returns=rows,
        labels=tuple(f"c{i}" for i in range(len(rows[0]))),
        notes="",
        deflated_sharpe=_DSR,
    )


def test_undefined_pbo_names_the_condition_that_failed() -> None:
    """3 configurations x 8 blocks used to print 'need >= 2 configurations'."""
    rows = tuple((Decimal("0"), Decimal("0"), Decimal("0")) for _ in range(8))
    line = _report(rows, splits=0).summary_line()
    assert "0 usable splits (need >= 2)" in line
    assert "configurations (need" not in line


def test_low_pbo_over_losing_configurations_is_not_a_pass() -> None:
    rows = tuple((Decimal("-0.05"), Decimal("-0.01")) for _ in range(8))
    line = _report(rows, splits=70).summary_line()
    assert "selection generalises" in line
    assert "no configuration is profitable" in line


def test_profitable_winner_keeps_the_plain_verdict() -> None:
    rows = tuple((Decimal("0.02"), Decimal("-0.01")) for _ in range(8))
    line = _report(rows, splits=70).summary_line()
    assert line.endswith("(selection generalises)")
