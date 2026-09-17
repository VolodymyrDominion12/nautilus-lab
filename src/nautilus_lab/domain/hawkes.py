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
        cross_alpha: Decimal = Decimal("0.0"),
        toxic_threshold: Decimal = Decimal("2.0"),
    ) -> None:
        self._mu = baseline
        self._alpha = alpha
        self._beta = beta
        self._cross_alpha = cross_alpha
        self._toxic_threshold = toxic_threshold
        self._buy_state = Decimal("0")
        self._sell_state = Decimal("0")

    def update(
        self,
        *,
        buy_volume: Decimal = Decimal("0"),
        sell_volume: Decimal = Decimal("0"),
        dt_seconds: Decimal,
    ) -> HawkesIntensity:
        decay = (
            Decimal("0") if dt_seconds <= 0 else Decimal(str(exp(float(-self._beta * dt_seconds))))
        )
        self._buy_state *= decay
        self._sell_state *= decay
        self._buy_state += self._alpha * buy_volume + self._cross_alpha * sell_volume
        self._sell_state += self._alpha * sell_volume + self._cross_alpha * buy_volume
        buy = self._mu + self._buy_state
        sell = self._mu + self._sell_state
        toxic = max(buy, sell) >= self._toxic_threshold
        return HawkesIntensity(buy_intensity=buy, sell_intensity=sell, toxic_flow=toxic)

    def on_trade(
        self, *, side: str, volume: Decimal = Decimal("1"), dt_seconds: Decimal
    ) -> HawkesIntensity:
        if side.lower() == "buy":
            return self.update(buy_volume=volume, dt_seconds=dt_seconds)
        else:
            return self.update(sell_volume=volume, dt_seconds=dt_seconds)
