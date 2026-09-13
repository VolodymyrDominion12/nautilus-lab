from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from nautilus_lab.domain.ema import ExponentialMovingAverage
from nautilus_lab.domain.ema_crossover import EmaCrossover
from nautilus_lab.domain.signals import SignalSide


def test_ema_rejects_non_positive_price() -> None:
    avg = ExponentialMovingAverage(2)
    with pytest.raises(ValueError, match="price"):
        avg.update(Decimal("0"))


def test_ema_rejects_invalid_period() -> None:
    with pytest.raises(ValueError, match="period"):
        ExponentialMovingAverage(0)


def test_ema_crossover_requires_fast_slower_than_slow() -> None:
    with pytest.raises(ValueError, match="fast_period"):
        EmaCrossover(instrument_id="ETH/USDT.SIM", fast_period=20, slow_period=10)


def test_ema_is_silent_until_slow_period_warms_up() -> None:
    robot = EmaCrossover(instrument_id="ETH/USDT.SIM", fast_period=2, slow_period=3)
    ts = datetime(2024, 1, 1, tzinfo=UTC)

    first = robot.on_close(close=Decimal("10"), bar_ts_utc=ts)
    second = robot.on_close(close=Decimal("11"), bar_ts_utc=ts + timedelta(minutes=1))

    assert first is None
    assert second is None


def test_ema_cross_emits_sell_when_fast_is_below_slow() -> None:
    robot = EmaCrossover(instrument_id="ETH/USDT.SIM", fast_period=2, slow_period=3)
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    robot.on_close(close=Decimal("12"), bar_ts_utc=ts)
    robot.on_close(close=Decimal("11"), bar_ts_utc=ts + timedelta(minutes=1))
    signal = robot.on_close(close=Decimal("8"), bar_ts_utc=ts + timedelta(minutes=2))

    assert signal is not None
    assert signal.side is SignalSide.SELL


def test_ema_cross_emits_buy_when_fast_is_above_slow() -> None:
    robot = EmaCrossover(instrument_id="ETH/USDT.SIM", fast_period=2, slow_period=3)
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    robot.on_close(close=Decimal("10"), bar_ts_utc=ts)
    robot.on_close(close=Decimal("11"), bar_ts_utc=ts + timedelta(minutes=1))
    signal = robot.on_close(close=Decimal("12"), bar_ts_utc=ts + timedelta(minutes=2))

    assert signal is not None
    assert signal.side is SignalSide.BUY
    assert signal.instrument_id == "ETH/USDT.SIM"


def test_ema_does_not_look_ahead() -> None:
    prices = [Decimal("10"), Decimal("11"), Decimal("12"), Decimal("13"), Decimal("9")]
    start = datetime(2024, 1, 1, tzinfo=UTC)

    def replay(count: int) -> list[SignalSide]:
        robot = EmaCrossover(instrument_id="ETH/USDT.SIM", fast_period=2, slow_period=3)
        sides: list[SignalSide] = []
        for index, price in enumerate(prices[:count]):
            signal = robot.on_close(close=price, bar_ts_utc=start + timedelta(minutes=index))
            if signal is not None:
                sides.append(signal.side)
        return sides

    prefix = replay(4)
    with_future = replay(5)[:-1]

    assert prefix == with_future
