"""Replay the trades of many single-instrument cells on one shared account (plan P1.5/1.6).

A batch runs every coin on its own 100k account. That answers "does the robot work on
SOL", not "what happens to one account that trades all twelve": in the 2026-02..04 fold
every coin lost at once, so twelve separate 0.5% stops are one 6% loss on a shared book.
This module puts the cells' trades (`trades.jsonl`, written with each cell's summary) on a
single timeline and re-sizes them under portfolio rules:

* **risk per trade** — each trade risks `risk_per_trade` of the *portfolio* equity at its
  entry, and keeps the R multiple it earned in its own cell (net of fees and, for perps,
  of funding);
* **heat cap** — a new entry is skipped while the open trades already risk `max_heat`;
* **side cap** — at most `max_per_side` instruments long and as many short (trades of one
  `group` — the same coin traded by several sub-systems of an ensemble — count once);
* **volatility target** — optional: the risk per trade is scaled by
  `target_vol / realised vol` of the replayed account's own past daily returns (look-back
  `vol_lookback_days`, factor clipped to `[min_scale, max_scale]`), so the account runs
  at a chosen risk instead of whatever the coins happened to do.

Honesty rules:

* this is a **replay**, not a backtest: entries and exits are the cells' own, so a trade
  the cap skipped can't change what the robot did next, and intrabar paths between
  entry and exit are not seen — drawdown is measured on realised equity at exits only,
  which understates the true intraperiod drawdown;
* a trade's R is taken over its cell's cash at risk (`|entry - stop| x qty`); a trade
  without a stop has no R and is skipped (counted);
* the vol scale uses only returns realised **before** the entry.

Floats are fine here: this is reporting over finished runs, not a trading decision.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class ReplayTrade:
    """One trade of one cell, reduced to what the replay needs."""

    cell: str
    side: str  # "LONG" / "SHORT"
    ts_in: datetime
    ts_out: datetime
    r_net: float  # net PnL (after fees and funding) over the cell's cash at risk
    fold: int | None = None
    #: What the side cap counts: the instrument. Defaults to the cell, so a plain batch
    #: counts each coin once; an ensemble (donchian 20/40/90 on one coin) shares a group.
    group: str | None = None

    @property
    def group_key(self) -> str:
        return self.group or self.cell


@dataclass(frozen=True, slots=True)
class ReplayRules:
    starting_equity: float = 100_000.0
    risk_per_trade: float = 0.005
    #: Total risk of open trades, as a share of equity; None = no cap.
    max_heat: float | None = 0.03
    #: Open positions per side; None = no cap.
    max_per_side: int | None = 4
    #: Annualised volatility target of the account; None = fixed risk per trade.
    target_vol: float | None = None
    vol_lookback_days: int = 60
    min_scale: float = 0.25
    max_scale: float = 2.0

    def __post_init__(self) -> None:
        if self.starting_equity <= 0:
            raise ValueError("starting_equity must be > 0")
        if not 0 < self.risk_per_trade < 0.1:
            raise ValueError("risk_per_trade must be in (0, 0.1)")
        if self.max_heat is not None and self.max_heat < self.risk_per_trade:
            raise ValueError("max_heat must allow at least one trade")
        if self.max_per_side is not None and self.max_per_side < 1:
            raise ValueError("max_per_side must be >= 1")
        if self.target_vol is not None and self.target_vol <= 0:
            raise ValueError("target_vol must be > 0")
        if not 0 < self.min_scale <= self.max_scale:
            raise ValueError("need 0 < min_scale <= max_scale")


@dataclass(slots=True)
class ReplayResult:
    rules: ReplayRules
    taken: int = 0
    skipped_heat: int = 0
    skipped_side: int = 0
    skipped_no_risk: int = 0
    ending_equity: float = 0.0
    max_drawdown: float = 0.0
    #: Realised PnL per calendar day (exit date), account currency.
    daily_pnl: dict[date, float] = field(default_factory=dict)
    pnl_by_cell: dict[str, float] = field(default_factory=dict)
    pnl_by_fold: dict[int, float] = field(default_factory=dict)
    peak_heat: float = 0.0

    @property
    def total_return(self) -> float:
        return self.ending_equity / self.rules.starting_equity - 1.0

    def annualised_vol(self) -> float | None:
        returns = _daily_returns(self.daily_pnl, self.rules.starting_equity)
        if len(returns) < 2:
            return None
        return _stdev(returns) * math.sqrt(365.0)

    def sharpe(self) -> float | None:
        returns = _daily_returns(self.daily_pnl, self.rules.starting_equity)
        if len(returns) < 2:
            return None
        sd = _stdev(returns)
        return None if sd == 0 else sum(returns) / len(returns) / sd * math.sqrt(365.0)


def trade_from_row(
    cell: str, row: Mapping[str, Any], *, group: str | None = None
) -> ReplayTrade | None:
    """A `trades.jsonl` row -> `ReplayTrade`; None when it has no stop or no prices."""
    try:
        px_in = float(row["px_in"])
        qty = float(row["qty"])
        net = float(row["net"])
        stop = row.get("stop")
        if stop is None:
            return None
        risk = abs(px_in - float(stop)) * qty
        if risk <= 0:
            return None
        funding = float(row.get("funding") or 0.0)
        fold = row.get("fold")
        return ReplayTrade(
            cell=cell,
            side=str(row.get("side") or "LONG"),
            ts_in=datetime.fromisoformat(str(row["ts_in"])),
            ts_out=datetime.fromisoformat(str(row["ts_out"])),
            r_net=(net - funding) / risk,
            fold=int(fold) if isinstance(fold, int) else None,
            group=group,
        )
    except (KeyError, TypeError, ValueError):
        return None


def replay(trades: Iterable[ReplayTrade], rules: ReplayRules) -> ReplayResult:
    """Run the trades through one account under `rules` (see the module docstring)."""
    ordered = sorted(trades, key=lambda t: (t.ts_in, t.cell))
    # Events: exits before entries at the same instant, so a slot freed at a bar is usable
    # by an entry on that bar — the same order a single cell's strategy works in.
    events: list[tuple[datetime, int, int]] = []
    for index, trade in enumerate(ordered):
        events.append((trade.ts_in, 1, index))
        events.append((trade.ts_out, 0, index))
    events.sort()

    result = ReplayResult(rules=rules)
    equity = rules.starting_equity
    peak = equity
    open_risk: dict[int, float] = {}  # trade index -> cash at risk
    # side -> group -> open trades of that group on that side
    sides: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    by_cell: dict[str, float] = defaultdict(float)
    by_fold: dict[int, float] = defaultdict(float)
    daily: dict[date, float] = defaultdict(float)

    for ts, kind, index in events:
        trade = ordered[index]
        if kind == 0:
            risk = open_risk.pop(index, None)
            if risk is None:
                continue  # it was skipped at entry
            pnl = trade.r_net * risk
            equity += pnl
            groups = sides[trade.side]
            groups[trade.group_key] -= 1
            if groups[trade.group_key] <= 0:
                del groups[trade.group_key]
            by_cell[trade.cell] += pnl
            if trade.fold is not None:
                by_fold[trade.fold] += pnl
            daily[ts.date()] += pnl
            peak = max(peak, equity)
            result.max_drawdown = max(result.max_drawdown, 1.0 - equity / peak)
            continue
        if not math.isfinite(trade.r_net):
            result.skipped_no_risk += 1
            continue
        groups = sides[trade.side]
        if (
            rules.max_per_side is not None
            and trade.group_key not in groups
            and len(groups) >= rules.max_per_side
        ):
            result.skipped_side += 1
            continue
        risk_share = rules.risk_per_trade * _vol_scale(daily, equity, ts.date(), rules)
        heat = sum(open_risk.values()) / equity if equity > 0 else math.inf
        if rules.max_heat is not None and heat + risk_share > rules.max_heat + 1e-12:
            result.skipped_heat += 1
            continue
        open_risk[index] = risk_share * equity
        groups[trade.group_key] += 1
        result.taken += 1
        result.peak_heat = max(result.peak_heat, heat + risk_share)

    result.ending_equity = equity
    result.daily_pnl = dict(sorted(daily.items()))
    result.pnl_by_cell = dict(sorted(by_cell.items()))
    result.pnl_by_fold = dict(sorted(by_fold.items()))
    return result


def _vol_scale(
    daily: Mapping[date, float], equity: float, today: date, rules: ReplayRules
) -> float:
    """`target / realised` over the look-back before `today`, clipped; 1 without a target."""
    if rules.target_vol is None:
        return 1.0
    if not daily:
        return 1.0
    first_day = min(daily)
    elapsed_days = min(rules.vol_lookback_days, max(0, (today - first_day).days))
    if elapsed_days < 5:
        return 1.0
    window = [pnl / equity for day, pnl in daily.items() if 0 < (today - day).days <= elapsed_days]
    # Days without an exit are flat days: count them, or the vol is overstated.
    flat = elapsed_days - len(window)
    returns = window + [0.0] * max(flat, 0)
    if len(window) < 5:
        return 1.0  # not enough history yet to scale on
    realised = _stdev(returns) * math.sqrt(365.0)
    if realised <= 0:
        return rules.max_scale
    return min(max(rules.target_vol / realised, rules.min_scale), rules.max_scale)


def _daily_returns(daily: Mapping[date, float], starting_equity: float) -> list[float]:
    """Daily returns over every calendar day from the first to the last exit."""
    if not daily:
        return []
    days = sorted(daily)
    first, last = days[0], days[-1]
    equity = starting_equity
    returns: list[float] = []
    for offset in range((last - first).days + 1):
        day = date.fromordinal(first.toordinal() + offset)
        pnl = daily.get(day, 0.0)
        returns.append(pnl / equity if equity > 0 else 0.0)
        equity += pnl
    return returns


def _stdev(values: Sequence[float]) -> float:
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


def render_markdown(results: Mapping[str, ReplayResult]) -> str:
    """One table comparing the named replays (e.g. uncapped vs capped vs vol-targeted)."""
    lines = [
        "| replay | trades | skipped heat/side | return | max DD (realised) | vol (ann.) "
        "| Sharpe | peak heat |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, res in results.items():
        vol, sharpe = res.annualised_vol(), res.sharpe()
        lines.append(
            f"| {name} | {res.taken} | {res.skipped_heat}/{res.skipped_side} "
            f"| {res.total_return:+.2%} | {res.max_drawdown:.2%} "
            f"| {'—' if vol is None else f'{vol:.1%}'} "
            f"| {'—' if sharpe is None else f'{sharpe:.2f}'} | {res.peak_heat:.1%} |"
        )
    return "\n".join(lines)
