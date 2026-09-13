from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from nautilus_lab.domain.bars import OhlcvBar


def synthetic_cointegrated_pair(
    *,
    leg_a: str,
    leg_b: str,
    count: int,
    seed: int = 42,
) -> dict[str, list[OhlcvBar]]:
    """Deterministic cointegrated pair for unit/integration tests."""
    origin = datetime(2024, 1, 1, tzinfo=UTC)
    rng = _lcg(seed)
    bars_a: list[OhlcvBar] = []
    bars_b: list[OhlcvBar] = []
    price_b = Decimal("65000")
    spread = Decimal("0")
    for index in range(count):
        shock = Decimal(str((rng() % 200 - 100) / 10000))
        spread = spread * Decimal("0.95") + shock
        price_b = price_b + Decimal(str((rng() % 100 - 50) / 100))
        price_a = Decimal("15") * price_b + spread
        ts = origin + timedelta(hours=index)
        for instrument_id, close in ((leg_a, price_a), (leg_b, price_b)):
            bar = OhlcvBar(
                instrument_id=instrument_id,
                ts_utc=ts,
                open=close,
                high=close + Decimal("1"),
                low=close - Decimal("1"),
                close=close,
                volume=Decimal("100"),
            )
            if instrument_id == leg_a:
                bars_a.append(bar)
            else:
                bars_b.append(bar)
    return {leg_a: bars_a, leg_b: bars_b}


def _lcg(seed: int) -> Callable[[], int]:
    state = seed

    def next_int() -> int:
        nonlocal state
        state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
        return state

    return next_int
