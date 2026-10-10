from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from nautilus_lab.domain.chandelier_stop import ChandelierParams
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
    # Chandelier Exit: volatility-adaptive trailing stop from highest high/lowest low.
    use_chandelier_stop: bool = False
    chandelier_atr_multiple: Decimal = Decimal("3.0")
    chandelier_lookback: int = 22
    # Closed bars after a ratchet/Chandelier exit during which no new position opens (0 = off).
    stop_cooldown_bars: int = 0

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
        if self.chandelier_atr_multiple <= 0:
            raise InvalidRiskError("chandelier_atr_multiple must be > 0")
        if self.chandelier_lookback < 1:
            raise InvalidRiskError("chandelier_lookback must be >= 1")
        if self.stop_cooldown_bars < 0:
            raise InvalidRiskError("stop_cooldown_bars must be >= 0")

    def ratchet_params(self, *, stop_pct: Decimal) -> RatchetParams:
        """Protective percent comes from `RiskLimits.stop_pct`, not from the strategy."""
        return RatchetParams(max_loss_pct=stop_pct, arm_pct=self.ratchet_arm_pct)

    def chandelier_params(self) -> ChandelierParams:
        """Chandelier Exit parameters for adaptive trailing stop."""
        return ChandelierParams(
            atr_multiple=self.chandelier_atr_multiple,
            lookback=self.chandelier_lookback,
        )

    def __repr__(self) -> str:
        text = self._legacy_repr()
        if self.stop_cooldown_bars == 0:
            return text
        # Appended only when set, so the repr (a preregistration-hash input) of every
        # existing configuration is byte-identical.
        return f"{text[:-1]}, stop_cooldown_bars={self.stop_cooldown_bars})"

    def _legacy_repr(self) -> str:
        base = (
            f"RiskOverlay(use_vol_scaling={self.use_vol_scaling}, "
            f"vol_scaling_target={self.vol_scaling_target!r}, "
            f"vol_model={self.vol_model!r}, "
            f"vol_refit_every={self.vol_refit_every}, "
            f"use_fractional_kelly={self.use_fractional_kelly}, "
            f"kelly_min_trades={self.kelly_min_trades}, "
            f"use_cvar_breaker={self.use_cvar_breaker}, "
            f"max_cvar_99={self.max_cvar_99!r}, "
            f"use_ratchet={self.use_ratchet}, "
            f"ratchet_arm_pct={self.ratchet_arm_pct!r}, "
            f"use_protective_stop={self.use_protective_stop}, "
            f"drawdown_cooldown_days={self.drawdown_cooldown_days})"
        )
        if not self.use_chandelier_stop:
            return base
        return (
            f"RiskOverlay(use_vol_scaling={self.use_vol_scaling}, "
            f"vol_scaling_target={self.vol_scaling_target!r}, "
            f"vol_model={self.vol_model!r}, "
            f"vol_refit_every={self.vol_refit_every}, "
            f"use_fractional_kelly={self.use_fractional_kelly}, "
            f"kelly_min_trades={self.kelly_min_trades}, "
            f"use_cvar_breaker={self.use_cvar_breaker}, "
            f"max_cvar_99={self.max_cvar_99!r}, "
            f"use_ratchet={self.use_ratchet}, "
            f"ratchet_arm_pct={self.ratchet_arm_pct!r}, "
            f"use_protective_stop={self.use_protective_stop}, "
            f"drawdown_cooldown_days={self.drawdown_cooldown_days}, "
            f"use_chandelier_stop={self.use_chandelier_stop}, "
            f"chandelier_atr_multiple={self.chandelier_atr_multiple!r}, "
            f"chandelier_lookback={self.chandelier_lookback})"
        )
