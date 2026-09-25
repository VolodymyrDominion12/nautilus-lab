"""Several live paper sessions in one process: one robot, one account, one journal each.

Each session keeps its own virtual account and breakers on purpose. At this stage every
robot is a separate hypothesis; if they shared a balance, a loss in one would block the
others' entries and neither result would mean anything. The portfolio view below only
*reads* the sessions (total equity, exposure per symbol, distance to the buy-and-hold
benchmark); it never gates an order.

Persistence: one journal file per session in `sessions_dir` (`<session_id>.jsonl`).
On start the registry resumes every session whose journal has no `session_stop`, then
reconciles the declared portfolio (`deploy/paper_portfolio.yaml`) by session *name*:

* a declared name that is running -> left alone (a changed config is reported, not
  applied: new parameters are a new session under a new name);
* a declared name that a person stopped -> not restarted;
* a declared name never seen -> started.

The single-file journal of the one-session version (`LIVE_PAPER_JOURNAL`) is read as
one more journal, so the session running before the upgrade is resumed, not lost.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from nautilus_lab.api.market_feed import FeedHub
from nautilus_lab.api.paper_streamer import (
    HistoryLoader,
    LivePaperConfig,
    LivePaperSessionManager,
    default_session_name,
)
from nautilus_lab.domain.buy_and_hold import HOLD_ROBOT
from nautilus_lab.domain.ports import DecisionLogPort
from nautilus_lab.infrastructure.live_paper_journal import (
    LivePaperJournal,
    ResumableSession,
    SessionRecord,
)

logger = logging.getLogger(__name__)

DEFAULT_MAX_SESSIONS = 8


def _record_name(record: SessionRecord) -> str:
    cfg = record.config
    return record.name or default_session_name(
        str(cfg.get("robot", "")), str(cfg.get("symbol", "")), str(cfg.get("interval", ""))
    )


def _max_drawdown_pct(equities: list[float]) -> float:
    peak = float("-inf")
    worst = 0.0
    for value in equities:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak)
    return round(worst * 100, 2)


def _pct(numerator: float, denominator: float) -> float | None:
    return None if denominator <= 0 else round((numerator / denominator - 1) * 100, 3)


class SessionRegistry:
    def __init__(
        self,
        *,
        sessions_dir: Path | None,
        legacy_journal: Path | None = None,
        history_loader: HistoryLoader | None = None,
        feed_hub: FeedHub | None = None,
        decision_log_writer: DecisionLogPort | None = None,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
    ) -> None:
        self.sessions_dir = sessions_dir
        self.legacy_journal = legacy_journal
        self.history_loader = history_loader
        self.feed_hub = feed_hub
        self.decision_log_writer = decision_log_writer
        self.max_sessions = max_sessions
        #: Sessions this process has run, in start order (stopped ones stay until restart).
        self.sessions: dict[str, LivePaperSessionManager] = {}

    # ------------------------------------------------------------------ lookup
    @property
    def persisted(self) -> bool:
        return self.sessions_dir is not None

    def active(self) -> list[LivePaperSessionManager]:
        return [m for m in self.sessions.values() if m.is_active]

    def find(self, key: str) -> LivePaperSessionManager | None:
        """By session id, else by name (the running one first, then the latest)."""
        if key in self.sessions:
            return self.sessions[key]
        named = [m for m in self.sessions.values() if m.config.name == key]
        running = [m for m in named if m.is_active]
        if running:
            return running[0]
        return named[-1] if named else None

    def primary(self) -> LivePaperSessionManager | None:
        """The session the one-session endpoints (`/api/paper/live/*`) act on."""
        active = self.active()
        if active:
            return active[0]
        return list(self.sessions.values())[-1] if self.sessions else None

    def journal_files(self) -> list[Path]:
        files: list[Path] = []
        if self.legacy_journal is not None and self.legacy_journal.is_file():
            files.append(self.legacy_journal)
        if self.sessions_dir is not None and self.sessions_dir.is_dir():
            files.extend(sorted(self.sessions_dir.glob("*.jsonl")))
        return files

    def history(self) -> list[SessionRecord]:
        records: list[SessionRecord] = []
        for path in self.journal_files():
            records.extend(LivePaperJournal(path).sessions())
        return sorted(records, key=lambda r: r.started_at)

    # ------------------------------------------------------------------ lifecycle
    def _manager(self, journal: LivePaperJournal | None) -> LivePaperSessionManager:
        return LivePaperSessionManager(
            history_loader=self.history_loader,
            journal=journal,
            feed_hub=self.feed_hub,
            decision_log=self.decision_log_writer,
        )

    async def create(self, config: LivePaperConfig) -> LivePaperSessionManager:
        """Start a new session. Raises ValueError with a reason a person can act on."""
        name = config.name.strip() or default_session_name(
            config.robot, config.symbol, config.interval
        )
        config = replace(config, name=name, symbol=config.symbol.upper())
        if any(m.config.name == name for m in self.active()):
            raise ValueError(f"a session named {name!r} is already running; pick another name")
        if len(self.active()) >= self.max_sessions:
            raise ValueError(
                f"at most {self.max_sessions} sessions at once (LIVE_PAPER_MAX_SESSIONS)"
            )
        # Count markets of running sessions, not open sockets: a session joins its feed
        # only after its warm-up, so the hub alone would let a burst of starts overshoot.
        markets = {(m.config.symbol.upper(), m.config.interval) for m in self.active()}
        wanted = (config.symbol, config.interval)
        if (
            self.feed_hub is not None
            and wanted not in markets
            and len(markets) >= self.feed_hub.max_feeds
        ):
            raise ValueError(
                f"at most {self.feed_hub.max_feeds} different symbol+interval markets at once"
            )
        session_id = f"{name}-{uuid.uuid4().hex[:6]}"
        journal = (
            LivePaperJournal(self.sessions_dir / f"{session_id}.jsonl")
            if self.sessions_dir is not None
            else None
        )
        manager = self._manager(journal)
        await manager.start(config, session_id=session_id)
        self.sessions[session_id] = manager
        return manager

    async def stop(self, key: str) -> LivePaperSessionManager:
        manager = self._require(key)
        await manager.stop()
        return manager

    async def set_paused(self, key: str, paused: bool) -> LivePaperSessionManager:
        manager = self._require(key)
        if not manager.is_active:
            raise ValueError(f"session {key!r} is not running")
        manager.paused = paused
        manager.status_message = (
            "Paused: no new entries (exits and stops still run)" if paused else "Resumed entries"
        )
        manager._journal_snapshot()
        await manager.broadcast_state()
        return manager

    def _require(self, key: str) -> LivePaperSessionManager:
        manager = self.find(key)
        if manager is None:
            raise KeyError(key)
        return manager

    async def restore(self) -> list[str]:
        """Resume every session a person did not stop. Returns one line per session."""
        outcomes: list[str] = []
        for path in self.journal_files():
            resumable = LivePaperJournal(path).load_resumable()
            if resumable is None or resumable.session_id in self.sessions:
                continue
            outcomes.append(await self._resume(path, resumable))
        return outcomes

    async def _resume(self, path: Path, resumable: ResumableSession) -> str:
        config = dict(resumable.config)
        if not config.get("name"):
            # Sessions from before names existed get the name the portfolio would use,
            # so the declared `regime-eth` recognises the one already running.
            config["name"] = default_session_name(
                str(config.get("robot", "")),
                str(config.get("symbol", "")),
                str(config.get("interval", "")),
            )
        resumable = replace(resumable, config=config)
        manager = self._manager(LivePaperJournal(path))
        try:
            await manager.resume(resumable)
        except ValueError as exc:
            logger.error("Cannot resume live paper session %s: %s", resumable.session_id, exc)
            return f"resume_failed {resumable.session_id}: {exc}"
        self.sessions[resumable.session_id] = manager
        return f"resumed {config['name']} ({resumable.session_id})"

    async def reconcile(self, portfolio: list[LivePaperConfig]) -> list[str]:
        """Bring the declared portfolio up, without ever restarting a stopped session."""
        outcomes: list[str] = []
        history = self.history()
        for wanted in portfolio:
            name = wanted.name
            running = [m for m in self.active() if m.config.name == name]
            if running:
                current = running[0].config
                declared = (wanted.robot, wanted.symbol.upper(), wanted.interval)
                actual = (current.robot, current.symbol.upper(), current.interval)
                if declared != actual:
                    outcomes.append(
                        f"kept {name}: running {actual} differs from the file {declared}; "
                        "new parameters need a new name"
                    )
                else:
                    outcomes.append(f"running {name}")
                continue
            past = [r for r in history if _record_name(r) == name]
            if past and past[-1].stopped:
                outcomes.append(f"skipped {name}: stopped by a person; rename it to start again")
                continue
            if past and not past[-1].stopped:
                outcomes.append(f"skipped {name}: journal is unfinished but could not be resumed")
                continue
            try:
                manager = await self.create(wanted)
            except ValueError as exc:
                outcomes.append(f"failed {name}: {exc}")
                continue
            outcomes.append(f"started {name} ({manager.session_id})")
        return outcomes

    # ------------------------------------------------------------------ views
    def _row(self, manager: LivePaperSessionManager) -> dict[str, Any]:
        cfg = manager.config
        start = float(manager.starting_equity)
        equity = float(manager.current_equity)
        equities = [p.equity for p in manager.equity_history]
        closed = [f for f in manager.fills if not f.reason.startswith("Open ")]
        wins = sum(1 for f in closed if Decimal(f.realized_pnl) > 0)
        status = "stopped"
        if manager.is_active:
            status = "paused" if manager.paused else "active"
        return {
            "session_id": manager.session_id,
            "name": cfg.name,
            "robot": cfg.robot,
            "symbol": cfg.symbol,
            "interval": cfg.interval,
            "status": status,
            "notes": cfg.notes,
            "created_from": cfg.created_from,
            "started_at": manager.started_at,
            "resumed_at": manager.resumed_at,
            "starting_equity": str(manager.starting_equity),
            "equity": str(manager.current_equity),
            "return_pct": _pct(equity, start),
            "vs_benchmark_pp": None,
            "position": None if manager.position is None else manager.position.side,
            "unrealized_pnl": str(manager.unrealized_pnl),
            "fees_paid": str(manager.fees_paid),
            "fills": len(manager.fills),
            "closed_trades": len(closed),
            "wins": wins,
            "max_drawdown_pct": _max_drawdown_pct(equities),
            "last_bar_ts": manager.to_state_dict()["last_bar_ts"],
            "risk_refusals": sum(manager.risk_refusals.values()),
            "status_message": manager.status_message,
            "persisted": manager.journal is not None,
        }

    def summaries(self, *, history_limit: int = 20) -> list[dict[str, Any]]:
        rows = [self._row(m) for m in self.sessions.values()]
        benchmarks = {
            (r["symbol"], r["interval"]): r["return_pct"]
            for r in rows
            if r["robot"] == HOLD_ROBOT and r["status"] != "stopped"
        }
        for row in rows:
            bench = benchmarks.get((row["symbol"], row["interval"]))
            if row["robot"] != HOLD_ROBOT and bench is not None and row["return_pct"] is not None:
                row["vs_benchmark_pp"] = round(row["return_pct"] - bench, 3)
        known = {r["session_id"] for r in rows}
        past: list[dict[str, Any]] = []
        for record in reversed(self.history()):
            if record.session_id in known or not record.stopped:
                continue
            snap = record.last_snapshot or {}
            start = float(record.config.get("starting_equity") or 0)
            equity = float(snap.get("equity") or start or 0)
            past.append(
                {
                    "session_id": record.session_id,
                    "name": _record_name(record),
                    "robot": record.config.get("robot"),
                    "symbol": record.config.get("symbol"),
                    "interval": record.config.get("interval"),
                    "status": "stopped",
                    "notes": record.config.get("notes", ""),
                    "started_at": record.started_at,
                    "stopped_at": record.stopped_at,
                    "starting_equity": str(record.config.get("starting_equity")),
                    "equity": str(snap.get("equity", "")),
                    "return_pct": _pct(equity, start),
                    "fills": record.fill_count,
                    "history_only": True,
                }
            )
            if len(past) >= history_limit:
                break
        return rows + past

    def portfolio(self) -> dict[str, Any]:
        live = [m for m in self.active()]
        start = sum(float(m.starting_equity) for m in live)
        equity = sum(float(m.current_equity) for m in live)
        exposure: dict[str, dict[str, int]] = {}
        for m in live:
            if m.config.robot == HOLD_ROBOT:
                continue  # the benchmark is always long; counting it hides the robots' view
            side = "flat" if m.position is None else m.position.side.lower()
            bucket = exposure.setdefault(m.config.symbol, {"long": 0, "short": 0, "flat": 0})
            bucket[side] += 1
        warnings = [
            f"all {sum(b.values())} robots on {symbol} are {side}"
            for symbol, b in exposure.items()
            for side in ("long", "short")
            if sum(b.values()) > 1 and b[side] == sum(b.values())
        ]
        return {
            "sessions_active": sum(1 for m in live if not m.paused),
            "sessions_paused": sum(1 for m in live if m.paused),
            "starting_equity": round(start, 2),
            "equity": round(equity, 2),
            "return_pct": _pct(equity, start),
            "exposure": exposure,
            "warnings": warnings,
            "feeds": [] if self.feed_hub is None else self.feed_hub.status(),
            "persisted": self.persisted,
            "max_sessions": self.max_sessions,
        }
