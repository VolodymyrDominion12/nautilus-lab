from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class SignalSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True, slots=True)
class Signal:
    """Intent from a strategy. Execution and risk live outside the strategy."""

    instrument_id: str
    side: SignalSide
    bar_ts_utc: datetime
    reason: str
