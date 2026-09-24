"""Liveness of the paper server (docs/27 E-1.5/E-1.6): readiness, watchdog, metrics."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from nautilus_lab.api.health import (
    HealthLimits,
    Readiness,
    Watchdog,
    check_readiness,
    feed_problem,
    render_metrics,
    run_watchdog,
)
from nautilus_lab.api.market_feed import MarketFeed
from nautilus_lab.api.paper_streamer import LivePaperConfig, LivePaperSessionManager
from nautilus_lab.domain.provenance import RunManifest
from nautilus_lab.infrastructure.live_paper_journal import LivePaperJournal

LIMITS = HealthLimits(
    message_timeout_seconds=90, closed_bar_slack_seconds=180, startup_grace_seconds=120
)
NOW = 1_800_000_000.0


def _feed(**overrides: Any) -> dict[str, Any]:
    status: dict[str, Any] = {
        "symbol": "ETHUSDT",
        "interval": "1h",
        "connected": True,
        "sessions": 2,
        "messages": 500,
        "reconnects": 0,
        "started_at": NOW - 7200,
        "last_message_at": NOW - 2,
        "last_closed_at": NOW - 600,
    }
    status.update(overrides)
    return status


# ------------------------------------------------------------------ feeds


def test_a_feed_that_delivers_is_healthy() -> None:
    assert feed_problem(_feed(), now=NOW, limits=LIMITS) is None


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"last_message_at": NOW - 300}, "no message for 300s"),
        # "connected" is not evidence: the socket can be open and silent.
        ({"last_message_at": NOW - 300, "connected": True}, "no message for 300s"),
        ({"last_closed_at": NOW - 3600 - 181}, "last closed bar 3781s ago"),
        (
            {"started_at": NOW - 3600 - 200, "last_closed_at": None},
            "no closed bar since start 3800s ago",
        ),
        (
            {"started_at": NOW - 121, "last_message_at": None, "last_closed_at": None},
            "no message since start 121s ago",
        ),
    ],
)
def test_silence_is_named(overrides: dict[str, Any], expected: str) -> None:
    problem = feed_problem(_feed(**overrides), now=NOW, limits=LIMITS)
    assert problem is not None
    assert problem.startswith("feed ETHUSDT 1h: ")
    assert expected in problem


def test_a_new_feed_gets_its_startup_grace() -> None:
    fresh = _feed(started_at=NOW - 30, last_message_at=None, last_closed_at=None)
    assert feed_problem(fresh, now=NOW, limits=LIMITS) is None


def test_a_closed_bar_just_after_the_interval_is_not_late() -> None:
    assert feed_problem(_feed(last_closed_at=NOW - 3600 - 60), now=NOW, limits=LIMITS) is None


def test_unknown_interval_is_judged_by_messages_only() -> None:
    odd = _feed(interval="2h", last_closed_at=NOW - 100_000)
    assert feed_problem(odd, now=NOW, limits=LIMITS) is None


def test_market_feed_records_message_and_closed_bar_times() -> None:
    clock = iter([100.0, 200.0, 300.0]).__next__
    feed = MarketFeed(("ETHUSDT", "1h"), connect=None, clock=clock)  # type: ignore[arg-type]

    def kline(closed: bool) -> str:
        return json.dumps(
            {"k": {"t": 0, "o": "1", "h": "1", "l": "1", "c": "1", "v": "1", "x": closed}}
        )

    asyncio.run(feed.dispatch(kline(False)))
    assert (feed.last_message_at, feed.last_closed_at) == (100.0, None)
    asyncio.run(feed.dispatch(kline(True)))
    assert (feed.last_message_at, feed.last_closed_at) == (200.0, 200.0)
    assert feed.messages == 2


# --------------------------------------------------------------- sessions


@dataclass
class _Session:
    session_id: str | None = "s1"
    is_active: bool = True
    journal_failing: bool = False
    journal_errors: int = 0


def test_idle_server_is_ready() -> None:
    readiness = check_readiness([], [], now=NOW, limits=LIMITS)
    assert readiness.ready
    assert readiness.as_dict()["status"] == "ready"


def test_a_failing_ledger_makes_the_server_not_ready() -> None:
    sessions = [_Session(journal_failing=True, journal_errors=3), _Session(session_id="s2")]
    readiness = check_readiness([_feed()], sessions, now=NOW, limits=LIMITS)
    assert not readiness.ready
    assert readiness.sessions_active == 2
    assert any("s1: journal write failing (3 failed writes)" in p for p in readiness.problems)


def test_a_stopped_session_with_old_errors_does_not_block_readiness() -> None:
    stopped = _Session(is_active=False, journal_failing=True, journal_errors=1)
    assert check_readiness([], [stopped], now=NOW, limits=LIMITS).ready


def test_readiness_reports_ages_per_feed() -> None:
    readiness = check_readiness([_feed()], [], now=NOW, limits=LIMITS)
    (feed,) = readiness.as_dict()["feeds"]
    assert feed["last_message_age_seconds"] == 2.0
    assert feed["last_closed_age_seconds"] == 600.0
    assert feed["problem"] is None


def test_manager_counts_failed_journal_writes(tmp_path: Path) -> None:
    # A directory where the journal file should be: every append raises OSError.
    journal_path = tmp_path / "journal.jsonl"
    journal_path.mkdir()
    manager = LivePaperSessionManager(journal=LivePaperJournal(journal_path))
    manager._launch_stream = lambda: None  # type: ignore[method-assign]
    asyncio.run(manager.start(LivePaperConfig(symbol="ETHUSDT", interval="1h")))
    assert manager.is_active, "a broken ledger must not stop trading"
    assert manager.journal_failing
    assert manager.journal_errors >= 1


# --------------------------------------------------------------- watchdog


def test_watchdog_speaks_on_change_only() -> None:
    dog = Watchdog()
    down = Readiness(ready=False, problems=("feed ETHUSDT 1h: no message for 95s",))
    still_down = Readiness(ready=False, problems=("feed ETHUSDT 1h: no message for 185s",))
    up = Readiness(ready=True, problems=())

    assert dog.transitions(down) == [
        ("WARNING", "live paper problem: feed ETHUSDT 1h: no message for 95s")
    ]
    assert dog.transitions(still_down) == [], "a longer silence is the same problem"
    assert dog.transitions(up) == [("INFO", "live paper recovered: feed ETHUSDT 1h")]
    assert dog.transitions(up) == []


def test_watchdog_tells_different_problems_of_one_feed_apart() -> None:
    dog = Watchdog()
    dog.transitions(Readiness(ready=False, problems=("feed BTCUSDT 4h: no message for 95s",)))
    late = "feed BTCUSDT 4h: last closed bar 14600s ago (interval 14400s)"
    messages = dog.transitions(Readiness(ready=False, problems=(late,)))
    assert ("WARNING", f"live paper problem: {late}") in messages
    assert ("INFO", "live paper recovered: feed BTCUSDT 4h") in messages


@dataclass
class _Notifier:
    sent: list[tuple[str, str]] = field(default_factory=list)
    fail: bool = False

    def notify(self, message: str, level: str = "INFO") -> bool:
        if self.fail:
            raise RuntimeError("telegram is down")
        self.sent.append((level, message))
        return True


def _stop_after(rounds: int) -> Any:
    calls = {"n": 0}

    async def sleep(_seconds: float) -> None:
        calls["n"] += 1
        if calls["n"] >= rounds:
            raise asyncio.CancelledError

    return sleep


def test_run_watchdog_sends_transitions_to_the_notifier() -> None:
    states = iter(
        [
            Readiness(ready=False, problems=("feed ETHUSDT 1h: no message for 95s",)),
            Readiness(ready=False, problems=("feed ETHUSDT 1h: no message for 125s",)),
            Readiness(ready=True, problems=()),
        ]
    )
    notifier = _Notifier()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            run_watchdog(lambda: next(states), notifier, every_seconds=0, sleep=_stop_after(3))
        )
    assert [level for level, _ in notifier.sent] == ["WARNING", "INFO"]


def test_a_broken_notifier_never_stops_the_watchdog() -> None:
    evaluations = {"n": 0}

    def evaluate() -> Readiness:
        evaluations["n"] += 1
        return Readiness(ready=False, problems=(f"feed X 1h: no message for {evaluations['n']}s",))

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            run_watchdog(evaluate, _Notifier(fail=True), every_seconds=0, sleep=_stop_after(3))
        )
    assert evaluations["n"] == 3


def test_one_failed_send_does_not_drop_the_rest_of_the_round() -> None:
    sent: list[str] = []

    class _Flaky:
        def notify(self, message: str, level: str = "INFO") -> bool:
            if not sent:
                sent.append("lost")
                raise RuntimeError("timeout")
            sent.append(message)
            return True

    both = Readiness(
        ready=False,
        problems=("feed A 1h: no message for 95s", "feed B 1h: no message for 95s"),
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_watchdog(lambda: both, _Flaky(), every_seconds=0, sleep=_stop_after(1)))
    assert sent == ["lost", "live paper problem: feed B 1h: no message for 95s"]


# ---------------------------------------------------------------- metrics


@dataclass
class _Cfg:
    name: str = 'regime "eth"'
    robot: str = "regime"
    symbol: str = "ETHUSDT"
    interval: str = "1h"


@dataclass
class _Running:
    config: _Cfg = field(default_factory=_Cfg)
    session_id: str = "abc"
    is_active: bool = True
    current_equity: Decimal = Decimal("10012.34")
    fills: list[object] = field(default_factory=lambda: [object(), object()])
    journal_errors: int = 0
    paused: bool = False


def test_metrics_are_prometheus_text() -> None:
    readiness = check_readiness(
        [_feed(last_closed_at=None, started_at=NOW - 60)], [], now=NOW, limits=LIMITS
    )
    text = render_metrics(
        readiness,
        [_Running(), _Running(is_active=False)],
        manifest=RunManifest(code_revision="abc123", nautilus_version="1.231.0"),
    )
    assert 'nautilus_lab_info{revision="abc123",nautilus="1.231.0"} 1' in text
    assert "nautilus_lab_ready 1" in text
    assert 'nautilus_lab_feed_connected{symbol="ETHUSDT",interval="1h"} 1' in text
    assert "nautilus_lab_feed_last_closed_bar_age_seconds{" not in text, "unknown is omitted"
    assert (
        'nautilus_lab_session_equity{session="regime \\"eth\\"",robot="regime",'
        'symbol="ETHUSDT",interval="1h"} 10012.34'
    ) in text
    assert text.count("nautilus_lab_session_fills_total{") == 1, "stopped sessions are left out"
    for line in text.splitlines():
        assert line.startswith("# ") or line.startswith("nautilus_lab_"), line


@dataclass
class _Guarded:
    risk_refusals: dict[str, int]
    session_id: str = "s1"
    is_active: bool = True
    config: _Cfg = field(default_factory=_Cfg)


def test_breaker_trip_is_announced_once_and_old_counts_are_not() -> None:
    dog = Watchdog()
    resumed = _Guarded({"max drawdown circuit breaker": 12})
    assert dog.breaker_trips([resumed]) == [], "counts carried over a restart are history"

    session = _Guarded({"max drawdown circuit breaker": 12, "daily loss circuit breaker": 0})
    assert dog.breaker_trips([session]) == []
    session.risk_refusals["daily loss circuit breaker"] = 1
    assert dog.breaker_trips([session]) == [
        (
            "WARNING",
            'live paper session regime "eth": daily loss circuit breaker tripped, '
            "new entries refused",
        )
    ]
    session.risk_refusals["daily loss circuit breaker"] = 7
    assert dog.breaker_trips([session]) == [], "refusing on every bar is one trip"
    session.risk_refusals["position already open"] = 3
    assert dog.breaker_trips([session]) == [], "only breakers are alerts"
