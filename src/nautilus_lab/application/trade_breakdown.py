"""Per-trade breakdown of a research backtest from its decision trace (docs/33).

`lab research` reports one number per fold. Whether that number came from a few long
trends, from the range leg, or from fees is only visible trade by trade, and the batch
analyses of 2026-10-01/02 had to rebuild trades by hand each time. This module does it
once, the same way for every cell:

* trades are rebuilt from the backtest's own records: `ENTRY_FILLED` (venue price, size,
  fee, stop), then the first exit (`STOP_LOSS` at the venue's stop fill, or a bar
  `EXIT` / `REVERSE` / regime flatten at the bar close, which is where a zero-latency
  backtest fills it);
* every trade is tagged with the two entry-gate features of `domain/entry_filters.py`,
  computed by **the same** `EntryFilter` code over the trace's closed bars, so "aligned
  with the slow EMA" here means exactly what `ENTRY_FILTER_HTF_TREND=true` would test;
* money is split into gross, fees and net, and into R (gross PnL over the cash at risk
  between the entry fill and the protective stop), so fee drag shows up as `fee_r`.

Honesty rules:

* the exit fee is not in the trace; it is estimated as `taker_fee x exit notional`
  and the report says so;
* tagging trades by a feature found on this very OOS data is a *diagnostic*. A gate
  that "would have helped" is a hypothesis to pre-register, never a result.

Floats are fine here: this is reporting over finished runs, not a trading decision.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.entry_filters import EntryFilter, EntryFilterParams

#: Bar-decision outcomes that open a position (REVERSE also closes the previous one).
_ENTRY_OUTCOMES = frozenset({"ENTRY_OPENED", "REVERSE"})
#: Bar-decision outcomes that flatten at the bar close.
_BAR_EXIT_OUTCOMES = frozenset(
    {"EXIT", "REVERSE", "FLATTEN_REGIME_CHANGE", "RATCHET_EXIT", "TAKE_PROFIT", "MANUAL_CLOSE"}
)
#: Holding-time buckets, hours (upper bounds, inclusive).
HOLD_BUCKETS: tuple[tuple[str, float], ...] = (
    ("<=2h", 2.0),
    ("2-6h", 6.0),
    ("6-24h", 24.0),
    ("1-3d", 72.0),
    (">3d", float("inf")),
)

_FOLD_RE = re.compile(r"-f(\d+)_\d{4}-\d{2}-\d{2}\.jsonl$")


def fold_of(filename: str) -> int | None:
    """`<session>-f3_2026-05-06.jsonl` -> 3; None for any other name."""
    match = _FOLD_RE.search(filename)
    return int(match.group(1)) if match else None


@dataclass(frozen=True, slots=True)
class Trade:
    fold: int
    side: str  # "LONG" / "SHORT"
    leg: str | None  # strategy component that emitted the entry, e.g. "UptrendBreakout"
    regime: str | None
    entry_reason: str | None
    ts_in: datetime
    px_in: float
    qty: float
    fee_in: float
    stop: float | None
    ts_out: datetime
    px_out: float
    exit_reason: str
    exit_fee: float
    slope_aligned: bool | None = None
    vol_ratio: float | None = None

    @property
    def direction(self) -> int:
        return 1 if self.side == "LONG" else -1

    @property
    def gross(self) -> float:
        return self.direction * (self.px_out - self.px_in) * self.qty

    @property
    def fees(self) -> float:
        return self.fee_in + self.exit_fee

    @property
    def net(self) -> float:
        return self.gross - self.fees

    @property
    def risk_cash(self) -> float | None:
        if self.stop is None:
            return None
        risk = abs(self.px_in - self.stop) * self.qty
        return risk if risk > 0 else None

    @property
    def r_multiple(self) -> float | None:
        risk = self.risk_cash
        return None if risk is None else self.gross / risk

    @property
    def fee_r(self) -> float | None:
        risk = self.risk_cash
        return None if risk is None else self.fees / risk

    @property
    def hold_hours(self) -> float:
        return (self.ts_out - self.ts_in).total_seconds() / 3600.0

    @property
    def hold_bucket(self) -> str:
        hours = self.hold_hours
        for label, upper in HOLD_BUCKETS:
            if hours <= upper:
                return label
        return HOLD_BUCKETS[-1][0]


@dataclass(frozen=True, slots=True)
class Reconstruction:
    trades: tuple[Trade, ...]
    open_at_end: int
    outcomes: Mapping[str, int]


def _ts(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"record without a timestamp: {value!r}")
    return datetime.fromisoformat(value)


def _num(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _step_values(record: Mapping[str, Any], component: str) -> Mapping[str, Any] | None:
    for item in record.get("steps") or ():
        if isinstance(item, Mapping) and item.get("component") == component:
            values = item.get("values")
            return values if isinstance(values, Mapping) else {}
    return None


def _entry_leg(record: Mapping[str, Any]) -> str | None:
    """The last strategy step that emitted a directional signal on this bar."""
    leg: str | None = None
    for item in record.get("steps") or ():
        if (
            isinstance(item, Mapping)
            and item.get("stage") == "strategy"
            and item.get("verdict") == "emit"
            and item.get("result") in ("buy", "sell")
        ):
            leg = str(item.get("component"))
    return leg


def reconstruct_trades(
    records: Iterable[tuple[int, Mapping[str, Any]]],
    *,
    taker_fee: float,
) -> Reconstruction:
    """Rebuild round trips from `(fold, record)` pairs **in log order**.

    Log order matters: at zero latency a bar's decision and its fill share a timestamp,
    and only the order they were written in says which came first.
    """
    trades: list[Trade] = []
    outcomes: dict[str, int] = defaultdict(int)
    pending: dict[str, Any] = {}
    current: dict[str, Any] | None = None
    current_fold: int | None = None
    open_at_end = 0

    def close(ts: datetime, price: float, reason: str) -> None:
        nonlocal current
        if current is None:
            return
        trades.append(
            Trade(
                **current,
                ts_out=ts,
                px_out=price,
                exit_reason=reason,
                exit_fee=abs(price * current["qty"]) * taker_fee,
            )
        )
        current = None

    for fold, record in records:
        if fold != current_fold:
            if current is not None:
                open_at_end += 1  # a fold ends with the position still open
            current, pending, current_fold = None, {}, fold
        kind = record.get("kind")
        outcome = str(record.get("outcome") or "")
        outcomes[f"{kind}:{outcome}"] += 1
        if kind == "bar_decision":
            close_px = _num(record.get("close"))
            if current is not None and outcome in _BAR_EXIT_OUTCOMES and close_px is not None:
                close(_ts(record.get("ts")), close_px, str(record.get("signal_reason") or outcome))
            if outcome in _ENTRY_OUTCOMES:
                pending = {
                    "leg": _entry_leg(record),
                    "regime": record.get("regime"),
                    "entry_reason": record.get("signal_reason"),
                }
            continue
        if kind != "intrabar":
            continue
        if outcome == "ENTRY_FILLED":
            fill = _step_values(record, "fill") or {}
            stop = _step_values(record, "protective_stop") or {}
            price, qty = _num(fill.get("fill_price")), _num(fill.get("qty"))
            if price is None or qty is None or price <= 0 or qty <= 0:
                continue
            current = {
                "fold": fold,
                "side": str(fill.get("side") or "LONG"),
                "leg": pending.get("leg"),
                "regime": pending.get("regime") or record.get("regime"),
                "entry_reason": pending.get("entry_reason"),
                "ts_in": _ts(record.get("ts")),
                "px_in": price,
                "qty": qty,
                "fee_in": _num(fill.get("fee")) or abs(price * qty) * taker_fee,
                "stop": _num(stop.get("stop_loss")),
            }
            pending = {}
        elif outcome == "STOP_LOSS" and current is not None:
            level = _num((_step_values(record, "stop_loss") or {}).get("level"))
            if level is not None:
                close(_ts(record.get("ts")), level, "STOP_LOSS")
    if current is not None:
        open_at_end += 1
    return Reconstruction(tuple(trades), open_at_end, dict(outcomes))


def bars_from_records(records: Iterable[Mapping[str, Any]], instrument_id: str) -> list[OhlcvBar]:
    """Closed bars carried by `bar_decision` records, de-duplicated across folds."""
    by_ts: dict[datetime, OhlcvBar] = {}
    for record in records:
        bar = record.get("bar")
        if record.get("kind") != "bar_decision" or not isinstance(bar, Mapping):
            continue
        ts = _ts(record.get("ts"))
        try:
            by_ts[ts] = OhlcvBar(
                instrument_id=instrument_id,
                ts_utc=ts,
                open=Decimal(str(bar["o"])),
                high=Decimal(str(bar["h"])),
                low=Decimal(str(bar["l"])),
                close=Decimal(str(bar["c"])),
                volume=Decimal(str(bar.get("v", 0))),
            )
        except (KeyError, ArithmeticError, ValueError):
            continue
    return [by_ts[ts] for ts in sorted(by_ts)]


def gate_features(
    bars: Sequence[OhlcvBar], params: EntryFilterParams
) -> dict[datetime, tuple[float | None, float | None]]:
    """`ts -> (htf_slope, vol_ratio)` after each closed bar, by the gate's own code."""
    gate = EntryFilter(params)
    features: dict[datetime, tuple[float | None, float | None]] = {}
    for bar in bars:
        if bar.close <= 0:
            continue
        gate.update(bar)
        slope, ratio = gate.htf_slope(), gate.vol_ratio()
        features[bar.ts_utc] = (
            None if slope is None else float(slope),
            None if ratio is None else float(ratio),
        )
    return features


