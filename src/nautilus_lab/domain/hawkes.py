from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import exp


@dataclass(frozen=True, slots=True)
class HawkesIntensity:
    buy_intensity: Decimal
    sell_intensity: Decimal
    toxic_flow: bool


class ExponentialHawkes:
    """Univariate exponential-kernel Hawkes intensity estimator."""

    def __init__(
        self,
        *,
        baseline: Decimal = Decimal("0.1"),
        alpha: Decimal = Decimal("0.5"),
        beta: Decimal = Decimal("1.0"),
        toxic_threshold: Decimal = Decimal("2.0"),
    ) -> None:
        self._mu = baseline
        self._alpha = alpha
        self._beta = beta
        self._toxic_threshold = toxic_threshold
        self._buy_state = Decimal("0")
        self._sell_state = Decimal("0")

    def on_trade(self, *, side: str, dt_seconds: Decimal) -> HawkesIntensity:
        decay = (
            Decimal("0") if dt_seconds <= 0 else Decimal(str(exp(float(-self._beta * dt_seconds))))
        )
        self._buy_state *= decay
        self._sell_state *= decay
        if side.lower() == "buy":
            self._buy_state += self._alpha
        else:
            self._sell_state += self._alpha
        buy = self._mu + self._buy_state
        sell = self._mu + self._sell_state
        toxic = max(buy, sell) >= self._toxic_threshold
        return HawkesIntensity(buy_intensity=buy, sell_intensity=sell, toxic_flow=toxic)
