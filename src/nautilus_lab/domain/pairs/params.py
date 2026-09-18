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
    # `None` keeps the fixed-`z_entry` gate, which is the configuration every
    # documented `pairs` run in docs/05 §4 was measured under. A probability in
    # (0, 0.5) switches the entry gate to the empirical quantile of the fitted
    # spread window, and `z_entry` is then ignored entirely — the two modes are
    # deliberately mutually exclusive rather than layered, so that enabling one
    # cannot quietly change the meaning of the other.
    z_entry_quantile: Decimal | None = None

    def __post_init__(self) -> None:
        if self.z_entry_quantile is not None and not (
            Decimal("0") < self.z_entry_quantile < Decimal("0.5")
        ):
            raise ValueError("z_entry_quantile must be in (0, 0.5) or None")
