"""Wiring of the live paper terminal to Settings: configuration, journal, start-up.

Kept out of `app.py` so it can be tested without an ASGI app and so the endpoint and
the start-up hook build a session the same way — a session started by hand and one
started by `LIVE_PAPER_AUTOSTART` must not trade two different rulebooks.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path

from nautilus_lab.api.live_sessions import SessionRegistry
from nautilus_lab.api.market_feed import FeedHub
from nautilus_lab.api.paper_streamer import (
    LIVE_PAPER_ROBOTS,
    HistoryLoader,
    LivePaperConfig,
    LivePaperSessionManager,
    default_session_name,
)
from nautilus_lab.infrastructure.live_paper_journal import LivePaperJournal
from nautilus_lab.infrastructure.settings import Settings
from nautilus_lab.infrastructure.decision_log_writer import JsonlDecisionLogWriter

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
    name: str = "",
    notes: str = "",
    created_from: str = "ui",
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
        name=name.strip(),
        notes=notes,
        created_from=created_from,
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
        name=default_session_name(
            cfg.live_paper_robot, cfg.live_paper_symbol, cfg.live_paper_interval
        ),
        created_from="autostart",
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


# --------------------------------------------------------------------------- portfolio
_PORTFOLIO_FIELDS = {
    "name",
    "robot",
    "symbol",
    "interval",
    "starting_equity",
    "risk_per_trade",
    "stop_pct",
    "take_profit_multiple",
    "notes",
    "auto_trade",
}


def _resolve(path: str, root: Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else root / candidate


def parse_portfolio(raw: object, cfg: Settings) -> list[LivePaperConfig]:
    """Sessions declared in a portfolio file. Raises ValueError naming what is wrong.

    Unknown keys are refused rather than ignored: a typo such as `risk_per_trad` would
    otherwise silently trade with the default and the ledger would lie about it.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("sessions"), list):
        raise ValueError("portfolio file must have a top-level `sessions:` list")
    defaults = raw.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ValueError("`defaults:` must be a mapping")
    configs: list[LivePaperConfig] = []
    names: set[str] = set()
    for index, entry in enumerate(raw["sessions"]):
        if not isinstance(entry, dict):
            raise ValueError(f"sessions[{index}] must be a mapping")
        merged = {**defaults, **entry}
        unknown = set(merged) - _PORTFOLIO_FIELDS
        if unknown:
            raise ValueError(f"sessions[{index}]: unknown keys {sorted(unknown)}")
        name = str(merged.get("name") or "").strip()
        if not name:
            raise ValueError(f"sessions[{index}]: `name` is required")
        if name in names:
            raise ValueError(f"duplicate session name {name!r}")
        names.add(name)
        robot = str(merged.get("robot") or "")
        if robot not in LIVE_PAPER_ROBOTS:
            known = ", ".join(sorted(LIVE_PAPER_ROBOTS))
            raise ValueError(f"{name}: robot {robot!r} is not available live ({known})")
        configs.append(
            live_config_from_settings(
                cfg,
                symbol=str(merged.get("symbol") or cfg.live_paper_symbol),
                interval=str(merged.get("interval") or cfg.live_paper_interval),
                robot=robot,
                starting_equity=Decimal(
                    str(merged.get("starting_equity", cfg.live_paper_starting_equity))
                ),
                risk_per_trade=Decimal(str(merged.get("risk_per_trade", cfg.risk_per_trade))),
                stop_pct=Decimal(str(merged.get("stop_pct", cfg.stop_pct))),
                take_profit_multiple=Decimal(
                    str(merged.get("take_profit_multiple", cfg.live_paper_take_profit_multiple))
                ),
                auto_trade=bool(merged.get("auto_trade", True)),
                name=name,
                notes=str(merged.get("notes") or ""),
                created_from="portfolio",
            )
        )
    return configs


def load_portfolio(cfg: Settings, *, root: Path) -> list[LivePaperConfig]:
    """Declared sessions: the portfolio file, else the single autostart session, else none."""
    if cfg.live_paper_portfolio.strip():
        import yaml

        path = _resolve(cfg.live_paper_portfolio.strip(), root)
        with path.open(encoding="utf-8") as handle:
            return parse_portfolio(yaml.safe_load(handle), cfg)
    single = autostart_config(cfg)
    return [] if single is None else [single]


