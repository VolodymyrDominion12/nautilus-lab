from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from math import sqrt

from nautilus_lab.domain.bars import OhlcvBar


@dataclass(frozen=True, slots=True)
class BacktestMetrics:
    fees_paid: Decimal
    max_drawdown: Decimal
    turnover: Decimal
    sharpe_like: Decimal | None
    # Two-sided traded notional (entries AND exits, from the engine's fills report).
    # `turnover` above counts entry notional only, so it cannot be used as the base
    # of a per-unit cost: doing that would inflate breakeven roughly twofold.
    traded_notional: Decimal = Decimal("0")
    breakeven_cost: Decimal | None = None

    @property
    def paid_cost_rate(self) -> Decimal | None:
        """Cost actually paid per unit of traded notional — the number to compare c* with.

        Same units as maker/taker (fraction of notional), so "we paid 5.0 bps and
        breakeven is 7.3 bps" is a direct reading. None when nothing was traded.
        """
        if self.traded_notional <= 0:
            return None
        return self.fees_paid / self.traded_notional


def buy_and_hold_return(bars: Sequence[OhlcvBar]) -> Decimal | None:
    """Close-to-close return of simply holding the instrument across the window.

    Every walk-forward fold needs this baseline: a long-only robot that returns 4%
    while the instrument returned 12% has not added value, it has just taken
    directional risk. Returns None when the window is too short to measure.
    """
    if len(bars) < 2:
        return None
    first = bars[0].close
    if first == 0:
        return None
    return (bars[-1].close - first) / first


def compute_metrics(
    *,
    starting_equity: Decimal,
    equity_curve: tuple[Decimal, ...],
    fees_paid: Decimal,
    turnover: Decimal,
    traded_notional: Decimal = Decimal("0"),
    ending_equity: Decimal | None = None,
) -> BacktestMetrics:
    max_dd = _max_drawdown(equity_curve, starting_equity)
    sharpe = _sharpe_like(equity_curve)
    net_pnl = _net_pnl(starting_equity, equity_curve, ending_equity)
    return BacktestMetrics(
        fees_paid=fees_paid,
        max_drawdown=max_dd,
        turnover=turnover,
        sharpe_like=sharpe,
        traded_notional=traded_notional,
        breakeven_cost=breakeven_cost(
            net_pnl=net_pnl,
            fees_paid=fees_paid,
            traded_notional=traded_notional,
        ),
    )


def breakeven_cost(
    *,
    net_pnl: Decimal | None,
    fees_paid: Decimal,
    traded_notional: Decimal,
) -> Decimal | None:
    """Largest constant cost per unit of traded notional that leaves PnL at zero.

    `net_pnl` is measured after fees, so the gross result is `net_pnl + fees_paid`,
    and the answer is `gross / traded_notional` — a cost rate in the same units as
    maker/taker (fraction of notional). A strategy that loses money even before
    costs gets a negative number, which is the honest reading: free execution would
    not have saved it.

    None (not zero) when there is nothing to divide by: no fills means no
    measurement, and "0" would claim the strategy breaks even at zero cost.
    """
    if net_pnl is None or traded_notional <= 0:
        return None
    return (net_pnl + fees_paid) / traded_notional


def _net_pnl(
    starting_equity: Decimal,
    equity_curve: tuple[Decimal, ...],
    ending_equity: Decimal | None,
) -> Decimal | None:
    """P&L after fees. Prefers the engine's ending balance over the strategy's curve."""
    if ending_equity is not None:
        return ending_equity - starting_equity
    if not equity_curve:
        return None
    return equity_curve[-1] - starting_equity


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
