from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from nautilus_lab.domain.bars import OhlcvBar


@dataclass(frozen=True, slots=True)
class VpinState:
    value: Decimal
    bucket_filled: Decimal
    toxic: bool


class VpinModel(Protocol):
    """Common interface for volume-synchronized probability of informed trading."""

    @property
    def last(self) -> VpinState | None: ...

    def update(self, bar: OhlcvBar) -> VpinState | None: ...


def vpin_threshold(model: object) -> Decimal | None:
    """The toxic threshold of a VPIN model, when it exposes one (None for test doubles)."""
    value = getattr(model, "toxic_threshold", None)
    return value if isinstance(value, Decimal) else None


class TickVpin:
    """Volume-bucket VPIN, filled strictly tick-by-tick from AggTrades.

    This provides true order-flow toxicity without the intra-bar approximation.
    Buckets emit exactly when filled by a sequence of aggressive orders.
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
        self._last: VpinState | None = None

    @property
    def toxic_threshold(self) -> Decimal:
        """The VPIN at or above which flow counts as toxic (for the decision trace)."""
        return self._toxic_threshold

    @property
    def last(self) -> VpinState | None:
        return self._last

    def update(self, bar: OhlcvBar) -> VpinState | None:
        """No-op for compatibility. TickVpin is updated via update_from_trade."""
        return self._last

    def update_from_trade(self, *, is_buy: bool, volume: Decimal) -> None:
        if volume <= 0:
            return
        remaining = volume
        while remaining > 0:
            space = self._bucket_volume - self._filled
            chunk = min(remaining, space)
            if is_buy:
                self._buy_volume += chunk
            else:
                self._sell_volume += chunk
            self._filled += chunk
            remaining -= chunk
            if self._filled >= self._bucket_volume:
                self._emit_bucket()

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
    def toxic_threshold(self) -> Decimal:
        """The VPIN at or above which flow counts as toxic (for the decision trace)."""
        return self._toxic_threshold

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

        # Step 1: Complete any currently partially filled bucket
        if self._filled > 0:
            space = self._bucket_volume - self._filled
            chunk = min(remaining, space)
            self._buy_volume += chunk * taker_buy / volume
            self._sell_volume += chunk * taker_sell / volume
            self._filled += chunk
            remaining -= chunk
            if self._filled >= self._bucket_volume:
                self._emit_bucket()

        if remaining <= 0:
            return

        # Step 2: Full buckets within this bar have identical buy/sell proportions.
        num_full = int(remaining // self._bucket_volume)
        if num_full > 0:
            val = Decimal("0") if volume <= 0 else abs(taker_buy - taker_sell) / volume
            self._emit_full_buckets(val, num_full)
            remaining -= Decimal(num_full) * self._bucket_volume

        # Step 3: Any leftover volume starts the next partial bucket
        if remaining > 0:
            self._buy_volume = remaining * taker_buy / volume
            self._sell_volume = remaining * taker_sell / volume
            self._filled = remaining

    def _fill(self, amount: Decimal, *, buy: bool) -> None:
        if amount <= 0:
            return
        remaining = amount

        if self._filled > 0:
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

        if remaining <= 0:
            return

        num_full = int(remaining // self._bucket_volume)
        if num_full > 0:
            self._emit_full_buckets(Decimal("1"), num_full)
            remaining -= Decimal(num_full) * self._bucket_volume

        if remaining > 0:
            if buy:
                self._buy_volume = remaining
            else:
                self._sell_volume = remaining
            self._filled = remaining

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

    def _emit_full_buckets(self, value: Decimal, count: int) -> None:
        if count <= 0:
            return
        self._last = VpinState(
            value=value,
            bucket_filled=self._bucket_volume,
            toxic=value >= self._toxic_threshold,
        )
        self._buy_volume = Decimal("0")
        self._sell_volume = Decimal("0")
        self._filled = Decimal("0")


class QuantileVpin(BarVpin):
    """BarVpin з адаптивним порогом токсичності на основі rolling-квантиля IS-вікна.

    Замість фіксованого `vpin_toxic_threshold` (0.7 за замовчуванням, на ETH/USDT 1h
    ніколи не досягається), поріг обчислюється як `quantile`-й перцентиль останніх
    `lookback` завершених кошиків. Новий поріг перераховується щоразу, коли кошик
    заповнюється. До накопичення `min_buckets` завершених кошиків клас поводиться
    консервативно: `toxic=False` (тобто не торгує, як і при статичному порозі 0.7).

    Призначення: IS-дослідження нової гіпотези (spec vpin_momentum.yaml §hypothesis
    «перцентильний поріг»). Активується лише при `USE_QUANTILE_VPIN=true`; за
    замовчуванням вимкнено, і поведінка идентична `BarVpin`.

    Правила безпеки IS/OOS:
    - `lookback` обмежує вікно «пам'яті», щоб квантиль не переповзав через межу
      IS/OOS у walk-forward-прогонах. Задайте `lookback <= is_bars` при підборі.
    - Поріг НЕ підбирається на OOS: `quantile` фіксується до запуску OOS-фолду.
    """

    def __init__(
        self,
        *,
        bucket_volume: Decimal,
        quantile: Decimal = Decimal("0.90"),
        lookback: int = 500,
        min_buckets: int = 30,
    ) -> None:
        if quantile <= 0 or quantile > 1:
            raise ValueError("quantile must be in (0, 1]")
        if lookback < 1:
            raise ValueError("lookback must be >= 1")
        if min_buckets < 1:
            raise ValueError("min_buckets must be >= 1")
        # Передаємо toxic_threshold=1 (ніколи не токсично за статичним порогом);
        # реальний поріг перераховується в _emit_bucket.
        super().__init__(bucket_volume=bucket_volume, toxic_threshold=Decimal("1"))
        self._quantile = quantile
        self._lookback = lookback
        self._min_buckets = min_buckets
        self._bucket_history: list[Decimal] = []
        # Поточний адаптивний поріг (None до накопичення min_buckets кошиків).
        self._adaptive_threshold: Decimal | None = None

    @property
    def toxic_threshold(self) -> Decimal:
        """Повертає поточний адаптивний поріг або 1.0 (= не токсично) до прогріву."""
        return self._adaptive_threshold if self._adaptive_threshold is not None else Decimal("1")

    def _emit_bucket(self) -> None:
        """Заповнює кошик і перераховує поріг через rolling-квантиль."""
        total = self._buy_volume + self._sell_volume
        value = Decimal("0") if total <= 0 else abs(self._buy_volume - self._sell_volume) / total

        # Оновлюємо rolling-историю завершених кошиків.
        self._bucket_history.append(value)
        if len(self._bucket_history) > self._lookback:
            self._bucket_history.pop(0)

        # Перераховуємо поріг лише після накопичення мінімальної кількості кошиків.
        if len(self._bucket_history) >= self._min_buckets:
            sorted_h = sorted(self._bucket_history)
            # Індекс квантиля: floor(q * n), затиснутий у [0, n-1].
            idx = min(int(float(self._quantile) * len(sorted_h)), len(sorted_h) - 1)
            self._adaptive_threshold = sorted_h[idx]
            threshold = self._adaptive_threshold
        else:
            # Ще не прогрівся — консервативно: не торгуємо.
            threshold = Decimal("1")

        self._last = VpinState(
            value=value,
            bucket_filled=self._bucket_volume,
            toxic=value >= threshold,
        )
        self._buy_volume = Decimal("0")
        self._sell_volume = Decimal("0")
        self._filled = Decimal("0")

    def _emit_full_buckets(self, value: Decimal, count: int) -> None:
        """Batch-processes multiple identical full buckets in O(1) time."""
        if count <= 0:
            return

        if count >= self._lookback:
            self._bucket_history = [value] * self._lookback
        else:
            to_keep = max(0, self._lookback - count)
            self._bucket_history = self._bucket_history[-to_keep:] + [value] * count

        if len(self._bucket_history) >= self._min_buckets:
            sorted_h = sorted(self._bucket_history)
            idx = min(int(float(self._quantile) * len(sorted_h)), len(sorted_h) - 1)
            self._adaptive_threshold = sorted_h[idx]
            threshold = self._adaptive_threshold
        else:
            threshold = Decimal("1")

        self._last = VpinState(
            value=value,
            bucket_filled=self._bucket_volume,
            toxic=value >= threshold,
        )
        self._buy_volume = Decimal("0")
        self._sell_volume = Decimal("0")
        self._filled = Decimal("0")
