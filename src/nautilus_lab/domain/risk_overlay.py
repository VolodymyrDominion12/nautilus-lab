from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from nautilus_lab.domain.errors import InvalidRiskError
from nautilus_lab.domain.ratchet_stop import RatchetParams
from nautilus_lab.domain.volatility import VolModel


@dataclass(frozen=True, slots=True)
class RiskOverlay:
    """Optional sizing and breaker overlays. All disabled by default."""

    use_vol_scaling: bool = False
    vol_scaling_target: Decimal = Decimal("0.02")
    vol_model: VolModel = VolModel.HAR
    vol_refit_every: int = 24
    use_fractional_kelly: bool = False
    kelly_min_trades: int = 30
    use_cvar_breaker: bool = False
    max_cvar_99: Decimal = Decimal("0.05")
    use_ratchet: bool = False
    ratchet_arm_pct: Decimal = Decimal("0.0125")
    # A resting reduce-only stop at the same distance `size_position` sized against.
    # On by default: without it `risk_per_trade` is a sizing assumption, not a cap —
    # nothing bounds the loss of a position the strategy never exits.
    use_protective_stop: bool = True
    # Days after which a tripped max-drawdown breaker re-bases its peak (0 = never).
    drawdown_cooldown_days: int = 0

    def __post_init__(self) -> None:
        if self.vol_scaling_target <= 0 or self.vol_scaling_target > 1:
            raise InvalidRiskError("vol_scaling_target must be in (0, 1]")
        if self.vol_refit_every < 1:
            raise InvalidRiskError("vol_refit_every must be >= 1")
        if self.kelly_min_trades < 1:
            raise InvalidRiskError("kelly_min_trades must be >= 1")
        if self.max_cvar_99 <= 0 or self.max_cvar_99 > 1:
            raise InvalidRiskError("max_cvar_99 must be in (0, 1]")
        if self.drawdown_cooldown_days < 0:
            raise InvalidRiskError("drawdown_cooldown_days must be >= 0")
        if self.ratchet_arm_pct <= 0 or self.ratchet_arm_pct > 1:
            raise InvalidRiskError("ratchet_arm_pct must be in (0, 1]")

    def ratchet_params(self, *, stop_pct: Decimal) -> RatchetParams:
        """Protective percent comes from `RiskLimits.stop_pct`, not from the strategy."""
        return RatchetParams(max_loss_pct=stop_pct, arm_pct=self.ratchet_arm_pct)
