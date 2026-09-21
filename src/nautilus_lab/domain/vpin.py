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
    """Volume-bucket VPIN, signed by the real taker split when the bar carries it.

    The sign comes from kline field 9 (`taker_buy_base_volume`) — what aggressive
    buyers actually lifted — and only falls back to the tick rule for bars where that
    field is unknown. Buckets are still filled bar by bar: the intra-bar *sequence* of
    trades remains invisible, so this is a bar-resolution order-flow feature, not a
    reconstruction of the tape.
    """

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
        taker_buy = bar.taker_buy_base_volume
        if taker_buy is None:
            self._fill(bar.volume, buy=self._price_rule_is_buy(bar))
        else:
            self._fill_split(bar.volume, taker_buy=taker_buy)
        self._previous_close = bar.close
        return self._last

    def _fill_split(self, volume: Decimal, *, taker_buy: Decimal) -> None:
        """Pour a bar into buckets, keeping its own buy/sell ratio inside each bucket.

        The order of aggressor sides *within* a bar is not observable from klines, so
        the choice matters. Pouring the buying first and the selling afterwards would
        manufacture a fully one-sided bucket every time a bar is larger than a bucket —
        measured on ETHUSDT 1h that inflated the median VPIN of perfectly balanced flow
        from ~0.01 to 1.0, i.e. it invented toxicity that the data does not contain.
        Spreading the ratio adds no information the bar does not carry.
        """
        if volume <= 0:
            return
        taker_sell = volume - taker_buy
        remaining = volume
        while remaining > 0:
            space = self._bucket_volume - self._filled
            chunk = min(remaining, space)
            self._buy_volume += chunk * taker_buy / volume
            self._sell_volume += chunk * taker_sell / volume
            self._filled += chunk
            remaining -= chunk
            if self._filled >= self._bucket_volume:
                self._emit_bucket()

    def _fill(self, amount: Decimal, *, buy: bool) -> None:
        remaining = amount
        while remaining > 0:
            space = self._bucket_volume - self._filled
            chunk = min(remaining, space)
            if buy:
                self._buy_volume += chunk
            else:
                self._sell_volume += chunk
            self._filled += chunk
            remaining -= chunk
            if self._filled >= self._bucket_volume:
                self._emit_bucket()

    def _price_rule_is_buy(self, bar: OhlcvBar) -> bool:
        """Fallback sign for bars whose taker split is unknown (the tick rule).

        Unchanged from the original approximation: the first bar compares against its
        own open, later bars against the previous close, and a tie counts as buying —
        which is exactly what the old `signed >= 0` test did.
        """
        if self._previous_close is None:
            return bar.close >= bar.open
        return bar.close >= self._previous_close

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
