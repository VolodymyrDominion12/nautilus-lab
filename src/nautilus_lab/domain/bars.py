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
    """One closed bar. Timestamps are UTC. Prices are Decimal.

    `taker_buy_base_volume` is Binance kline field 9 — the base volume that
    aggressive (taker) buyers lifted in this bar. It is `None` when the source does
    not carry it (synthetic bars, catalogs ingested before phase 4 of
    docs/23-infrastruktura-danyh-plan.md), and `None` means *unknown*, never zero:
    a bar with no aggressive buying is a real, different observation.
    """

    instrument_id: str
    ts_utc: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    taker_buy_base_volume: Decimal | None = None

    @property
    def taker_sell_base_volume(self) -> Decimal | None:
        """Aggressive sell volume implied by the bar, or None when unknown.

        Derived, not stored: the sell side is whatever the takers did not buy. The
        invariant `0 <= taker_buy <= volume` is enforced by `validate_bar`, so this
        can never come out negative on a validated bar.
        """
        if self.taker_buy_base_volume is None:
            return None
        return self.volume - self.taker_buy_base_volume


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
    taker_buy = bar.taker_buy_base_volume
    if taker_buy is not None:
        if taker_buy < 0:
            raise InvalidBarError("taker buy base volume must be >= 0")
        # Takers cannot buy more base than the bar traded. A breach means the flow
        # series and the bar series disagree (wrong interval, misaligned window),
        # which must fail loudly instead of tilting an order-flow feature.
        if taker_buy > bar.volume:
            raise InvalidBarError("taker buy base volume must be <= bar volume")
    if previous_ts is not None and bar.ts_utc <= previous_ts:
        raise InvalidBarError("bar timestamps must be strictly increasing")
    clock = now if now is not None else datetime.now(UTC)
    if bar.ts_utc > clock:
        raise InvalidBarError("bar timestamp is in the future")
