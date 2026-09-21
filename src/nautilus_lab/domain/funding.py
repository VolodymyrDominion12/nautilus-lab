from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from nautilus_lab.domain.signals import LegIntent, SignalSide, SpreadSignal


@dataclass(frozen=True, slots=True)
class FundingSnapshot:
    """One funding settlement.

    `index_price` is optional on purpose. Binance's `fapi/v1/fundingRate` response
    carries `markPrice` but **no** `indexPrice` (verified against the live endpoint),
    so an adapter that defaults index to mark silently makes the basis
    `(mark - index) / index` identically zero — a gate that can never fire and never
    complains. `None` here means "index unknown", which callers must treat as
    *no information*, never as "no divergence".
    """

    instrument: str
    funding_rate: Decimal
    mark_price: Decimal
    index_price: Decimal | None
    ts_utc: datetime

    def basis(self) -> Decimal | None:
        """`(mark - index) / index`, or None when it cannot be computed honestly."""
        if self.index_price is None or self.index_price <= 0:
            return None
        return (self.mark_price - self.index_price) / self.index_price


@dataclass(frozen=True, slots=True)
class FundingParams:
    min_net_apy: Decimal = Decimal("0.10")
    taker_fee: Decimal = Decimal("0.0005")
    # Funding intervals the position is expected to be held for (8h each on Binance
    # USD-M). The round trip costs two taker fees exactly once, so amortising them
    # over the holding period is what makes the APY gate comparable with the funding
    # rate. Charging the full round trip against *every* interval instead needs a
    # funding rate above 0.1% per 8h (~109% APY) to clear a 10% gate, which no
    # ordinary market ever pays — the robot could never open a position.
    holding_periods: int = 30
    basis_max: Decimal = Decimal("0.005")
    close_on_negative: bool = True

    def __post_init__(self) -> None:
        if self.taker_fee < 0:
            raise ValueError("taker_fee must be >= 0")
        if self.holding_periods < 1:
            raise ValueError("holding_periods must be >= 1")
        if self.basis_max < 0:
            raise ValueError("basis_max must be >= 0")


class FundingCashAndCarry:
    """Delta-neutral spot long + perp short when funding exceeds costs."""

    def __init__(
        self,
        *,
        spot_id: str,
        perp_id: str,
        params: FundingParams,
    ) -> None:
        self._spot_id = spot_id
        self._perp_id = perp_id
        self._params = params
        self._open = False

    def on_funding(self, snapshot: FundingSnapshot) -> SpreadSignal | None:
        ts = snapshot.ts_utc
        basis = snapshot.basis()
        if basis is None:
            # An unusable snapshot must not crash the run, and must not be read as a
            # flat basis (0/0 is not "no divergence", it is "we do not know").
            return self._flat(ts, "missing index price") if self._open else None
        net = snapshot.funding_rate - self._round_trip_fee_per_interval()
        annualized = net * Decimal("3") * Decimal("365")

        if self._open:
            if self._params.close_on_negative and snapshot.funding_rate < 0:
                self._open = False
                return self._flat(ts, "negative funding")
            if abs(basis) > self._params.basis_max:
                self._open = False
                return self._flat(ts, "basis divergence")
            return None

        if annualized < self._params.min_net_apy:
            return None
        if abs(basis) > self._params.basis_max:
            return None
        self._open = True
        return SpreadSignal(
            leg_a=LegIntent(self._spot_id, SignalSide.BUY),
            leg_b=LegIntent(self._perp_id, SignalSide.SELL),
            bar_ts_utc=ts,
            reason="funding cash-and-carry",
            hedge_ratio=Decimal("1"),
            z_score=None,
            half_life_bars=None,
        )

    def _round_trip_fee_per_interval(self) -> Decimal:
        return self._params.taker_fee * Decimal("2") / Decimal(self._params.holding_periods)

    def _flat(self, ts: datetime, reason: str) -> SpreadSignal:
        return SpreadSignal(
            leg_a=LegIntent(self._spot_id, SignalSide.FLAT),
            leg_b=LegIntent(self._perp_id, SignalSide.FLAT),
            bar_ts_utc=ts,
            reason=reason,
            hedge_ratio=Decimal("1"),
        )
