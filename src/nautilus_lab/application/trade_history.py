"""Reconstruct and enrich completed and open trades from decision logs and fills.

Used by both live paper sessions and research backtests so the dashboard's trade
inspection view presents identical diagnostics, indicators and charts.

Honesty rules this module follows, because the dashboard is where a diagnostic can be
mistaken for accounting:

* every money field carries its **basis** (`pnl_source`, `qty_known`, `fee_known`), so the
  UI can write "price difference, size unknown" instead of dressing a per-unit number up
  as account PnL;
* a backtest has no fill ledger in its decision log (`fill_ids` is empty by design), so its
  trades report price arithmetic and no fees — never a zero that looks like a measurement;
* an excursion (MAE/MFE) is computed from **decision closes**, which is the only series the
  log holds, and is labelled as such rather than presented as intrabar extremes.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from typing import Any

from nautilus_lab.application.decision_trace_codec import upgrade_row

#: Outcomes that open a position. `REVERSE` closes the old side and opens the new one.
ENTRY_OUTCOMES = ("ENTRY_OPENED", "REVERSE")

#: Outcomes that flatten the position.
EXIT_OUTCOMES = (
    "EXIT",
    "STOP_LOSS",
    "RATCHET_EXIT",
    "TAKE_PROFIT",
    "FLATTEN_REGIME_CHANGE",
    "MANUAL_CLOSE",
)

#: The intrabar record a backtest writes when its entry order fills (price, size, stop).
ENTRY_FILL_OUTCOME = "ENTRY_FILLED"

#: A fill is stamped with wall-clock `YYYY-mm-dd HH:MM:SS`, a decision with the **bar's**
#: end. On a 1m bar those differ by under a second, but a restarted or slow feed can shift
#: one of them, so fills are matched inside a small window rather than on equality.
FILL_MATCH_TOLERANCE = timedelta(minutes=5)

#: The size a trade is assumed to have when the log never recorded one.
DEFAULT_QTY = 1.0


def parse_ts(ts_val: object) -> datetime | None:
    if isinstance(ts_val, datetime):
        return ts_val if ts_val.tzinfo is not None else ts_val.replace(tzinfo=UTC)
    if isinstance(ts_val, str) and ts_val:
        try:
            dt = datetime.fromisoformat(ts_val)
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(ts_val, fmt).replace(tzinfo=UTC)
            except ValueError:
                pass
    return None


def _to_float(val: object) -> float | None:
    """A number out of a JSON row, or None. Never raises: a log row is untrusted text."""
    if val is None or val == "" or val == "—":
        return None
    if isinstance(val, (int, float, Decimal, str)):
        try:
            return float(val)
        except (ValueError, TypeError, InvalidOperation):
            return None
    return None


def reconstruct_trades_from_decisions(
    logs: Sequence[dict[str, Any]],
    *,
    fills: Sequence[dict[str, Any]] | None = None,
    active_position: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Reconstruct complete and in-progress trades from chronological decision records.

    Matches entry outcomes (ENTRY_OPENED, REVERSE) with exit outcomes (EXIT, STOP_LOSS,
    TAKE_PROFIT, FLATTEN_REGIME_CHANGE, MANUAL_CLOSE), attaching intermediate
    decision records, indicators at entry/exit, SL/TP levels, and realized returns.

    The records are first split into **passes** (`_ordered_windows`). One file can hold
    several runs over the same window: a walk-forward writes every fold under one session id,
    so the timestamps restart mid-file. Sorting that flat and pairing entries with exits
    across the seam invents trades nobody made — a real log in this repository holds six
    replays of the same seven hours, and a naive sort produced a run of one-bar "trades"
    whose entry price equalled their exit price.
    """
    trades: list[dict[str, Any]] = []
    trade_counter = 0
    # Rows straight from a file lack `indicators` (derived from steps since docs/30) and
    # the run header is not a decision: normalise once here, whoever the caller is.
    logs = [upgrade_row(row) for row in logs if row.get("kind") != "run_header"]
    windows = _ordered_windows(logs)

    for index, window in enumerate(windows, start=1):
        counter, finished = _reconstruct_window(
            window,
            trade_counter=trade_counter,
            window_index=index,
            active_position=active_position if index == len(windows) else None,
        )
        trade_counter = counter
        trades.extend(finished)

    # Optional enrichment with executed fills if available
    if fills:
        _enrich_trades_with_fills(trades, fills)

    # Excursions last: they read the closes of every decision the trade kept.
    for trade in trades:
        _annotate_excursions(trade)

    return trades


