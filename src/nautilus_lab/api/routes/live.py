"""The live paper terminal: sessions on real Binance bars, simulated fills, WebSocket feed.

Only the paper venue exists; nothing here can reach an exchange order endpoint.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from nautilus_lab.api.context import Lab, LabContext
from nautilus_lab.api.live_paper_boot import live_config_from_settings
from nautilus_lab.api.paper_streamer import LivePaperSessionManager
from nautilus_lab.api.requests import PaperLiveStartRequest, PaperLiveStopsUpdateRequest

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
    ctx: Lab, key: str, lines: int = Query(100, ge=1, le=1000)
) -> dict[str, Any]:
    manager = _session_or_404(ctx, key)
    writer = ctx.sessions.decision_log_writer

    if writer is None:
        return {
            "status": "error",
            "message": "Decision logging is disabled or not configured",
            "logs": [],
        }

    if not hasattr(writer, "get_recent_logs"):
        return {"status": "error", "message": "Log writer does not support reading", "logs": []}

    try:
        logs = writer.get_recent_logs(manager.config.name, lines=lines)
        return {"status": "ok", "logs": logs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


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