def sessions_dir_from_settings(cfg: Settings, *, root: Path) -> Path | None:
    if cfg.live_paper_sessions_dir.strip():
        return _resolve(cfg.live_paper_sessions_dir.strip(), root)
    legacy = journal_from_settings(cfg, root=root)
    return None if legacy is None else legacy.path.parent / "sessions"


def _unwritable(directory: Path) -> str | None:
    """None when `directory` would accept a journal file, else why it would not.

    The probe is a real file, not ``os.access``: a read-only mount, a wrong owner and a
    full disk all answer "no" to an actual write and only some of them answer "no" to a
    permission check.
    """
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return f"{directory} cannot be created: {exc}"
    probe = directory / ".journal_write_probe"
    try:
        with probe.open("w", encoding="utf-8") as handle:
            handle.write("")
        probe.unlink()
    except OSError as exc:
        return f"{directory} is not writable: {exc}"
    return None


def journal_write_problems(cfg: Settings, *, root: Path) -> list[str]:
    """Every configured journal directory that refuses a write, with the reason.

    Empty when no journal is configured — in-memory is a legitimate mode, the mode of a
    workstation that is only watching — or when each directory takes a file. A deeper
    directory is skipped once its parent is already reported: the cause is the parent.
    """
    targets: list[Path] = []
    legacy = journal_from_settings(cfg, root=root)
    if legacy is not None:
        targets.append(legacy.path.parent)
    sessions_dir = sessions_dir_from_settings(cfg, root=root)
    if sessions_dir is not None:
        targets.append(sessions_dir)
    problems: list[str] = []
    refused: list[Path] = []
    for target in sorted(dict.fromkeys(targets), key=lambda path: len(path.parts)):
        if any(target.is_relative_to(parent) for parent in refused):
            continue
        problem = _unwritable(target)
        if problem is not None:
            problems.append(problem)
            refused.append(target)
    return problems


def ensure_journal_writable(cfg: Settings, *, root: Path) -> None:
    """Refuse to start when a configured journal cannot be written. Raises RuntimeError.

    A paper terminal without its ledger is not a degraded paper terminal: every session
    would run in memory, the dashboard would look healthy, and the artifact this server
    exists to produce would be empty. So this is a startup failure (fail closed, like
    `lab live`), not an error logged once per closed bar.
    """
    problems = journal_write_problems(cfg, root=root)
    if problems:
        raise RuntimeError(
            "live paper journal is not writable: "
            + "; ".join(problems)
            + ". Fix the owner/mount of that directory (docs/26-deploy-vps.md), or leave "
            "LIVE_PAPER_JOURNAL and LIVE_PAPER_SESSIONS_DIR unset to run in memory on purpose."
        )


def registry_from_settings(
    cfg: Settings,
    *,
    root: Path,
    history_loader: HistoryLoader | None,
    feed_hub: FeedHub | None = None,
) -> SessionRegistry:
    legacy = journal_from_settings(cfg, root=root)
    
    decision_log_writer = None
    if cfg.decision_log_enabled:
        decision_log_writer = JsonlDecisionLogWriter(cfg, root=root)
        
    return SessionRegistry(
        sessions_dir=sessions_dir_from_settings(cfg, root=root),
        legacy_journal=None if legacy is None else legacy.path,
        history_loader=history_loader,
        feed_hub=feed_hub if feed_hub is not None else FeedHub(max_feeds=cfg.live_paper_max_feeds),
        decision_log_writer=decision_log_writer,
        max_sessions=cfg.live_paper_max_sessions,
    )


async def boot_sessions(registry: SessionRegistry, cfg: Settings, *, root: Path) -> list[str]:
    """Resume what was running, then bring up the declared portfolio. One line per session."""
    outcomes = await registry.restore()
    try:
        portfolio = load_portfolio(cfg, root=root)
    except (OSError, ValueError) as exc:
        logger.error("Live paper portfolio not loaded: %s", exc)
        return [*outcomes, f"portfolio error: {exc}"]
    outcomes.extend(await registry.reconcile(portfolio))
    return outcomes or ["idle"]