def _ordered_windows(logs: Sequence[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """The records split where the clock restarts, each window sorted by timestamp.

    A pass over a window is written in time order, so a timestamp that goes **backwards**
    is a new pass, not a late row. Reverse-ordered input (a caller that read newest-first
    and forgot to reverse) has no such structure to find: it is sorted whole instead of
    being shredded into one row per window.
    """
    stamps = [parse_ts(row.get("ts")) for row in logs]
    backwards = sum(
        1
        for first, second in pairwise(stamps)
        if first is not None and second is not None and second < first
    )
    ordered = (
        sorted(logs, key=lambda r: parse_ts(r.get("ts")) or datetime.min.replace(tzinfo=UTC))
        if backwards * 2 > len(logs)
        else list(logs)
    )

    windows: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    last: datetime | None = None
    for row in ordered:
        when = parse_ts(row.get("ts"))
        if current and when is not None and last is not None and when < last:
            windows.append(current)
            current = []
        current.append(row)
        last = when
    if current:
        windows.append(current)

    return [
        sorted(window, key=lambda r: parse_ts(r.get("ts")) or datetime.min.replace(tzinfo=UTC))
        for window in windows
    ]


def _reconstruct_window(
    sorted_logs: Sequence[dict[str, Any]],
    *,
    trade_counter: int,
    window_index: int,
    active_position: dict[str, Any] | None,
) -> tuple[int, list[dict[str, Any]]]:
    """One pass over one window: pair entries with exits, keep the bar rows in between."""
    trades: list[dict[str, Any]] = []
    current_trade: dict[str, Any] | None = None

    for row in sorted_logs:
        outcome = str(row.get("outcome", "")).upper()
        price = _to_float(row.get("close")) or 0.0
        ts_str = row.get("ts", "")
        signal = str(row.get("signal", "")).lower()

        # Check for Entry / Reverse
        if outcome in ENTRY_OUTCOMES:
            # If a trade was already open, close it (e.g. reverse)
            if current_trade is not None:
                current_trade["exit_time"] = ts_str
                current_trade["exit_price"] = price
                current_trade["exit_outcome"] = outcome
                current_trade["exit_reason"] = f"{outcome}: reverse direction"
                current_trade["indicators_at_exit"] = row.get("indicators") or {}
                current_trade["states_at_exit"] = row.get("states") or {}
                current_trade["regime_at_exit"] = row.get("regime") or ""
                current_trade["status"] = "CLOSED"
                _finalize_trade(current_trade)
                trades.append(current_trade)
                current_trade = None

            trade_counter += 1
            side = "SHORT" if signal == "sell" else "LONG"
            session_id = row.get("session_id", "")
            instrument = row.get("instrument") or row.get("instrument_id") or "UNKNOWN"

            trade_id = (
                f"{session_id}-trade-{trade_counter}" if session_id else f"trade-{trade_counter}"
            )
            current_trade = {
                "id": trade_id,
                "session_id": session_id,
                "symbol": instrument,
                "side": side,
                "status": "OPEN",
                "window_index": window_index,
                "entry_time": ts_str,
                "entry_price": price,
                "entry_outcome": outcome,
                "entry_reason": row.get("signal_reason") or row.get("narrative") or "Signal entry",
                "stop_loss": _extract_level(row, "stop_loss"),
                "take_profit": _extract_level(row, "take_profit"),
                "qty": DEFAULT_QTY,
                "qty_known": False,
                "fee": None,
                "fee_known": False,
                "pnl_source": None,
                "indicators_at_entry": row.get("indicators") or {},
                "states_at_entry": row.get("states") or {},
                "regime_at_entry": row.get("regime") or "",
                "steps_at_entry": row.get("steps") or [],
                "narrative_at_entry": row.get("narrative") or "",
                "decisions": [row],
                "duration_bars": 1,
            }
            _apply_entry_step(current_trade, row)
            if current_trade["stop_loss"] is not None:
                current_trade["initial_stop_loss"] = current_trade["stop_loss"]
        elif current_trade is not None and outcome == ENTRY_FILL_OUTCOME:
            # Not a bar: the venue's answer to the entry. Kept in the trade's timeline but
            # not counted as a bar held.
            current_trade["decisions"].append(row)
            _apply_entry_fill(current_trade, row)
            level = _extract_level(row, "stop_loss")
            if level is not None:
                current_trade["stop_loss"] = level
                current_trade.setdefault("initial_stop_loss", level)
        elif current_trade is not None:
            current_trade["decisions"].append(row)
            current_trade["duration_bars"] += 1

            # Update trailing stop / TP if present in states or indicators
            updated_sl = _extract_level(row, "stop_loss")
            if updated_sl is not None:
                current_trade["stop_loss"] = updated_sl
            updated_tp = _extract_level(row, "take_profit")
            if updated_tp is not None:
                current_trade["take_profit"] = updated_tp

            # Check for Exit
            if outcome in EXIT_OUTCOMES:
                current_trade["exit_time"] = ts_str
                current_trade["exit_price"] = price
                current_trade["exit_outcome"] = outcome
                reason = outcome
                if row.get("signal_reason"):
                    reason += f": {row['signal_reason']}"
                current_trade["exit_reason"] = reason
                current_trade["indicators_at_exit"] = row.get("indicators") or {}
                current_trade["states_at_exit"] = row.get("states") or {}
                current_trade["regime_at_exit"] = row.get("regime") or ""
                current_trade["status"] = "CLOSED"
                _finalize_trade(current_trade)
                trades.append(current_trade)
                current_trade = None

    if current_trade is not None:
        current_trade["status"] = "OPEN"
        if active_position is not None:
            mark = _to_float(active_position.get("mark_price"))
            if mark is not None:
                current_trade["mark_price"] = mark
            floating = _to_float(active_position.get("unrealized_pnl"))
            if floating is not None:
                current_trade["realized_pnl"] = floating
                current_trade["pnl_source"] = "mark"
            if "unrealized_pnl_pct" in active_position:
                current_trade["realized_pnl_pct"] = _to_float(
                    str(active_position["unrealized_pnl_pct"]).rstrip("%")
                )
            if active_position.get("stop_loss"):
                current_trade["stop_loss"] = _to_float(active_position["stop_loss"])
            if active_position.get("take_profit"):
                current_trade["take_profit"] = _to_float(active_position["take_profit"])
            if active_position.get("qty"):
                current_trade["qty"] = _to_float(active_position["qty"]) or DEFAULT_QTY
                current_trade["qty_known"] = True
        _finalize_trade(current_trade)
        trades.append(current_trade)

    return trade_counter, trades


def _step_values(row: dict[str, Any], stage: str, result: str) -> dict[str, Any] | None:
    for item in row.get("steps") or []:
        if isinstance(item, dict) and item.get("stage") == stage and item.get("result") == result:
            values = item.get("values")
            return values if isinstance(values, dict) else {}
    return None


def _apply_entry_step(trade: dict[str, Any], row: dict[str, Any]) -> None:
    """The size the entry bar's execution step sent (backtest and paper both log it)."""
    values = _step_values(row, "execution", "entry")
    if not values:
        return
    qty = _to_float(values.get("qty"))
    if qty:
        trade["qty"] = qty
        trade["qty_known"] = True
    side = values.get("side")
    if side in ("LONG", "SHORT"):
        trade["side"] = side


def _apply_entry_fill(trade: dict[str, Any], row: dict[str, Any]) -> None:
    """Attach what the venue did with the entry: fill price, slippage, fee, delay.

    `entry_price` stays the decision bar's close on purpose: exits are priced the same way
    (a backtest logs no exit fill), so PnL compares like with like. The fill is reported
    next to it, where the gap between the two is the finding.
    """
    values = _step_values(row, "execution", "entry_filled")
    if not values:
        return
    for source, target in (
        ("fill_price", "entry_fill_price"),
        ("slippage_bps", "entry_slippage_bps"),
        ("fill_delay_s", "entry_fill_delay_s"),
    ):
        number = _to_float(values.get(source))
        if number is not None:
            trade[target] = number
    trade["entry_fill_time"] = row.get("ts")
    qty = _to_float(values.get("qty"))
    if qty:
        trade["qty"] = qty
        trade["qty_known"] = True
    fee = _to_float(values.get("fee"))
    if fee is not None:
        trade["fee"] = fee
        trade["fee_known"] = True


def _extract_level(row: dict[str, Any], key: str) -> float | None:
    states = row.get("states") or {}
    indicators = row.get("indicators") or {}
    val = states.get(key)
    if val is None:
        val = indicators.get(key)
    return _to_float(val)


def _finalize_trade(trade: dict[str, Any]) -> None:
    entry_px = trade.get("entry_price") or 0.0
    exit_px = trade.get("exit_price") or trade.get("mark_price")
    side = trade.get("side", "LONG")
    qty = trade.get("qty", DEFAULT_QTY)

    # Duration calculation
    dt_entry = parse_ts(trade.get("entry_time"))
    dt_exit = parse_ts(trade.get("exit_time"))
    if dt_entry and dt_exit:
        trade["duration_seconds"] = int((dt_exit - dt_entry).total_seconds())
    else:
        trade["duration_seconds"] = 0

    if exit_px is not None and entry_px > 0 and trade.get("realized_pnl") is None:
        delta = exit_px - entry_px if side == "LONG" else entry_px - exit_px
        pnl = delta * qty
        pct = (delta / entry_px) * 100.0
        trade["realized_pnl"] = round(pnl, 4)
        trade["realized_pnl_pct"] = round(pct, 2)
        trade["pnl_source"] = "price_delta"

    # R-multiple against the stop the trade was OPENED with: a ratchet that trails the
    # stop to break-even would otherwise shrink the risk to ~0 and inflate R.
    sl = trade.get("initial_stop_loss", trade.get("stop_loss"))
    if sl is not None and entry_px > 0 and exit_px is not None:
        risk_dist = abs(entry_px - sl)
        if risk_dist > 0:
            reward_dist = exit_px - entry_px if side == "LONG" else entry_px - exit_px
            trade["r_multiple"] = round(reward_dist / risk_dist, 2)


def _annotate_excursions(trade: dict[str, Any]) -> None:
    """Best and worst close the trade saw, signed by direction.

    Closes, not highs and lows: the decision log records one close per bar and no OHLC, so
    an "excursion" here is a close-to-close measurement. Calling it MAE/MFE without that
    qualifier would read as an intrabar extreme the log cannot support.
    """
    entry_px = _to_float(trade.get("entry_price"))
    side = trade.get("side", "LONG")
    closes = [
        value
        for value in (_to_float(row.get("close")) for row in trade.get("decisions") or ())
        if value is not None
    ]
    if trade.get("mark_price") is not None:
        closes.append(trade["mark_price"])
    if entry_px is None or entry_px <= 0 or not closes:
        trade["excursion_basis"] = "decision closes"
        return

    sign = 1.0 if side == "LONG" else -1.0
    best = max(closes, key=lambda value: sign * (value - entry_px))
    worst = min(closes, key=lambda value: sign * (value - entry_px))
    trade["mfe_close"] = round((best - entry_px) * sign, 4)
    trade["mae_close"] = round((worst - entry_px) * sign, 4)
    trade["mfe_close_pct"] = round((best - entry_px) * sign / entry_px * 100.0, 2)
    trade["mae_close_pct"] = round((worst - entry_px) * sign / entry_px * 100.0, 2)
    trade["excursion_basis"] = "decision closes"


def trade_summary(trade: dict[str, Any]) -> dict[str, Any]:
    """One row of the trade list: what a reader needs to pick a trade, no per-bar rows.

    The dashboard's list is fetched on every poll of a running session, while the full
    trade carries every decision since entry — hundreds of records on a one-minute robot.
    The detail view asks for those by id instead.
    """
    return {
        key: trade.get(key)
        for key in (
            "id",
            "session_id",
            "symbol",
            "side",
            "status",
            "window_index",
            "entry_time",
            "entry_price",
            "entry_reason",
            "exit_time",
            "exit_price",
            "exit_outcome",
            "exit_reason",
            "stop_loss",
            "initial_stop_loss",
            "take_profit",
            "entry_fill_price",
            "entry_slippage_bps",
            "entry_fill_delay_s",
            "qty",
            "qty_known",
            "fee",
            "fee_known",
            "pnl_source",
            "realized_pnl",
            "realized_pnl_pct",
            "r_multiple",
            "mfe_close",
            "mae_close",
            "mfe_close_pct",
            "mae_close_pct",
            "excursion_basis",
            "duration_bars",
            "duration_seconds",
            "regime_at_entry",
            "regime_at_exit",
            "mark_price",
        )
    } | {"decision_count": len(trade.get("decisions") or ())}


def find_trade(trades: Sequence[dict[str, Any]], trade_id: str) -> dict[str, Any] | None:
    """The trade with this id, or None. Ids are built by `reconstruct_trades_from_decisions`.

    A live session keeps appending, so a trade's id is stable but its *number* is not: the
    counter restarts at 1 for every scan, and a truncated window can begin mid-trade. Ids
    are therefore resolved against a fresh reconstruction of the same window, never stored.
    """
    for trade in trades:
        if trade.get("id") == trade_id:
            return trade
    return None


def _fill_ts(fill: dict[str, Any]) -> datetime | None:
    return parse_ts(fill.get("ts"))


def _fill_money(fill: dict[str, Any], key: str) -> float | None:
    value = fill.get(key)
    if value is None:
        return None
    return _to_float(str(value).replace("+", ""))


def _pick_fill(
    candidates: Iterable[dict[str, Any]],
    *,
    start: datetime,
    end: datetime,
    opener: bool,
    after: datetime | None = None,
) -> dict[str, Any] | None:
    """The earliest fill in [start, end] whose `reason` marks it as an open or a close.

    `after` (exclusive) rejects a fill stamped at or before a known-boundary fill. A
    reversal writes the closing fill of the old position and the opening fill of the new
    one at the same instant, so without it the old close would be read as the new trade's
    exit — the trade would show a PnL taken from its predecessor.
    """
    best: tuple[datetime, dict[str, Any]] | None = None
    for fill in candidates:
        reason = str(fill.get("reason", "")).lower()
        if reason.startswith("open ") != opener:
            continue
        when = _fill_ts(fill)
        if when is None or not (start <= when <= end):
            continue
        if after is not None and when <= after:
            continue
        if best is None or when < best[0]:
            best = (when, fill)
    return None if best is None else best[1]


def _enrich_trades_with_fills(
    trades: list[dict[str, Any]],
    fills: Sequence[dict[str, Any]],
    *,
    tolerance: timedelta = FILL_MATCH_TOLERANCE,
) -> None:
    """Attach the venue's own fills to reconstructed trades, matched by **time window**.

    The previous version zipped trades with closing fills by position, which silently
    attached one trade's PnL and fee to another as soon as a single trade had no closing
    fill in the list (an open trade, a stoppage, a fill written outside the log window).
    A window match is not exact either — the log timestamps the **bar**, the ledger the
    **fill** — so a matched trade says `pnl_source: "fills"` and an unmatched one keeps its
    price arithmetic with the basis spelled out.
    """
    for trade in trades:
        entry_at = parse_ts(trade.get("entry_time"))
        exit_at = parse_ts(trade.get("exit_time")) or entry_at
        if entry_at is None or exit_at is None:
            continue

        entry_fill = _pick_fill(
            fills,
            start=entry_at - tolerance,
            end=entry_at + tolerance,
            opener=True,
        )
        entry_fill_at = None if entry_fill is None else _fill_ts(entry_fill)
        exit_fill = _pick_fill(
            fills,
            start=entry_at - tolerance,
            end=exit_at + tolerance,
            opener=False,
            after=entry_fill_at,
        )

        fees: list[float] = []
        if entry_fill is not None:
            entry_fee = _fill_money(entry_fill, "fee")
            if entry_fee is not None:
                fees.append(entry_fee)

        if exit_fill is not None:
            exit_fee = _fill_money(exit_fill, "fee")
            if exit_fee is not None:
                fees.append(exit_fee)
            pnl_val = _fill_money(exit_fill, "realized_pnl")
            if pnl_val is not None:
                trade["realized_pnl"] = pnl_val
                trade["pnl_source"] = "fills"
                notional = (trade.get("entry_price") or 0.0) * (trade.get("qty") or DEFAULT_QTY)
                if notional > 0:
                    trade["realized_pnl_pct"] = round((pnl_val / notional) * 100.0, 2)

        for fill in (entry_fill, exit_fill):
            qty = None if fill is None else _fill_money(fill, "qty")
            if qty:
                trade["qty"] = qty
                trade["qty_known"] = True

        if fees:
            trade["fee"] = round(sum(fees), 8)
            trade["fee_known"] = True
