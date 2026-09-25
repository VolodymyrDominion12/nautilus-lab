from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    # ── Identification ──
    ts_utc: str
    bar_ts_utc: str
    robot: str
    session_id: str
    symbol: str
    interval: str

    # ── Bar Data ──
    bar_open: str
    bar_high: str
    bar_low: str
    bar_close: str
    bar_volume: str

    # ── Indicators ──
    indicators: dict[str, str | None]

    # ── Decision ──
    robot_signal: str | None
    signal_reason: str | None

    # ── Filters ──
    filters: dict[str, bool | str]

    # ── Final Action ──
    final_action: str
    action_reason: str

    # ── Account State ──
    balance: str
    equity: str
    open_position: str | None
