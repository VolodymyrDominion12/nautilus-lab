from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from nautilus_lab.domain.errors import InvalidRiskError


@dataclass(frozen=True, slots=True)
class FeeSchedule:
    """Exchange fee schedule in decimal fractions (not bps)."""

    maker: Decimal
    taker: Decimal

    def __post_init__(self) -> None:
        if self.maker < 0 or self.taker < 0:
            raise InvalidRiskError("fees must be >= 0")
        if self.maker > Decimal("0.01") or self.taker > Decimal("0.01"):
            raise InvalidRiskError("fees look too large; use decimal fractions")

    @classmethod
    def binance_spot_vip0(cls) -> FeeSchedule:
        """Conservative VIP0 spot defaults from MFT doc (0.10% maker/taker)."""
        return cls(maker=Decimal("0.001"), taker=Decimal("0.001"))

    @classmethod
    def binance_usdm_vip0(cls) -> FeeSchedule:
        """Conservative VIP0 USD-M futures defaults (0.020% / 0.050%)."""
        return cls(maker=Decimal("0.0002"), taker=Decimal("0.0005"))
