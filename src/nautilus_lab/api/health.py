"""Is the paper server alive, is it *working*, and who hears about it when it is not.

`/healthz` only says the process answers. That is what the old Docker check proved, and
it stays green while a Binance socket is "connected" and delivers nothing, or while
every journal write fails on a full disk — the two failures that silently turn an
8-week paper run into a hole (docs/27 E-1.5, E-1.6). So:

* **readiness** (`/readyz`, the Docker health check) judges every open market feed by
  the age of its last message and of its last *closed* bar, and every running session
  by whether its latest journal write succeeded;
* the **watchdog** re-evaluates readiness on a timer and sends a message when a problem
  appears and again when it clears — transitions, not repeats, so a long Binance outage
  is two messages, not two hundred;
* the **heartbeat** pings an external URL while the server is ready (a push-style
  dead-man's switch: healthchecks.io, Uptime Kuma "push", Cronitor). When the pings
  stop — VPS down, process dead, network gone, or the server not ready — the *outside*
  service raises the alarm; nothing inside a dead machine can (docs/27 E-1.7);
* **metrics** (`/api/metrics`) expose the same numbers in the Prometheus text format for
  anyone who scrapes; nothing here depends on a Prometheus library.

Everything below is plain functions over plain values (feed status dicts, session
objects, a clock), so it is tested without sockets, threads or a running API.
"""

from __future__ import annotations

import asyncio
import logging
import time
import urllib.request
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from nautilus_lab.api.paper_streamer import INTERVAL_SECONDS
from nautilus_lab.domain.provenance import RunManifest
from nautilus_lab.infrastructure.alerts import AlertNotifier

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HealthLimits:
    """How long silence may last before it is a problem."""

    #: No message at all for this long = the socket is dead even if "connected".
    #: Binance pushes kline updates every ~2 s while the market trades.
    message_timeout_seconds: float = 90.0
    #: Closed bars may arrive this late after the interval ends (exchange lag, reconnects).
    closed_bar_slack_seconds: float = 180.0
    #: A freshly started feed gets this long to deliver its first message.
    startup_grace_seconds: float = 120.0


class SessionLike(Protocol):
    """What the checks read from a live paper session (LivePaperSessionManager)."""

    @property
    def session_id(self) -> str | None: ...
    @property
    def is_active(self) -> bool: ...
    @property
    def journal_failing(self) -> bool: ...
    @property
    def journal_errors(self) -> int: ...


@dataclass(frozen=True, slots=True)
class Readiness:
    ready: bool
    problems: tuple[str, ...]
    feeds: tuple[dict[str, Any], ...] = ()
    sessions_active: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "ready" if self.ready else "not_ready",
            "problems": list(self.problems),
            "feeds": list(self.feeds),
            "sessions_active": self.sessions_active,
        }


def feed_problem(status: Mapping[str, Any], *, now: float, limits: HealthLimits) -> str | None:
    """Why one feed is not delivering, or None when it is."""
    name = f"feed {status.get('symbol')} {status.get('interval')}"
    started = _number(status.get("started_at"))
    last_message = _number(status.get("last_message_at"))
    last_closed = _number(status.get("last_closed_at"))

    if last_message is None:
        if started is not None and now - started > limits.startup_grace_seconds:
            return f"{name}: no message since start {now - started:.0f}s ago"
        return None
    silence = now - last_message
    if silence > limits.message_timeout_seconds:
        return f"{name}: no message for {silence:.0f}s"

    interval = INTERVAL_SECONDS.get(str(status.get("interval")))
    if interval is None:
        return None
    allowed = interval + limits.closed_bar_slack_seconds
    reference = last_closed if last_closed is not None else started
    if reference is not None and now - reference > allowed:
        what = "last closed bar" if last_closed is not None else "no closed bar since start"
        return f"{name}: {what} {now - reference:.0f}s ago (interval {interval}s)"
    return None


def session_problem(session: SessionLike) -> str | None:
    if session.is_active and session.journal_failing:
        return (
            f"session {session.session_id}: journal write failing "
            f"({session.journal_errors} failed writes) - the ledger has a hole"
        )
    return None


def check_readiness(
    feeds: Sequence[Mapping[str, Any]],
    sessions: Iterable[SessionLike],
    *,
    now: float,
    limits: HealthLimits,
) -> Readiness:
    """Ready = every open feed delivers and every running session can write its ledger.

    No feeds and no sessions is ready: an idle server is not a broken one.
    """
    problems: list[str] = []
    annotated: list[dict[str, Any]] = []
    for status in feeds:
        problem = feed_problem(status, now=now, limits=limits)
        annotated.append({**status, **_ages(status, now), "problem": problem})
        if problem is not None:
            problems.append(problem)
    active = [s for s in sessions if s.is_active]
    for session in active:
        problem = session_problem(session)
        if problem is not None:
            problems.append(problem)
    return Readiness(
        ready=not problems,
        problems=tuple(problems),
        feeds=tuple(annotated),
        sessions_active=len(active),
    )


