from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    bar_end_utc: datetime
    robot: str
    instrument_id: str
    close_price: Decimal
    regime: str
    signal: str | None
    signal_reason: str | None
    indicators: dict[str, str]
    states: dict[str, Any]
    session_id: str | None = None