def tag_trades(
    trades: Iterable[Trade], features: Mapping[datetime, tuple[float | None, float | None]]
) -> list[Trade]:
    """Attach slope alignment and vol ratio as of the entry bar (its close = the fill)."""
    tagged: list[Trade] = []
    for trade in trades:
        slope, ratio = features.get(trade.ts_in, (None, None))
        aligned = None if slope is None or slope == 0 else (slope > 0) == (trade.direction > 0)
        tagged.append(
            Trade(
                fold=trade.fold,
                side=trade.side,
                leg=trade.leg,
                regime=trade.regime,
                entry_reason=trade.entry_reason,
                ts_in=trade.ts_in,
                px_in=trade.px_in,
                qty=trade.qty,
                fee_in=trade.fee_in,
                stop=trade.stop,
                ts_out=trade.ts_out,
                px_out=trade.px_out,
                exit_reason=trade.exit_reason,
                exit_fee=trade.exit_fee,
                slope_aligned=aligned,
                vol_ratio=ratio,
            )
        )
    return tagged


@dataclass(frozen=True, slots=True)
class GroupRow:
    key: str
    n: int
    net: float
    gross: float
    fees: float
    win_rate: float
    mean_r: float | None


def summarize(
    trades: Sequence[Trade],
    key: Callable[[Trade], object],
    *,
    order: Sequence[str] = (),
) -> list[GroupRow]:
    """Totals per group; groups listed in `order` first, the rest alphabetically."""
    groups: dict[str, list[Trade]] = defaultdict(list)
    for trade in trades:
        groups[str(key(trade))].append(trade)
    rank = {name: index for index, name in enumerate(order)}
    rows: list[GroupRow] = []
    for name in sorted(groups, key=lambda g: (rank.get(g, len(rank)), g)):
        items = groups[name]
        rs = [r for r in (t.r_multiple for t in items) if r is not None]
        rows.append(
            GroupRow(
                key=name,
                n=len(items),
                net=sum(t.net for t in items),
                gross=sum(t.gross for t in items),
                fees=sum(t.fees for t in items),
                win_rate=sum(1 for t in items if t.net > 0) / len(items),
                mean_r=sum(rs) / len(rs) if rs else None,
            )
        )
    return rows


