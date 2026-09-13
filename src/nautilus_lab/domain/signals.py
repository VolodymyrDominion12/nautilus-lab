from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from nautilus_lab.domain.regime import MarketRegime


class SignalSide(StrEnum):
    BUY = "buy"
    SELL = "sell"
    FLAT = "flat"


@dataclass(frozen=True, slots=True)
class Signal:
    """Intent from a strategy. Execution and risk live outside the strategy."""

    instrument_id: str
    side: SignalSide
    bar_ts_utc: datetime
    reason: str
    regime: MarketRegime | None = None
