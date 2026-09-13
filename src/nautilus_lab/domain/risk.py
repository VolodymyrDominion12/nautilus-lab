from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from nautilus_lab.domain.errors import InvalidRiskError


@dataclass(frozen=True, slots=True)
class RiskLimits:
    """Hard risk caps. Strategies must not bypass these."""

    risk_per_trade: Decimal
    stop_pct: Decimal
    max_daily_loss: Decimal
    max_drawdown: Decimal
    max_open_positions: int = 1
    kelly_fraction: Decimal = Decimal("0.25")
    max_var_99: Decimal = Decimal("0.05")
    atr_stop_multiplier: Decimal = Decimal("2")

    def __post_init__(self) -> None:
        for name, value in (
            ("risk_per_trade", self.risk_per_trade),
            ("stop_pct", self.stop_pct),
            ("max_daily_loss", self.max_daily_loss),
            ("max_drawdown", self.max_drawdown),
            ("kelly_fraction", self.kelly_fraction),
            ("max_var_99", self.max_var_99),
        ):
            if value <= 0 or value > 1:
                raise InvalidRiskError(f"{name} must be in (0, 1]")
        if self.atr_stop_multiplier <= 0:
            raise InvalidRiskError("atr_stop_multiplier must be > 0")
        if self.max_open_positions < 1:
            raise InvalidRiskError("max_open_positions must be >= 1")


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    equity: Decimal
    peak_equity: Decimal
    day_start_equity: Decimal
    open_positions: int
    recent_returns: tuple[Decimal, ...] = ()


@dataclass(frozen=True, slots=True)
class RiskDecision:
    allowed: bool
    reason: str
