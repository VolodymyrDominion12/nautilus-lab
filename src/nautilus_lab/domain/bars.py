from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from nautilus_lab.domain.errors import InvalidBarError


class BarOrigin(StrEnum):
    """Where research bars come from. Catalog is real history; synthetic is for tests."""

    CATALOG = "catalog"
    SYNTHETIC = "synthetic"


@dataclass(frozen=True, slots=True)
class OhlcvBar:
    """One closed bar. Timestamps are UTC. Prices are Decimal."""

    instrument_id: str
    ts_utc: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


def validate_bar(
    bar: OhlcvBar,
    *,
    previous_ts: datetime | None = None,
    now: datetime | None = None,
) -> None:
    """Reject look-ahead, inverted candles, and non-monotonic timestamps."""
    if bar.ts_utc.tzinfo is None:
        raise InvalidBarError("bar timestamp must be timezone-aware UTC")
    if bar.ts_utc.utcoffset() != timedelta(0):
        raise InvalidBarError("bar timestamp must be UTC")
    if bar.high < max(bar.open, bar.close):
        raise InvalidBarError("high must be >= max(open, close)")
    if bar.low > min(bar.open, bar.close):
        raise InvalidBarError("low must be <= min(open, close)")
    if bar.volume < 0:
        raise InvalidBarError("volume must be >= 0")
    if previous_ts is not None and bar.ts_utc <= previous_ts:
        raise InvalidBarError("bar timestamps must be strictly increasing")
    clock = now if now is not None else datetime.now(UTC)
    if bar.ts_utc > clock:
        raise InvalidBarError("bar timestamp is in the future")
