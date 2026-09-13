from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from nautilus_lab.domain.regime import MarketRegime


class SignalSide(StrEnum):
    BUY = "buy"
    SELL = "sell"
    FLAT = "flat"


@dataclass(frozen=True, slots=True)
class Signal:
    """Intent from a single-leg strategy. Execution and risk live outside."""

    instrument_id: str
    side: SignalSide
    bar_ts_utc: datetime
    reason: str
    regime: MarketRegime | None = None


@dataclass(frozen=True, slots=True)
class LegIntent:
    """One leg of a spread or hedge. qty_weight is relative, not USDT size."""

    instrument_id: str
    side: SignalSide
    qty_weight: Decimal = Decimal("1")


@dataclass(frozen=True, slots=True)
class SpreadSignal:
    """Market-neutral spread intent. Sizes are applied by risk per leg."""

    leg_a: LegIntent
    leg_b: LegIntent
    bar_ts_utc: datetime
    reason: str
    hedge_ratio: Decimal
    z_score: Decimal | None = None
    half_life_bars: Decimal | None = None


@dataclass(frozen=True, slots=True)
class QuoteIntent:
    """Limit quote intent for market making (GLFT). Sizes set by risk."""

    instrument_id: str
    bar_ts_utc: datetime
    bid_price: Decimal
    ask_price: Decimal
    bid_qty_weight: Decimal = Decimal("1")
    ask_qty_weight: Decimal = Decimal("1")
    reason: str = "glft_quote"
