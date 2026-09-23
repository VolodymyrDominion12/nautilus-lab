"""Portfolio simulator for the cross-sectional momentum robot.

Why not the Nautilus engine: every other robot trades one instrument (or one pair) and
runs through `NautilusResearchBacktest`. A rotation across N coins needs a
multi-instrument strategy there; until that adapter exists, this simulator keeps the
research honest with the same rules the engine enforces:

* **No lookahead.** Weights are decided on bar *t*'s close and executed at bar *t+1*'s
  open. The decision only sees closes up to and including *t*.
* **Costs.** Every traded notional pays the taker fee from the fee schedule plus a
  slippage haircut on the fill price (buys fill higher, sells lower).
* **No leverage, no shorts, no negative cash.** Sells execute before buys, and buys are
  scaled down when fees and slippage would overdraw the cash.
* **Marked equity.** The curve is cash plus holdings at each close, so drawdowns include
  open losses (the same rule `domain/marking.py` enforces for the engine).
* **Warm-up.** Bars before `trade_start` feed the ranking but are never traded.

Fractional quantities are allowed: position sizes here are research numbers, not
exchange orders, and rounding to lot sizes would add noise to every comparison.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from nautilus_lab.application.dtos import BacktestReport
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.fees import FeeSchedule
from nautilus_lab.domain.metrics import BacktestMetrics, compute_metrics
from nautilus_lab.domain.xsmom import XsMomParams, target_weights

DEFAULT_SLIPPAGE = Decimal("0.0005")  # 5 bps against us on every fill


@dataclass(frozen=True, slots=True)
class XsMomRun:
    params: XsMomParams
    starting_equity: Decimal
    ending_equity: Decimal
    equity_curve: tuple[Decimal, ...]
    fees_paid: Decimal
    traded_notional: Decimal
    rebalances: int
    trades: int
    basket_return: Decimal | None
    metrics: BacktestMetrics
    first_ts: datetime | None
    last_ts: datetime | None

    @property
    def return_fraction(self) -> Decimal:
        return (self.ending_equity - self.starting_equity) / self.starting_equity

    def as_backtest_report(self) -> BacktestReport:
        """The shape `score.in_sample_score` and the audit tooling already rank."""
        return BacktestReport(
            fills=self.trades,
            positions=self.rebalances,
            ending_balance=self.ending_equity,
            notes=f"xsmom {self.params.label()}",
            metrics=self.metrics,
            realized_balance=None,
        )


def require_aligned(bars_by_symbol: Mapping[str, Sequence[OhlcvBar]]) -> tuple[str, ...]:
    """Symbols in a stable order, after checking every series shares one clock."""
    if not bars_by_symbol:
        raise ValueError("xsmom needs at least one symbol")
    symbols = tuple(sorted(bars_by_symbol))
    reference = [bar.ts_utc for bar in bars_by_symbol[symbols[0]]]
    for symbol in symbols[1:]:
        if [bar.ts_utc for bar in bars_by_symbol[symbol]] != reference:
            raise ValueError(
                f"bars for {symbol} are not aligned with {symbols[0]}; load them with an "
                "inner join on timestamps (ResearchBarFeed.load_multi does)"
            )
    return symbols


def run_xsmom(
    bars_by_symbol: Mapping[str, Sequence[OhlcvBar]],
    params: XsMomParams,
    *,
    starting_equity: Decimal,
    fees: FeeSchedule,
    slippage: Decimal = DEFAULT_SLIPPAGE,
    trade_start: datetime | None = None,
    periods_per_year: int | None = None,
) -> XsMomRun:
    if starting_equity <= 0:
        raise ValueError("starting_equity must be > 0")
    if slippage < 0:
        raise ValueError("slippage must be >= 0")
    symbols = require_aligned(bars_by_symbol)
    series = {symbol: list(bars_by_symbol[symbol]) for symbol in symbols}
    count = len(series[symbols[0]])
    closes: dict[str, list[Decimal]] = {s: [bar.close for bar in series[s]] for s in symbols}

    def tradable(index: int) -> bool:
        return trade_start is None or series[symbols[0]][index].ts_utc >= trade_start

    cash = starting_equity
    qty = dict.fromkeys(symbols, Decimal("0"))
    pending: dict[str, Decimal] | None = None
    curve: list[Decimal] = []
    fees_paid = Decimal("0")
    traded = Decimal("0")
    rebalances = 0
    trades = 0
    eligible_seen = 0
    first_index: int | None = None

    for index in range(count):
        if pending is not None and tradable(index):
            opens = {s: series[s][index].open for s in symbols}
            cash, fill_fees, fill_notional, legs = _rebalance(
                cash, qty, pending, opens, fee=fees.taker, slippage=slippage
            )
            fees_paid += fill_fees
            traded += fill_notional
            trades += legs
            rebalances += 1
        pending = None

        if tradable(index):
            if first_index is None:
                first_index = index
            curve.append(cash + sum((qty[s] * closes[s][index] for s in symbols), Decimal("0")))

        # Decide on this close for the next open — only if that open will be traded
        # and the ranking has enough history.
        has_next = index + 1 < count and tradable(index + 1)
        if has_next and index + 1 >= params.warmup_bars:
            if eligible_seen % params.rebalance_every == 0:
                window = {s: closes[s][: index + 1] for s in symbols}
                pending = target_weights(window, params)
            eligible_seen += 1

    ending = curve[-1] if curve else starting_equity
    basket = _basket_return(series, symbols, first_index)
    metrics = compute_metrics(
        starting_equity=starting_equity,
        equity_curve=tuple(curve),
        fees_paid=fees_paid,
        turnover=traded / 2,
        traded_notional=traded,
        ending_equity=ending,
        periods_per_year=periods_per_year,
    )
    reference = series[symbols[0]]
    return XsMomRun(
        params=params,
        starting_equity=starting_equity,
        ending_equity=ending,
        equity_curve=tuple(curve),
        fees_paid=fees_paid,
        traded_notional=traded,
        rebalances=rebalances,
        trades=trades,
        basket_return=basket,
        metrics=metrics,
        first_ts=None if first_index is None else reference[first_index].ts_utc,
        last_ts=reference[-1].ts_utc if reference else None,
    )


def _rebalance(
    cash: Decimal,
    qty: dict[str, Decimal],
    weights: Mapping[str, Decimal],
    opens: Mapping[str, Decimal],
    *,
    fee: Decimal,
    slippage: Decimal,
) -> tuple[Decimal, Decimal, Decimal, int]:
    """Move holdings to `weights` at `opens`. Returns (cash, fees, notional, legs)."""
    equity = cash + sum((qty[s] * opens[s] for s in qty), Decimal("0"))
    deltas: dict[str, Decimal] = {}
    for symbol, held in qty.items():
        price = opens[symbol]
        if price <= 0:
            continue
        target_qty = equity * weights.get(symbol, Decimal("0")) / price
        delta = target_qty - held
        if delta != 0:
            deltas[symbol] = delta

    fees_paid = Decimal("0")
    notional = Decimal("0")
    legs = 0
    # Sells first: they fund the buys.
    for symbol, delta in deltas.items():
        if delta >= 0:
            continue
        fill = opens[symbol] * (1 - slippage)
        proceeds = -delta * fill
        charge = proceeds * fee
        cash += proceeds - charge
        fees_paid += charge
        notional += -delta * opens[symbol]
        qty[symbol] += delta
        legs += 1

    buys = {symbol: delta for symbol, delta in deltas.items() if delta > 0}
    cost = sum(
        (delta * opens[s] * (1 + slippage) * (1 + fee) for s, delta in buys.items()),
        Decimal("0"),
    )
    scale = Decimal("1") if cost <= cash or cost == 0 else cash / cost
    for symbol, delta in buys.items():
        bought = delta * scale
        fill = opens[symbol] * (1 + slippage)
        spend = bought * fill
        charge = spend * fee
        cash -= spend + charge
        fees_paid += charge
        notional += bought * opens[symbol]
        qty[symbol] += bought
        legs += 1
    return cash, fees_paid, notional, legs


def _basket_return(
    series: Mapping[str, Sequence[OhlcvBar]],
    symbols: Sequence[str],
    first_index: int | None,
) -> Decimal | None:
    """Equal-weight buy&hold of the whole basket over the traded window, no costs."""
    if first_index is None:
        return None
    returns: list[Decimal] = []
    for symbol in symbols:
        bars = series[symbol]
        start = bars[first_index].open
        if start > 0:
            returns.append(bars[-1].close / start - 1)
    if not returns:
        return None
    return sum(returns, Decimal("0")) / Decimal(len(returns))
