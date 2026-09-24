"""Wiring of the live paper terminal to Settings: configuration, journal, start-up.

Kept out of `app.py` so it can be tested without an ASGI app and so the endpoint and
the start-up hook build a session the same way — a session started by hand and one
started by `LIVE_PAPER_AUTOSTART` must not trade two different rulebooks.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path

from nautilus_lab.api.paper_streamer import LivePaperConfig, LivePaperSessionManager
from nautilus_lab.infrastructure.live_paper_journal import LivePaperJournal
from nautilus_lab.infrastructure.settings import Settings

logger = logging.getLogger(__name__)


def live_config_from_settings(
    cfg: Settings,
    *,
    symbol: str,
    interval: str,
    robot: str,
    starting_equity: Decimal,
    risk_per_trade: Decimal,
    stop_pct: Decimal,
    take_profit_multiple: Decimal,
    mode: str = "paper",
    auto_trade: bool = True,
) -> LivePaperConfig:
    """Robot parameters, fees and breakers from the same Settings research runs use."""
    fees = cfg.fee_schedule()
    return LivePaperConfig(
        symbol=symbol.upper(),
        interval=interval,
        robot=robot,
        starting_equity=starting_equity,
        risk_per_trade=risk_per_trade,
        stop_pct=stop_pct,
        take_profit_multiple=take_profit_multiple,
        mode=mode,
        auto_trade=auto_trade,
        maker_fee=fees.maker,
        taker_fee=fees.taker,
        fast_ema=cfg.fast_ema,
        slow_ema=cfg.slow_ema,
        regime=cfg.regime_params(),
        adaptive=cfg.adaptive_ema_params(),
        max_daily_loss=cfg.max_daily_loss,
        max_drawdown=cfg.max_drawdown,
    )


def autostart_config(cfg: Settings) -> LivePaperConfig | None:
    """The session `LIVE_PAPER_AUTOSTART=true` asks for, or None when it is off."""
    if not cfg.live_paper_autostart:
        return None
    return live_config_from_settings(
        cfg,
        symbol=cfg.live_paper_symbol,
        interval=cfg.live_paper_interval,
        robot=cfg.live_paper_robot,
        starting_equity=cfg.live_paper_starting_equity,
        risk_per_trade=cfg.risk_per_trade,
        stop_pct=cfg.stop_pct,
        take_profit_multiple=cfg.live_paper_take_profit_multiple,
    )


def journal_from_settings(cfg: Settings, *, root: Path) -> LivePaperJournal | None:
    """Relative paths are resolved against the project root, like `reports/`."""
    raw = cfg.live_paper_journal.strip()
    if not raw:
        return None
    path = Path(raw)
    return LivePaperJournal(path if path.is_absolute() else root / path)


async def boot_live_paper(
    manager: LivePaperSessionManager, *, autostart: LivePaperConfig | None
) -> str:
    """Resume the unfinished session if the journal has one, else autostart, else idle.

    Resume wins over autostart on purpose: a restart must continue the running ledger,
    not open a second one next to it. Returns what happened, for the log.
    """
    journal = manager.journal
    session = journal.load_resumable() if journal is not None else None
    if session is not None:
        try:
            await manager.resume(session)
        except ValueError as exc:
            logger.error("Cannot resume live paper session %s: %s", session.session_id, exc)
            manager.status_message = f"Resume failed: {exc}"
            return "resume_failed"
        return "resumed"
    if autostart is not None:
        await manager.start(autostart)
        return "started"
    return "idle"