def vol_bucket(trade: Trade, *, threshold: float = 1.0) -> str:
    if trade.vol_ratio is None:
        return "n/a"
    return f">={threshold:g}" if trade.vol_ratio >= threshold else f"<{threshold:g}"


def profit_factor(trades: Sequence[Trade]) -> float | None:
    wins = sum(t.net for t in trades if t.net > 0)
    losses = -sum(t.net for t in trades if t.net < 0)
    return None if losses == 0 else wins / losses


def _fmt(value: float | None, digits: int = 0) -> str:
    return "—" if value is None else f"{value:,.{digits}f}"


def render_cell_markdown(name: str, rec: Reconstruction, trades: Sequence[Trade]) -> str:
    """One cell's section of the batch report."""
    lines = [f"## {name}", ""]
    if not trades:
        lines += ["No completed trades in the decision trace.", ""]
        return "\n".join(lines)
    fee_rs = [f for f in (t.fee_r for t in trades) if f is not None]
    rs = [r for r in (t.r_multiple for t in trades) if r is not None]
    top = sorted((t.net for t in trades), reverse=True)[:4]
    lines += [
        f"- trades: {len(trades)} (open at a fold's end: {rec.open_at_end})",
        f"- net {_fmt(sum(t.net for t in trades))} = gross {_fmt(sum(t.gross for t in trades))}"
        f" - fees {_fmt(sum(t.fees for t in trades))} (exit fee estimated at the taker rate)",
        f"- profit factor {_fmt(profit_factor(trades), 2)}; "
        f"mean gross R {_fmt(sum(rs) / len(rs) if rs else None, 3)}; "
        f"fees per trade {_fmt(sum(fee_rs) / len(fee_rs) if fee_rs else None, 3)} R",
        f"- best 4 trades together: {_fmt(sum(top))}",
        "",
    ]
    hold_order = tuple(label for label, _ in HOLD_BUCKETS)
    sections: tuple[tuple[str, Callable[[Trade], object], Sequence[str]], ...] = (
        ("fold", lambda t: t.fold, ()),
        ("side", lambda t: t.side, ()),
        ("leg", lambda t: t.leg or "n/a", ()),
        ("exit", lambda t: t.exit_reason, ()),
        ("holding", lambda t: t.hold_bucket, hold_order),
        ("slow-EMA slope aligned (H1 diagnostic)", lambda t: t.slope_aligned, ()),
        ("vol ratio fast/slow (H2 diagnostic)", vol_bucket, ()),
    )
    for title, key, order in sections:
        lines += [
            f"### by {title}",
            "",
            "| key | n | net | gross | fees | win | mean R |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        lines += [
            f"| {row.key} | {row.n} | {_fmt(row.net)} | {_fmt(row.gross)} | {_fmt(row.fees)}"
            f" | {row.win_rate:.0%} | {_fmt(row.mean_r, 2)} |"
            for row in summarize(trades, key, order=order)
        ]
        lines.append("")
    return "\n".join(lines)
