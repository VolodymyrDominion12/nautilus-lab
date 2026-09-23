"""Mark-to-market for open positions on linear instruments.

On a Nautilus MARGIN account `balance_total` moves only on realized PnL and fees: an
open position that is 30% under water leaves it untouched. Every number built on that
balance — the equity curve, max drawdown, Sharpe, VaR/CVaR, the daily-loss and
drawdown breakers, the out-of-sample return — then ignores open losses. Equity is
balance plus what the open positions are worth at the current mark; this module is
the one place that sum is defined.

Only linear, multiplier-1 instruments are handled (the spot pairs and USDT perpetuals
in `infrastructure/nautilus/instrument.py`). An inverse contract needs its own formula
and must not reuse this one silently.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class OpenLot:
    """One open (netted) position: positive `signed_qty` is long, negative is short."""

    instrument_id: str
    signed_qty: Decimal
    avg_price: Decimal


def lot_unrealized_pnl(lot: OpenLot, mark: Decimal) -> Decimal:
    return (mark - lot.avg_price) * lot.signed_qty


def unrealized_pnl(lots: Iterable[OpenLot], marks: Mapping[str, Decimal]) -> Decimal:
    """Sum of open PnL. A lot whose instrument has no mark is valued at its entry price.

    That is the conservative reading for a lot we cannot price (it neither flatters nor
    punishes the curve), and it is visible: the caller passes the marks it has.
    """
    total = Decimal("0")
    for lot in lots:
        mark = marks.get(lot.instrument_id)
        if mark is None or lot.signed_qty == 0:
            continue
        total += lot_unrealized_pnl(lot, mark)
    return total


def marked_equity(
    balance: Decimal,
    lots: Iterable[OpenLot],
    marks: Mapping[str, Decimal],
) -> Decimal:
    return balance + unrealized_pnl(lots, marks)