# ------------------------------------------------------------------ watchdog


@dataclass(slots=True)
class Watchdog:
    """Turns successive readiness checks into alert messages on change only."""

    #: Problems are keyed by subject + kind of failure without numbers, so a growing
    #: "no message for 95s" -> "for 125s" is one ongoing problem, not a new one each time.
    known: set[str] = field(default_factory=set)
    subjects: dict[str, str] = field(default_factory=dict)

    def transitions(self, readiness: Readiness) -> list[tuple[str, str]]:
        """(level, message) for problems that appeared and problems that cleared."""
        current = {_problem_key(p): p for p in readiness.problems}
        messages: list[tuple[str, str]] = []
        for key, text in current.items():
            if key not in self.known:
                messages.append(("WARNING", f"live paper problem: {text}"))
        for key in sorted(self.known - current.keys()):
            messages.append(("INFO", f"live paper recovered: {self.subjects.get(key, key)}"))
        self.known = set(current)
        self.subjects = {key: _subject(text) for key, text in current.items()}
        return messages

    #: Breaker refusals per (session, reason) as last seen; None until the first look,
    #: which only records: sessions resumed after a restart carry old counts.
    breakers: dict[tuple[str, str], int] | None = None

    def breaker_trips(self, sessions: Iterable[Any]) -> list[tuple[str, str]]:
        """A message when a circuit breaker starts refusing entries in a session.

        A tripped breaker refuses on every following bar; only the first refusal after
        the counter was zero (a new trip, or a trip after a reset) is worth a message.
        """
        current: dict[tuple[str, str], int] = {}
        names: dict[str, str] = {}
        for session in sessions:
            if not getattr(session, "is_active", False):
                continue
            sid = str(session.session_id)
            names[sid] = str(getattr(session.config, "name", "") or sid)
            for reason, count in dict(getattr(session, "risk_refusals", {}) or {}).items():
                if "circuit breaker" in str(reason):
                    current[(sid, str(reason))] = int(count)
        previous = self.breakers
        self.breakers = current
        if previous is None:
            return []
        return [
            (
                "WARNING",
                f"live paper session {names[sid]}: {reason} tripped, new entries refused",
            )
            for (sid, reason), count in current.items()
            if count > 0 and previous.get((sid, reason), 0) == 0
        ]


def http_get(url: str, *, timeout_seconds: float = 10.0) -> None:
    """One GET; raises on network errors and non-2xx answers (urllib does both)."""
    with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
        response.read(1024)


@dataclass(slots=True)
class Heartbeat:
    """Push-style dead-man's switch: ping `url` at most every `every_seconds` while ready.

    Not ready: ping `fail_url` when one is configured (healthchecks.io's `/fail` turns
    the check red at once), otherwise send nothing and let the silence trip the check.
    A change of state pings immediately. A ping that fails is retried next round.
    """

    url: str
    every_seconds: float = 300.0
    fail_url: str = ""
    send: Callable[[str], None] = http_get
    last_sent: float | None = None
    last_ready: bool | None = None

    def due(self, ready: bool, now: float) -> str | None:
        target = self.url if ready else self.fail_url
        if not target:
            return None
        changed = self.last_ready is not None and ready != self.last_ready
        if changed or self.last_sent is None or now - self.last_sent >= self.every_seconds:
            return target
        return None

    async def tick(self, ready: bool, now: float) -> None:
        target = self.due(ready, now)
        if target is not None:
            try:
                await asyncio.to_thread(self.send, target)
            except Exception as exc:
                # The URL can carry a secret check id: log the failure, not the URL.
                logger.warning("live paper heartbeat not delivered: %s", type(exc).__name__)
                return
            self.last_sent = now
        self.last_ready = ready


async def run_watchdog(
    evaluate: Callable[[], Readiness],
    notifier: AlertNotifier,
    *,
    every_seconds: float,
    sessions: Callable[[], Iterable[Any]] | None = None,
    heartbeat: Heartbeat | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    watchdog: Watchdog | None = None,
) -> None:
    """Evaluate forever; each transition goes to the notifier off the event loop.

    The notifiers are synchronous HTTP calls (infrastructure/alerts.py); running them in
    a thread keeps a slow Telegram from stalling bar processing. A failing notifier is
    logged and never stops the loop: alerts are fail-open, trading is not affected.
    """
    dog = watchdog or Watchdog()
    while True:
        readiness: Readiness | None = None
        try:
            readiness = evaluate()
            messages = dog.transitions(readiness)
            if sessions is not None:
                messages += dog.breaker_trips(sessions())
        except Exception:
            logger.exception("live paper watchdog: readiness check failed")
            messages = []
        for level, message in messages:
            logger.warning("%s", message)
            try:
                # One failed send must not swallow the other messages of this round.
                await asyncio.to_thread(notifier.notify, message, level)
            except Exception:
                logger.exception("live paper watchdog: alert not delivered: %s", message)
        if heartbeat is not None:
            # A check that itself crashed counts as not ready: silence is the safe signal.
            await heartbeat.tick(readiness is not None and readiness.ready, clock())
        await sleep(every_seconds)


