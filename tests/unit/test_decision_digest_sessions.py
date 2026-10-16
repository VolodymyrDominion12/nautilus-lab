"""Digest sequence statistics are counted inside a session, never across fold seams.

A walk-forward writes one decision session per fold, and fold k+1's warm-up replays the
last bars of fold k. Sorted by time, the two sessions interleave: the 2026-10-12/13 batches
reported 745 `bar_seq` gaps in every cell, all of them seams, none of them missed bars.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from nautilus_lab.application.decision_digest import build_digest

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _bar(session: str, seq: int, hour: int, regime: str, close: float = 100.0) -> dict[str, Any]:
    return {
        "kind": "bar_decision",
        "session_id": session,
        "ts": (T0 + timedelta(hours=hour)).isoformat(),
        "bar_seq": seq,
        "regime": regime,
        "close": str(close),
        "outcome": "NO_SIGNAL",
        "steps": [],
    }


def _fold(session: str, start_hour: int, n: int, regime: str) -> list[dict[str, Any]]:
    return [_bar(session, i + 1, start_hour + i, regime) for i in range(n)]


def test_overlapping_fold_sessions_report_no_gaps() -> None:
    # fold 1 starts warming up 5 bars before fold 0's last bar
    rows = _fold("s-f0", 0, 10, "uptrend") + _fold("s-f1", 5, 10, "downtrend")
    digest = build_digest(rows, max_narratives=0, no_signal_samples=0)
    assert digest.bar_seq_gaps == 0
    assert digest.regime_switches == 0
    assert digest.regime_flip_flops == 0


def test_a_missed_bar_inside_a_session_is_still_a_gap() -> None:
    rows = _fold("s-f0", 0, 4, "uptrend")
    rows[2]["bar_seq"] = 9  # the writer skipped five bars
    rows[3]["bar_seq"] = 10
    digest = build_digest(rows, max_narratives=0, no_signal_samples=0)
    assert digest.bar_seq_gaps == 1


def test_forward_returns_read_the_same_session() -> None:
    entry = _bar("s-f0", 1, 0, "uptrend", close=100.0)
    entry.update(outcome="ENTRY_OPENED", signal="buy")
    later = [_bar("s-f0", i + 2, i + 1, "uptrend", close=110.0) for i in range(3)]
    # another session's bars at the same hours, at a different price
    other = [_bar("s-f1", i + 1, i + 1, "uptrend", close=50.0) for i in range(3)]
    digest = build_digest(
        [entry, *later, *other], horizons=(1,), max_narratives=0, no_signal_samples=0
    )
    stats = digest.forward["executed"]["+1"]
    assert stats.n == 1
    assert stats.mean_pct == 10.0
