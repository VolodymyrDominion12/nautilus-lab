from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from nautilus_lab.domain.errors import InvalidRiskError


@dataclass(frozen=True, slots=True)
class Money:
    """Non-negative cash amount. Use Decimal, never float."""

    amount: Decimal
    currency: str = "USDT"

    def __post_init__(self) -> None:
        amount = Decimal(self.amount)
        if amount < 0:
            raise InvalidRiskError("amount must be >= 0")
        object.__setattr__(self, "amount", amount)

    def risk_amount(self, fraction: Decimal) -> Decimal:
        if fraction < 0 or fraction > 1:
            raise InvalidRiskError("fraction must be in [0, 1]")
        return (self.amount * fraction).quantize(Decimal("0.01"))
