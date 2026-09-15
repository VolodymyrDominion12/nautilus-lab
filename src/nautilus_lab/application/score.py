from __future__ import annotations

from decimal import Decimal

from nautilus_lab.application.dtos import BacktestReport

# Extra live-cost buffer applied to turnover. Fees are already inside ending_balance;
# this haircut is the unused signal: two equal-P&L candidates, the heavier-trading
# one is more fragile when live costs exceed the fill model (docs/13 §6).
DEFAULT_TURNOVER_HAIRCUT = Decimal("0.0005")  # 5 bps of notional


def in_sample_score(
    report: BacktestReport,
    *,
    turnover_haircut: Decimal = DEFAULT_TURNOVER_HAIRCUT,
) -> Decimal:
    """Higher is better. Missing balance ranks last so it cannot win the grid.

    When metrics are present, subtract `turnover_haircut * turnover` so a candidate
    that only wins by churning loses to the quieter one. Do not subtract `fees_paid`
    again: they already reduced the balance.
    """
    if turnover_haircut < 0:
        raise ValueError("turnover_haircut must be >= 0")
    if report.ending_balance is None:
        return Decimal("-1")
    score = report.ending_balance
    if report.metrics is not None:
        score -= turnover_haircut * report.metrics.turnover
    return score