# ------------------------------------------------------------------ metrics


def render_metrics(
    readiness: Readiness,
    sessions: Iterable[Any],
    *,
    manifest: RunManifest | None = None,
) -> str:
    """Prometheus text exposition (version 0.0.4) of readiness, feeds and sessions."""
    lines: list[str] = []

    def metric(
        name: str, kind: str, help_text: str, rows: list[tuple[dict[str, str], Any]]
    ) -> None:
        lines.append(f"# HELP nautilus_lab_{name} {help_text}")
        lines.append(f"# TYPE nautilus_lab_{name} {kind}")
        for labels, value in rows:
            if value is None:
                continue
            lines.append(f"nautilus_lab_{name}{_labels(labels)} {_value(value)}")

    info_labels = {
        "revision": (manifest.code_revision or "unknown") if manifest else "unknown",
        "nautilus": (manifest.nautilus_version or "unknown") if manifest else "unknown",
    }
    metric("info", "gauge", "Build information.", [(info_labels, 1)])
    metric(
        "ready",
        "gauge",
        "1 when every feed and session is healthy.",
        [({}, 1 if readiness.ready else 0)],
    )
    metric(
        "sessions_active",
        "gauge",
        "Running live paper sessions.",
        [({}, readiness.sessions_active)],
    )

    feeds = [
        ({"symbol": str(f["symbol"]), "interval": str(f["interval"])}, f) for f in readiness.feeds
    ]
    metric(
        "feed_connected",
        "gauge",
        "1 while the market socket is open.",
        [(labels, 1 if f.get("connected") else 0) for labels, f in feeds],
    )
    metric(
        "feed_healthy",
        "gauge",
        "1 when the feed passes the readiness rules.",
        [(labels, 0 if f.get("problem") else 1) for labels, f in feeds],
    )
    metric(
        "feed_last_message_age_seconds",
        "gauge",
        "Seconds since the last message.",
        [(labels, f.get("last_message_age_seconds")) for labels, f in feeds],
    )
    metric(
        "feed_last_closed_bar_age_seconds",
        "gauge",
        "Seconds since the last closed bar.",
        [(labels, f.get("last_closed_age_seconds")) for labels, f in feeds],
    )
    metric(
        "feed_messages_total",
        "counter",
        "Messages received.",
        [(labels, f.get("messages")) for labels, f in feeds],
    )
    metric(
        "feed_reconnects_total",
        "counter",
        "Socket reconnects.",
        [(labels, f.get("reconnects")) for labels, f in feeds],
    )

    rows: list[tuple[dict[str, str], Any]] = []
    for session in sessions:
        if not getattr(session, "is_active", False):
            continue
        cfg = session.config
        labels = {
            "session": str(cfg.name or session.session_id),
            "robot": str(cfg.robot),
            "symbol": str(cfg.symbol),
            "interval": str(cfg.interval),
        }
        rows.append((labels, session))
    metric(
        "session_equity",
        "gauge",
        "Marked equity (balance + open position).",
        [(labels, s.current_equity) for labels, s in rows],
    )
    metric(
        "session_fills_total",
        "counter",
        "Simulated fills.",
        [(labels, len(s.fills)) for labels, s in rows],
    )
    metric(
        "session_journal_errors_total",
        "counter",
        "Failed journal writes.",
        [(labels, s.journal_errors) for labels, s in rows],
    )
    metric(
        "session_paused",
        "gauge",
        "1 while new entries are paused.",
        [(labels, 1 if s.paused else 0) for labels, s in rows],
    )
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ helpers


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _ages(status: Mapping[str, Any], now: float) -> dict[str, float | None]:
    def age(key: str) -> float | None:
        value = _number(status.get(key))
        return None if value is None else round(max(now - value, 0.0), 1)

    return {
        "last_message_age_seconds": age("last_message_at"),
        "last_closed_age_seconds": age("last_closed_at"),
    }


def _problem_key(text: str) -> str:
    """'feed ETHUSDT 1h: no message for 95s' -> 'feed ETHUSDT 1h: no message'."""
    subject, _, detail = text.partition(":")
    words = [w for w in detail.split() if not any(ch.isdigit() for ch in w)]
    return f"{subject}: {' '.join(words[:3])}"


def _subject(text: str) -> str:
    return text.partition(":")[0]


def _labels(labels: Mapping[str, str]) -> str:
    if not labels:
        return ""
    body = ",".join(f'{k}="{_escape(v)}"' for k, v in labels.items())
    return "{" + body + "}"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _value(value: bool | int | float | Decimal) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value) if isinstance(value, int) else repr(float(value))
