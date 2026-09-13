from __future__ import annotations

from decimal import Decimal

from nautilus_lab.application.dtos import BacktestReport


def in_sample_score(report: BacktestReport) -> Decimal:
    """Higher is better. Missing balance ranks last so it cannot win the grid."""
    if report.ending_balance is None:
        return Decimal("-1")
    return report.ending_balance
