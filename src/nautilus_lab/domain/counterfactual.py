"""Deterministic price perturbation for anti-mirage checks.

A recipe that memorised a historical path should collapse when closes are
gently shocked. The shock is seeded and point-in-time: bar i only depends on
returns up to i. Never used on the hot path.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.errors import InvalidBarError


def perturb_bars(
    bars: Sequence[OhlcvBar],
    *,
    magnitude: Decimal,
    seed: int = 1,
) -> list[OhlcvBar]:
    """Rebuild the series with each return multiplied by `(1 + magnitude * noise)`.

    `magnitude` is a fraction (0.02 = ±2% shock on each bar's return). OHLC
    invariants are restored so `validate_bar` still accepts the result.
    """
    if magnitude < 0:
        raise ValueError("magnitude must be >= 0")
    if not bars:
        return []
    closes = _shocked_closes([item.close for item in bars], magnitude=magnitude, seed=seed)
    return [
        _rebuild_bar(original, close=close) for original, close in zip(bars, closes, strict=True)
    ]


def _shocked_closes(
    closes: Sequence[Decimal],
    *,
    magnitude: Decimal,
    seed: int,
) -> list[Decimal]:
    if not closes:
        return []
    shocked = [closes[0]]
    for index in range(1, len(closes)):
        previous = closes[index - 1]
        current = closes[index]
        if previous <= 0:
            shocked.append(current)
            continue
        raw_return = (current - previous) / previous
        noise = _unit_noise(seed, index)
        shocked_return = raw_return * (Decimal("1") + magnitude * noise)
        next_close = shocked[-1] * (Decimal("1") + shocked_return)
        if next_close <= 0:
            next_close = shocked[-1]
        shocked.append(next_close)
    return shocked


def _rebuild_bar(original: OhlcvBar, *, close: Decimal) -> OhlcvBar:
    if original.close <= 0:
        raise InvalidBarError("original close must be > 0 to perturb")
    scale = close / original.close
    open_ = original.open * scale
    high = original.high * scale
    low = original.low * scale
    # Keep the candle internally consistent after scaling.
    high = max(high, open_, close)
    low = min(low, open_, close)
    return OhlcvBar(
        instrument_id=original.instrument_id,
        ts_utc=original.ts_utc,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=original.volume,
    )


def _unit_noise(seed: int, index: int) -> Decimal:
    """Deterministic value in (-1, 1). No `random` — domain stays pure."""
    mixed = abs(seed * 1_000_003 + index * 97) % 10_000
    return (Decimal(mixed) / Decimal("5000")) - Decimal("1")
