from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class PairsParams:
    leg_a: str = "ETH/USDT.SIM"
    leg_b: str = "BTC/USDT.SIM"
    lookback: int = 120
    z_entry: Decimal = Decimal("2")
    z_exit: Decimal = Decimal("0.5")
    max_half_life_bars: int = 240
    adf_pvalue_max: Decimal = Decimal("0.05")
    refit_every_bars: int = 0
