from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.funding import FundingSnapshot


def synthetic_funding_pair(
    *,
    spot_id: str = "ETH/USDT.SIM",
    perp_id: str = "ETHUSDT-PERP.SIM",
    count: int,
    seed: int = 42,
) -> tuple[dict[str, list[OhlcvBar]], list[FundingSnapshot]]:
    """Deterministic spot + perp bars and 8h funding rate snapshots."""
    origin = datetime(2024, 1, 1, tzinfo=UTC)
    rng = _lcg(seed)
    bars_spot: list[OhlcvBar] = []
    bars_perp: list[OhlcvBar] = []
    spot_price = Decimal("2000.00")
    snapshots: list[FundingSnapshot] = []

    for index in range(count):
        ts = origin + timedelta(hours=index)
        drift = Decimal(str((rng() % 100 - 50) / 100))
        spot_price = spot_price + drift
        basis = Decimal("0.0005")
        perp_price = (spot_price * (Decimal("1") + basis)).quantize(Decimal("0.01"))

        bar_spot = OhlcvBar(
            instrument_id=spot_id,
            ts_utc=ts,
            open=spot_price,
            high=spot_price + Decimal("1.00"),
            low=spot_price - Decimal("1.00"),
            close=spot_price,
            volume=Decimal("100"),
        )
        bar_perp = OhlcvBar(
            instrument_id=perp_id,
            ts_utc=ts,
            open=perp_price,
            high=perp_price + Decimal("1.00"),
            low=perp_price - Decimal("1.00"),
            close=perp_price,
            volume=Decimal("100"),
        )
        bars_spot.append(bar_spot)
        bars_perp.append(bar_perp)

        if index > 0 and index % 8 == 0:
            snapshots.append(
                FundingSnapshot(
                    instrument=perp_id,
                    funding_rate=Decimal("0.0003"),
                    mark_price=perp_price,
                    index_price=spot_price,
                    ts_utc=ts,
                )
            )

    return {spot_id: bars_spot, perp_id: bars_perp}, snapshots


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
