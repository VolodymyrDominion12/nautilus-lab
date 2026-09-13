from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from random import Random

from nautilus_lab.domain.bars import OhlcvBar, validate_bar


def synthetic_ohlcv(
    *,
    instrument_id: str,
    count: int,
    seed: int,
    start: datetime | None = None,
    start_price: Decimal = Decimal("3500"),
) -> list[OhlcvBar]:
    """Deterministic random-walk bars. Validated, UTC, no future timestamps."""
    if count < 1:
        raise ValueError("count must be >= 1")
    rng = Random(seed)
    origin = start or datetime(2024, 1, 1, tzinfo=UTC)
    now = datetime(2024, 12, 31, tzinfo=UTC)
    price = start_price
    bars: list[OhlcvBar] = []
    previous_ts: datetime | None = None
    for index in range(count):
        ts = origin + timedelta(minutes=index)
        tick = Decimal("0.01")
        delta = Decimal(str(rng.uniform(-0.003, 0.003)))
        open_px = price.quantize(tick)
        close_px = _positive(open_px * (Decimal("1") + delta)).quantize(tick)
        wick = Decimal(str(rng.uniform(0, 0.0015))).quantize(tick)
        high = (max(open_px, close_px) + wick).quantize(tick)
        low = (min(open_px, close_px) - wick).quantize(tick)
        if low <= 0:
            low = tick
        bar = OhlcvBar(
            instrument_id=instrument_id,
            ts_utc=ts,
            open=open_px,
            high=high,
            low=low,
            close=close_px,
            volume=Decimal("10"),
        )
        validate_bar(bar, previous_ts=previous_ts, now=now)
        bars.append(bar)
        previous_ts = ts
        price = close_px
    return bars


def _positive(value: Decimal) -> Decimal:
    return value if value > 0 else Decimal("0.01")
