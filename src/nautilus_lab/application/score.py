from __future__ import annotations

from decimal import Decimal

from nautilus_lab.application.dtos import BacktestReport
from nautilus_lab.domain.metrics import SelectionMetric

# Extra live-cost buffer applied to turnover. Fees are already inside ending_balance;
# this haircut is the unused signal: two equal-P&L candidates, the heavier-trading
# one is more fragile when live costs exceed the fill model (docs/13 §6).
DEFAULT_TURNOVER_HAIRCUT = Decimal("0.0005")  # 5 bps of notional

#: Score for a run that cannot be ranked on a ratio metric (no balance, no Sharpe).
#: Finite on purpose: Optuna maximises floats, and -inf poisons its samplers.
UNRANKABLE = Decimal("-1e18")

#: Drawdown floor for the return/drawdown ratio, so a run that barely traded (dd ≈ 0)
#: cannot win the grid with an enormous ratio built on a tiny return.
MIN_DRAWDOWN = Decimal("0.005")


def in_sample_score(
    report: BacktestReport,
    *,
    metric: SelectionMetric = SelectionMetric.PNL,
    starting_equity: Decimal | None = None,
    turnover_haircut: Decimal = DEFAULT_TURNOVER_HAIRCUT,
) -> Decimal:
    """Higher is better. A run that cannot be measured ranks last so it cannot win.

    * `pnl` (default, the historical behaviour): ending balance minus
      `turnover_haircut * turnover`, so a candidate that only wins by churning loses to
      the quieter one. Fees are not subtracted again: they already reduced the balance.
    * `sharpe`: the per-bar Sharpe of the marked equity curve. Every candidate in one
      selection runs on the same bars, so annualising would not change the ranking.
    * `calmar`: return over max drawdown (drawdown floored at 0.5%). Prefers the
      candidate that earned its return without the deepest hole.

    Raw P&L picks whichever candidate took the most risk in-sample; the ratio metrics
    are the ones to use when that is not the question.
    """
    if turnover_haircut < 0:
        raise ValueError("turnover_haircut must be >= 0")
    if metric is SelectionMetric.PNL:
        if report.ending_balance is None:
            return Decimal("-1")
        score = report.ending_balance
        if report.metrics is not None:
            score -= turnover_haircut * report.metrics.turnover
        return score
    metrics = report.metrics
    if metrics is None or report.ending_balance is None:
        return UNRANKABLE
    if metric is SelectionMetric.SHARPE:
        return metrics.sharpe_like if metrics.sharpe_like is not None else UNRANKABLE
    if starting_equity is None or starting_equity <= 0:
        raise ValueError("calmar selection needs the starting equity")
    total_return = (report.ending_balance - starting_equity) / starting_equity
    return total_return / max(metrics.max_drawdown, MIN_DRAWDOWN)
