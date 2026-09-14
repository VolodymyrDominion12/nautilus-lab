from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from nautilus_lab.domain.errors import InvalidRiskError


@dataclass(frozen=True, slots=True)
class RiskOverlay:
    """Optional sizing and breaker overlays. All disabled by default."""

    use_vol_scaling: bool = False
    vol_scaling_target: Decimal = Decimal("0.02")
    use_fractional_kelly: bool = False
    kelly_min_trades: int = 30
    use_cvar_breaker: bool = False
    max_cvar_99: Decimal = Decimal("0.05")

    def __post_init__(self) -> None:
        if self.vol_scaling_target <= 0 or self.vol_scaling_target > 1:
            raise InvalidRiskError("vol_scaling_target must be in (0, 1]")
        if self.kelly_min_trades < 1:
            raise InvalidRiskError("kelly_min_trades must be >= 1")
        if self.max_cvar_99 <= 0 or self.max_cvar_99 > 1:
            raise InvalidRiskError("max_cvar_99 must be in (0, 1]")
