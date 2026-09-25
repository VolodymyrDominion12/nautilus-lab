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
    rng = Random(seed)  # noqa: S311 — seeded test data, reproducibility is the point
    origin = start or datetime(2024, 1, 1, tzinfo=UTC)
    price = start_price
    bars: list[OhlcvBar] = []
    previous_ts: datetime | None = None
    for index in range(count):
        noise = Decimal(str(rng.uniform(-0.003, 0.003)))
        wick = Decimal(str(rng.uniform(0, 0.0015)))
        bar, price = _next_bar(
            instrument_id=instrument_id,
            ts=origin + timedelta(minutes=index),
            open_px=price,
            return_pct=noise,
            wick=wick,
            previous_ts=previous_ts,
        )
        bars.append(bar)
        previous_ts = bar.ts_utc
    return bars


def synthetic_regime_ohlcv(
    *,
    instrument_id: str,
    count: int,
    seed: int,
    start: datetime | None = None,
    start_price: Decimal = Decimal("3500"),
) -> list[OhlcvBar]:
    """Up trend, then range, then down trend — enough structure for regime tests."""
    if count < 3:
        raise ValueError("count must be >= 3")
    rng = Random(seed)  # noqa: S311 — seeded test data, reproducibility is the point
    origin = start or datetime(2024, 1, 1, tzinfo=UTC)
    third = count // 3
    segments = (
        ("up", third),
        ("range", third),
        ("down", count - 2 * third),
    )
    price = start_price
    range_center = start_price
    bars: list[OhlcvBar] = []
    previous_ts: datetime | None = None
    index = 0
    for kind, length in segments:
        if kind == "range":
            range_center = price
        for _ in range(length):
            if kind == "up":
                drift = Decimal("0.0018") + Decimal(str(rng.uniform(-0.0004, 0.0004)))
            elif kind == "down":
                drift = Decimal("-0.0018") + Decimal(str(rng.uniform(-0.0004, 0.0004)))
            else:
                reversion = (range_center - price) / price * Decimal("0.15")
                drift = reversion + Decimal(str(rng.uniform(-0.0008, 0.0008)))
            wick = Decimal(str(rng.uniform(0, 0.0012)))
            bar, price = _next_bar(
                instrument_id=instrument_id,
                ts=origin + timedelta(minutes=index),
                open_px=price,
                return_pct=drift,
                wick=wick,
                previous_ts=previous_ts,
            )
            bars.append(bar)
            previous_ts = bar.ts_utc
            index += 1
    return bars


def _next_bar(
    *,
    instrument_id: str,
    ts: datetime,
    open_px: Decimal,
    return_pct: Decimal,
    wick: Decimal,
    previous_ts: datetime | None,
) -> tuple[OhlcvBar, Decimal]:
    tick = Decimal("0.01")
    open_px = open_px.quantize(tick)
    close_px = _positive(open_px * (Decimal("1") + return_pct)).quantize(tick)
    wick = wick.quantize(tick)
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
    validate_bar(bar, previous_ts=previous_ts, now=datetime(2024, 12, 31, tzinfo=UTC))
    return bar, close_px


def _positive(value: Decimal) -> Decimal:
    return value if value > 0 else Decimal("0.01")
