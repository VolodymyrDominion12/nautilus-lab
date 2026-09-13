from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.risk import RiskLimits


@pytest.fixture
def default_limits() -> RiskLimits:
    return RiskLimits(
        risk_per_trade=Decimal("0.005"),
        stop_pct=Decimal("0.01"),
        max_daily_loss=Decimal("0.02"),
        max_drawdown=Decimal("0.06"),
    )


def make_bars(
    count: int, *, start: datetime | None = None, step_minutes: int = 60
) -> list[OhlcvBar]:
    origin = start or datetime(2024, 1, 1, tzinfo=UTC)
    bars: list[OhlcvBar] = []
    price = Decimal("3500")
    for index in range(count):
        close = price + Decimal(index)
        bars.append(
            OhlcvBar(
                instrument_id="ETH/USDT.SIM",
                ts_utc=origin + timedelta(minutes=step_minutes * index),
                open=price,
                high=close + Decimal("1"),
                low=price - Decimal("1"),
                close=close,
                volume=Decimal("10"),
            )
        )
        price = close
    return bars
