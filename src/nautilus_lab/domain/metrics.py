from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import sqrt


@dataclass(frozen=True, slots=True)
class BacktestMetrics:
    fees_paid: Decimal
    max_drawdown: Decimal
    turnover: Decimal
    sharpe_like: Decimal | None


def compute_metrics(
    *,
    starting_equity: Decimal,
    equity_curve: tuple[Decimal, ...],
    fees_paid: Decimal,
    turnover: Decimal,
) -> BacktestMetrics:
    max_dd = _max_drawdown(equity_curve, starting_equity)
    sharpe = _sharpe_like(equity_curve)
    return BacktestMetrics(
        fees_paid=fees_paid,
        max_drawdown=max_dd,
        turnover=turnover,
        sharpe_like=sharpe,
    )


def _max_drawdown(equity_curve: tuple[Decimal, ...], starting: Decimal) -> Decimal:
    if not equity_curve:
        return Decimal("0")
    peak = starting
    worst = Decimal("0")
    for equity in equity_curve:
        if equity > peak:
            peak = equity
        if peak > 0:
            dd = (peak - equity) / peak
            if dd > worst:
                worst = dd
    return worst


def _sharpe_like(equity_curve: tuple[Decimal, ...]) -> Decimal | None:
    if len(equity_curve) < 3:
        return None
    returns: list[Decimal] = []
    previous = equity_curve[0]
    for equity in equity_curve[1:]:
        if previous > 0:
            returns.append((equity - previous) / previous)
        previous = equity
    if len(returns) < 2:
        return None
    mean = sum(returns, Decimal("0")) / Decimal(len(returns))
    variance = sum((item - mean) ** 2 for item in returns) / Decimal(len(returns) - 1)
    if variance <= 0:
        return None
    std = Decimal(str(sqrt(float(variance))))
    if std == 0:
        return None
    return mean / std
