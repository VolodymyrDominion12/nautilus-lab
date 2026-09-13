from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from nautilus_lab.domain.signals import LegIntent, SignalSide, SpreadSignal


@dataclass(frozen=True, slots=True)
class FundingSnapshot:
    instrument: str
    funding_rate: Decimal
    mark_price: Decimal
    index_price: Decimal
    ts_utc: datetime


@dataclass(frozen=True, slots=True)
class FundingParams:
    min_net_apy: Decimal = Decimal("0.10")
    taker_fee: Decimal = Decimal("0.0005")
    basis_max: Decimal = Decimal("0.005")
    close_on_negative: bool = True


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
        basis = (snapshot.mark_price - snapshot.index_price) / snapshot.index_price
        net = snapshot.funding_rate - self._params.taker_fee * 2
        annualized = net * Decimal("3") * Decimal("365")
        ts = snapshot.ts_utc

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

    def _flat(self, ts: datetime, reason: str) -> SpreadSignal:
        return SpreadSignal(
            leg_a=LegIntent(self._spot_id, SignalSide.FLAT),
            leg_b=LegIntent(self._perp_id, SignalSide.FLAT),
            bar_ts_utc=ts,
            reason=reason,
            hedge_ratio=Decimal("1"),
        )
