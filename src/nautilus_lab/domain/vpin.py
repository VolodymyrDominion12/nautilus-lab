from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from nautilus_lab.domain.bars import OhlcvBar


@dataclass(frozen=True, slots=True)
class VpinState:
    value: Decimal
    bucket_filled: Decimal
    toxic: bool


class BarVpin:
    """Bar-level VPIN approximation using volume buckets and tick-rule signed volume."""

    def __init__(
        self,
        *,
        bucket_volume: Decimal,
        toxic_threshold: Decimal = Decimal("0.7"),
    ) -> None:
        if bucket_volume <= 0:
            raise ValueError("bucket_volume must be > 0")
        if toxic_threshold <= 0 or toxic_threshold > 1:
            raise ValueError("toxic_threshold must be in (0, 1]")
        self._bucket_volume = bucket_volume
        self._toxic_threshold = toxic_threshold
        self._buy_volume = Decimal("0")
        self._sell_volume = Decimal("0")
        self._filled = Decimal("0")
        self._previous_close: Decimal | None = None
        self._last: VpinState | None = None

    @property
    def last(self) -> VpinState | None:
        return self._last

    def update(self, bar: OhlcvBar) -> VpinState | None:
        signed = self._signed_volume(bar)
        remaining = bar.volume
        while remaining > 0:
            space = self._bucket_volume - self._filled
            chunk = min(remaining, space)
            if signed >= 0:
                self._buy_volume += chunk
            else:
                self._sell_volume += chunk
            self._filled += chunk
            remaining -= chunk
            if self._filled >= self._bucket_volume:
                self._emit_bucket()
        self._previous_close = bar.close
        return self._last

    def _signed_volume(self, bar: OhlcvBar) -> Decimal:
        if self._previous_close is None:
            return bar.volume if bar.close >= bar.open else -bar.volume
        if bar.close > self._previous_close:
            return bar.volume
        if bar.close < self._previous_close:
            return -bar.volume
        return Decimal("0")

    def _emit_bucket(self) -> None:
        total = self._buy_volume + self._sell_volume
        value = Decimal("0") if total <= 0 else abs(self._buy_volume - self._sell_volume) / total
        self._last = VpinState(
            value=value,
            bucket_filled=self._bucket_volume,
            toxic=value >= self._toxic_threshold,
        )
        self._buy_volume = Decimal("0")
        self._sell_volume = Decimal("0")
        self._filled = Decimal("0")
