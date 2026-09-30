"""The live paper terminal: sessions on real Binance bars, simulated fills, WebSocket feed.

Only the paper venue exists; nothing here can reach an exchange order endpoint.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from itertools import pairwise
from typing import Any

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from nautilus_lab.api.context import Lab, LabContext
from nautilus_lab.api.live_paper_boot import live_config_from_settings
from nautilus_lab.api.batch_store import decision_reader, find_session_cell
from nautilus_lab.api.live_sessions import resolve_decision_log_key
from nautilus_lab.api.paper_streamer import LivePaperSessionManager
from nautilus_lab.api.requests import PaperLiveStartRequest, PaperLiveStopsUpdateRequest
from nautilus_lab.application.trade_history import (
    find_trade,
    parse_ts,
    reconstruct_trades_from_decisions,
    trade_summary,
)

router = APIRouter()


def _idle_state(ctx: LabContext) -> dict[str, Any]:
    """What the terminal shows when no session is selected or running."""
    state = LivePaperSessionManager().to_state_dict()
    state["persisted"] = ctx.sessions.persisted
    return state


def _session_or_404(ctx: LabContext, key: str) -> LivePaperSessionManager:
    manager = ctx.sessions.find(key)
    if manager is None:
        raise HTTPException(status_code=404, detail=f"no live paper session {key!r}")
    return manager


def _primary_or_400(ctx: LabContext) -> LivePaperSessionManager:
    manager = ctx.sessions.primary()
    if manager is None:
        raise HTTPException(status_code=400, detail="no live paper session")
    return manager


async def _create_session(ctx: LabContext, req: PaperLiveStartRequest) -> LivePaperSessionManager:
    # Robot parameters, fees and breakers come from the same Settings the research runs
    # use, so the terminal rehearses the tested configuration rather than its own defaults.
    config = live_config_from_settings(
        ctx.settings(),
        symbol=req.symbol,
        interval=req.interval,
        robot=req.robot,
        starting_equity=Decimal(req.starting_equity),
        risk_per_trade=Decimal(req.risk_per_trade),
        stop_pct=Decimal(req.stop_pct),
        take_profit_multiple=Decimal(req.take_profit_multiple),
        mode=req.mode,
        auto_trade=req.auto_trade,
        name=req.name,
        notes=req.notes,
        created_from="ui",
    )
    try:
        return await ctx.sessions.create(config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _close_position(manager: LivePaperSessionManager) -> dict[str, Any]:
    msg = manager.close_position_manual()
    await manager.broadcast_state()
    return {"status": "ok", "message": msg}


async def _update_stops(
    manager: LivePaperSessionManager, req: PaperLiveStopsUpdateRequest
) -> dict[str, Any]:
    sl = Decimal(req.stop_loss) if req.stop_loss else None
    tp = Decimal(req.take_profit) if req.take_profit else None
    msg = manager.update_stops(sl, tp)
    await manager.broadcast_state()
    return {"status": "ok", "message": msg}


async def _set_paused(ctx: LabContext, key: str, paused: bool) -> LivePaperSessionManager:
    try:
        return await ctx.sessions.set_paused(key, paused)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"no live paper session {key!r}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---- several sessions -------------------------------------------------------------
@router.get("/api/paper/sessions")
def list_paper_sessions(ctx: Lab) -> dict[str, Any]:
    return {"sessions": ctx.sessions.summaries(), "portfolio": ctx.sessions.portfolio()}


@router.get("/api/paper/portfolio")
def get_paper_portfolio(ctx: Lab) -> dict[str, Any]:
    return ctx.sessions.portfolio()


@router.post("/api/paper/sessions")
async def create_paper_session(ctx: Lab, req: PaperLiveStartRequest) -> dict[str, Any]:
    manager = await _create_session(ctx, req)
    return {
        "status": "started",
        "session_id": manager.session_id,
        "name": manager.config.name,
        "message": f"Started {manager.config.name} ({manager.config.symbol})",
    }


@router.get("/api/paper/sessions/{key}")
def get_paper_session(ctx: Lab, key: str) -> dict[str, Any]:
    return _session_or_404(ctx, key).to_state_dict()


@router.post("/api/paper/sessions/{key}/stop")
async def stop_paper_session(ctx: Lab, key: str) -> dict[str, Any]:
    manager = _session_or_404(ctx, key)
    await manager.stop()
    return {"status": "stopped", "message": f"Stopped {manager.config.name}"}


@router.get("/api/paper/sessions/{key}/decision-log")
def get_paper_session_decision_log(
    ctx: Lab,
    key: str,
    lines: int = Query(100, ge=1, le=1000),
    outcome: str | None = Query(None, description="Comma-separated outcome codes"),
    kind: str | None = Query(None, pattern="^(bar_decision|intrabar)$"),
    since: datetime | None = None,
    until: datetime | None = None,
    regime: str | None = Query(None, description="Filter by regime (uptrend|downtrend|range)"),
    signal: str | None = Query(None, pattern="^(buy|sell|flat)$"),
) -> dict[str, Any]:
    """Decisions recorded for this session at bar closes.

    The writer keys its files by **session id** (docs/20, `JsonlDecisionLogWriter`), so the
    lookup must use the same key: reading by `config.name` found nothing and the dashboard
    showed "No decision logs found" while the files were being written all along.

    A research backtest files under its own `single_backtest.session_id` and has no live
    session, so a key with no session behind it is read as a plain log key instead of a
    404 — that is what the dashboard's Backtest Details asks for.
    """
    manager = ctx.sessions.find(key)
    if manager is not None and not manager.session_id:
        return {
            "status": "error",
            "message": "Session has no id yet: decision logs are keyed by session id",
            "logs": [],
        }

    session_key = resolve_decision_log_key(ctx.sessions, key)
    writer = _decision_reader(ctx, session_key)

    if writer is None:
        return {
            "status": "error",
            "message": "Decision logging is disabled or not configured",
            "logs": [],
        }

    if not hasattr(writer, "get_recent_logs"):
        return {"status": "error", "message": "Log writer does not support reading", "logs": []}

    try:
        outcomes = (
            [item.strip() for item in outcome.split(",") if item.strip()] if outcome else None
        )
        logs = writer.get_recent_logs(
            session_key,
            lines=lines,
            outcomes=outcomes,
            kind=kind,
            since=since,
            until=until,
            regime=regime,
            signal=signal,
        )
        return {"status": "ok", "logs": logs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/paper/sessions/{key}/trades")
def get_paper_session_trades(
    ctx: Lab,
    key: str,
    limit: int = Query(20000, ge=1, le=200000, description="Decision records scanned"),
) -> dict[str, Any]:
    """Reconstructed trades (completed and open) for this session, without their bar rows.

    Works for both live paper sessions and research backtest runs: the decision log is the
    single source, so the same list appears for a backtest id and for a running session.

    `truncated` is the honest part. The reader walks the log newest-first and stops at
    `limit` records, so a window that hits the cap is missing the oldest trades — the list
    says so rather than presenting a truncated history as the whole run.
    """
    session_key, logs, truncated = _session_log_rows(ctx, key, limit)
    trades = _reconstruct(ctx, key, logs)
    return {
        "status": "ok",
        "session_id": session_key,
        "records": len(logs),
        "limit": limit,
        "truncated": truncated,
        "windows": _window_count(trades),
        "trades": [trade_summary(trade) for trade in trades],
    }


@router.get("/api/paper/sessions/{key}/trades/{trade_id}")
def get_paper_session_trade(
    ctx: Lab,
    key: str,
    trade_id: str,
    instrument_id: str | None = Query(None, description="Instrument to draw the chart for"),
    bar_interval: str | None = Query(None, description="Bar interval of that instrument"),
    catalog_path: str | None = Query(None, description="Parquet catalog to read bars from"),
    bars: int = Query(500, ge=0, le=5000, description="Chart bars to return; 0 = none"),
) -> dict[str, Any]:
    """One trade with everything the log holds about it (the dashboard's trade page).

    Same reconstruction as the list — a trade is not stored anywhere, so the id is resolved
    against the same window the list was built from. A trade older than that window is a
    404 with the count that *was* scanned, not an empty trade that looks like a flat trade.

    The chart bars come with the trade, from whichever source actually has them (see
    `_trade_chart`), so the page draws the candles the robot saw instead of guessing a
    catalog path in the browser and silently drawing no markers when they disagree.
    """
    session_key, logs, truncated = _session_log_rows(ctx, key, 20000)
    trades = _reconstruct(ctx, key, logs)
    trade = find_trade(trades, trade_id)
    if trade is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"no trade {trade_id!r} in the last {len(logs)} records of session "
                f"{session_key!r} ({len(trades)} trades reconstructed)"
                + ("; the window was truncated, so an older trade may exist" if truncated else "")
            ),
        )
    return {
        "status": "ok",
        "session_id": session_key,
        "records": len(logs),
        "truncated": truncated,
        "windows": _window_count(trades),
        "trade": trade,
        # Bars around the trade (steps + stop only), so the chart draws the indicators
        # leading into the entry and after the exit, not just while the trade was open.
        "context": _trade_context(logs, trade),
        "chart": _trade_chart(
            ctx,
            key,
            trade,
            instrument_id=instrument_id,
            bar_interval=bar_interval,
            catalog_path=catalog_path,
            limit=bars,
        ),
    }


def _trade_chart(
    ctx: LabContext,
    key: str,
    trade: dict[str, Any],
    *,
    instrument_id: str | None,
    bar_interval: str | None,
    catalog_path: str | None,
    limit: int,
) -> dict[str, Any]:
    """Candles around one trade, or an explanation of why there are none.

    Two sources, tried in this order, because they answer different questions:

    1. **the live session's own bars** — what the robot actually saw, available the moment
       the trade closes and without an ingest;
    2. **the parquet catalog** — the only source a backtest has, and it needs the
       instrument and interval the caller read off the run's config.

    A trade whose bars are in neither is answered with `source: "none"` and a note naming
    what is missing: an empty chart with no explanation is how "the catalog never held this
    window" gets read as "the trade had no price action".
    """
    if limit <= 0:
        return {"source": "none", "note": "Chart bars were not requested.", "bars": []}

    start, end = _trade_window(trade)
    manager = ctx.sessions.find(key)

    if manager is not None and manager.recent_bars:
        known = [bar for bar in manager.recent_bars if start <= bar.time <= end]
        if known:
            return {
                "source": "session",
                "instrument_id": manager.config.symbol,
                "bar_interval": manager.config.interval,
                "catalog_path": None,
                "note": "Bars streamed to this live paper session.",
                "bars": [
                    {
                        "time": bar.time,
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume,
                        "is_closed": bar.is_closed,
                    }
                    for bar in known[-limit:]
                ],
            }

    # The trade itself names the instrument it was taken on: a link that carries no context
    # (an archived history entry has `bar_interval: null`) still gets a chart attempt, and
    # the series check below refuses the wrong series rather than drawing it.
    instrument_id = instrument_id or _trade_instrument(trade)

    if instrument_id:
        from nautilus_lab.api.catalog_service import load_catalog_bars

        resolved_catalog = catalog_path or ctx.settings().catalog_path
        try:
            loaded = load_catalog_bars(
                instrument_id=instrument_id,
                catalog_path=resolved_catalog,
                bar_interval=bar_interval,
                start=datetime.fromtimestamp(start, UTC).isoformat(),
                end=datetime.fromtimestamp(end, UTC).isoformat(),
                limit=limit,
            )
        except Exception as exc:
            return {
                "source": "none",
                "instrument_id": instrument_id,
                "bar_interval": bar_interval,
                "catalog_path": catalog_path,
                "note": f"The catalog could not be read for {instrument_id}: {exc}",
                "bars": [],
            }
        interval = loaded["bar_interval"]
        if loaded["bars"]:
            mismatch = _series_mismatch(trade, loaded["bars"])
            if mismatch is None:
                return {
                    "source": "catalog",
                    "instrument_id": instrument_id,
                    "bar_interval": interval,
                    "catalog_path": loaded["catalog_path"],
                    "note": f"Bars from {loaded['catalog_path']} ({loaded['bar_type']}).",
                    "bars": loaded["bars"],
                }
            return {
                "source": "none",
                "instrument_id": instrument_id,
                "bar_interval": interval,
                "catalog_path": loaded["catalog_path"],
                "note": (
                    f"{loaded['catalog_path']} holds bars for {instrument_id}, but they are "
                    f"not the series this trade was taken on: {mismatch}. Drawing them would "
                    "put the entry marker on prices the run never saw."
                ),
                "bars": [],
            }
        return {
            "source": "none",
            "instrument_id": instrument_id,
            "bar_interval": interval,
            "catalog_path": loaded["catalog_path"],
            "note": (
                f"No {interval} bars for {instrument_id} in {loaded['catalog_path']} "
                "between the entry and the exit."
            ),
            "bars": [],
        }

    return {
        "source": "none",
        "instrument_id": instrument_id,
        "bar_interval": bar_interval,
        "catalog_path": catalog_path,
        "note": (
            "No live session holds these bars and the instrument/interval were not given, "
            "so there is nothing to draw."
        ),
        "bars": [],
    }


#: Bars drawn before the entry and after the exit, so the trade is not flush against the
#: chart edge. Twenty bars is enough to see the setup; more buries the trade itself.
TRADE_CHART_PAD_BARS = 20


def _trade_window(trade: dict[str, Any]) -> tuple[int, int]:
    """Unix-second window around one trade, padded by the trade's own bar spacing.

    The bar length is measured from the trade's decision timestamps rather than assumed:
    a 1m session and a 4h backtest need pads two orders of magnitude apart, and the log
    records exactly one close per bar, so consecutive timestamps *are* the interval.
    """
    stamps = sorted(
        int(dt.timestamp())
        for dt in (parse_ts(row.get("ts")) for row in trade.get("decisions") or ())
        if dt is not None
    )
    if not stamps:
        now = int(datetime.now(UTC).timestamp())
        return now - 3600, now

    diffs = [b - a for a, b in pairwise(stamps) if b > a]
    spacing = min(diffs) if diffs else 60
    pad = spacing * TRADE_CHART_PAD_BARS
    return stamps[0] - pad, stamps[-1] + pad


#: How far outside the bars' own high/low a trade's price may sit before the series is
#: called a different one. Small enough to catch another catalog, wide enough to survive a
#: rounded level or a bar the reader dropped at the window edge.
SERIES_PRICE_TOLERANCE = 0.02


def _series_mismatch(trade: dict[str, Any], bars: list[dict[str, Any]]) -> str | None:
    """Why these bars cannot be the ones this trade was taken on, or None if they can.

    Prices are the only cross-check available, and they are decisive: a run that entered at
    3832 cannot have traded bars whose whole range is 2280-2310. The instrument id does not
    tell them apart — every catalog of `ETH/USDT.SIM` is named the same — so without this
    check a wrong catalog path draws a confident chart under a trade it has nothing to do
    with. (Found by opening the page: the entry marker sat on a series 1500 dollars away.)
    """
    lows = [_to_float(bar.get("low")) for bar in bars]
    highs = [_to_float(bar.get("high")) for bar in bars]
    known_lows = [value for value in lows if value is not None]
    known_highs = [value for value in highs if value is not None]
    if not known_lows or not known_highs:
        return None
    low = min(known_lows) * (1 - SERIES_PRICE_TOLERANCE)
    high = max(known_highs) * (1 + SERIES_PRICE_TOLERANCE)

    for label, value in (
        ("entry", _to_float(trade.get("entry_price"))),
        ("exit", _to_float(trade.get("exit_price"))),
    ):
        if value is None or low <= value <= high:
            continue
        return (
            f"its {label} price {value:g} lies outside the bars' range "
            f"{min(known_lows):g} to {max(known_highs):g}"
        )
    return None


def _to_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float, str, Decimal)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None


def _trade_instrument(trade: dict[str, Any]) -> str | None:
    """The instrument the trade was taken on, as the log recorded it."""
    symbol = trade.get("symbol")
    if not isinstance(symbol, str) or not symbol or symbol == "UNKNOWN":
        return None
    return symbol


def _trade_context(
    logs: list[dict[str, Any]], trade: dict[str, Any], *, before: int = 60, after: int = 30
) -> list[dict[str, Any]]:
    """Up to `before` bar records ahead of the entry and `after` past the exit, slimmed."""
    bars = [row for row in logs if row.get("kind", "bar_decision") == "bar_decision"]
    entry = str(trade.get("entry_time") or "")
    exit_ = str(trade.get("exit_time") or "")
    if not bars or not entry:
        return []
    start = next((i for i, row in enumerate(bars) if str(row.get("ts", "")) >= entry), len(bars))
    end = len(bars)
    if exit_:
        end = next((i for i, row in enumerate(bars) if str(row.get("ts", "")) > exit_), len(bars))
    picked = bars[max(0, start - before) : start] + bars[end : end + after]
    return [
        {
            "ts": row.get("ts"),
            "close": row.get("close"),
            "steps": row.get("steps") or [],
            "states": row.get("states") or {},
        }
        for row in picked
    ]


def _window_count(trades: list[dict[str, Any]]) -> int:
    """How many passes over the same window the log holds (a walk-forward writes several).

    One file can hold every fold of a run under one session id, so the clock restarts
    mid-file. The list says how many passes it merged instead of showing the same window
    several times as if it were several windows of history.
    """
    return max((int(trade.get("window_index", 1)) for trade in trades), default=1)


def _session_log_rows(
    ctx: LabContext, key: str, limit: int
) -> tuple[str, list[dict[str, Any]], bool]:
    """The session's decision records, oldest first, and whether older ones were cut off."""
    session_key = resolve_decision_log_key(ctx.sessions, key)
    writer = _decision_reader(ctx, session_key)
    logs: list[dict[str, Any]] = []
    if writer is not None and hasattr(writer, "get_recent_logs"):
        try:
            logs = writer.get_recent_logs(session_key, lines=limit)
        except Exception:
            logs = []
    return session_key, logs, len(logs) >= limit


def _decision_reader(ctx: LabContext, session_key: str) -> Any:  # noqa: ANN401
    """The paper writer, or the batch cell holding `session_key` when the writer has none.

    A batch fold writes into `reports/batches/<id>/cells/<cell>/decisions/`, not into the
    paper decision directory, so its trades would 404 on this router without the fallback
    (and with decision logging off for paper, there is no paper writer at all).
    """
    writer = ctx.sessions.decision_log_writer
    has_rows = False
    if writer is not None and hasattr(writer, "get_recent_logs"):
        try:
            has_rows = bool(writer.get_recent_logs(session_key, lines=1))
        except Exception:
            has_rows = False
    if has_rows:
        return writer
    cell = find_session_cell(ctx.reports_dir, session_key)
    if cell is not None:
        return decision_reader(cell, ctx.settings())
    return writer


def _reconstruct(ctx: LabContext, key: str, logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rebuild trades from `logs`, attaching the fills of the live session when there is one."""
    manager = ctx.sessions.find(key)
    fills_data = None
    pos_data = None
    if manager is not None:
        fills_data = [
            {
                "id": f.id,
                "ts": f.ts,
                "symbol": f.symbol,
                "side": f.side,
                "qty": f.qty,
                "price": f.price,
                "fee": f.fee,
                "realized_pnl": f.realized_pnl,
                "reason": f.reason,
            }
            for f in manager.fills
        ]
        if manager.position is not None:
            pos_data = {
                "symbol": manager.position.symbol,
                "side": manager.position.side,
                "qty": manager.position.qty,
                "entry_price": manager.position.entry_price,
                "entry_time": manager.position.entry_time,
                "mark_price": manager.position.mark_price,
                "unrealized_pnl": manager.position.unrealized_pnl,
                "unrealized_pnl_pct": manager.position.unrealized_pnl_pct,
                "stop_loss": manager.position.stop_loss,
                "take_profit": manager.position.take_profit,
            }
    return reconstruct_trades_from_decisions(logs, fills=fills_data, active_position=pos_data)


@router.post("/api/paper/sessions/{key}/pause")
async def pause_paper_session(ctx: Lab, key: str) -> dict[str, Any]:
    manager = await _set_paused(ctx, key, True)
    return {"status": "paused", "message": f"Paused entries of {manager.config.name}"}


@router.post("/api/paper/sessions/{key}/resume")
async def resume_paper_session(ctx: Lab, key: str) -> dict[str, Any]:
    manager = await _set_paused(ctx, key, False)
    return {"status": "active", "message": f"Resumed entries of {manager.config.name}"}


@router.post("/api/paper/sessions/{key}/close-position")
async def close_paper_session_position(ctx: Lab, key: str) -> dict[str, Any]:
    return await _close_position(_session_or_404(ctx, key))


@router.post("/api/paper/sessions/{key}/update-stops")
async def update_paper_session_stops(
    ctx: Lab, key: str, req: PaperLiveStopsUpdateRequest
) -> dict[str, Any]:
    return await _update_stops(_session_or_404(ctx, key), req)


# ---- one-session endpoints, kept for older dashboards: act on the primary session ---
@router.get("/api/paper/live/state")
def get_paper_live_state(ctx: Lab) -> dict[str, Any]:
    manager = ctx.sessions.primary()
    return _idle_state(ctx) if manager is None else manager.to_state_dict()


@router.post("/api/paper/live/start")
async def start_paper_live(ctx: Lab, req: PaperLiveStartRequest) -> dict[str, Any]:
    manager = await _create_session(ctx, req)
    return {
        "status": "started",
        "session_id": manager.session_id,
        "message": f"Started live paper session for {req.symbol}",
    }


@router.post("/api/paper/live/stop")
async def stop_paper_live(ctx: Lab) -> dict[str, Any]:
    await _primary_or_400(ctx).stop()
    return {"status": "stopped", "message": "Live paper session stopped"}


@router.post("/api/paper/live/close-position")
async def close_paper_live_position(ctx: Lab) -> dict[str, Any]:
    return await _close_position(_primary_or_400(ctx))


@router.post("/api/paper/live/update-stops")
async def update_paper_live_stops(ctx: Lab, req: PaperLiveStopsUpdateRequest) -> dict[str, Any]:
    return await _update_stops(_primary_or_400(ctx), req)


@router.websocket("/api/paper/live-stream")
async def paper_live_stream_ws(websocket: WebSocket) -> None:
    """State + bars of one session: `?session=<id or name>`, else the primary session."""
    # HTTP middleware never sees a WebSocket handshake, and CORS does not apply to one,
    # so the same gate runs here. Browsers cannot set headers on a WebSocket: the token
    # travels as `?token=`.
    ctx: LabContext = websocket.app.state.lab
    reason = ctx.security.refusal(
        method="GET",
        path=websocket.url.path,
        origin=websocket.headers.get("origin"),
        presented_token=websocket.query_params.get("token"),
    )
    if reason is not None:
        await websocket.close(code=1008, reason=reason)
        return
    await websocket.accept()
    key = websocket.query_params.get("session")
    manager = ctx.sessions.find(key) if key else ctx.sessions.primary()
    if manager is not None:
        manager.subscribers.add(websocket)
    try:
        state = _idle_state(ctx) if manager is None else manager.to_state_dict()
        await websocket.send_text(json.dumps({"type": "INIT_STATE", "data": state}))
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if manager is not None:
            manager.subscribers.discard(websocket)
