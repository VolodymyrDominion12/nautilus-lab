from datetime import UTC, datetime, timedelta
from decimal import Decimal

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.donchian import DowntrendBreakout, UptrendBreakout
from nautilus_lab.domain.signals import SignalSide


def _bar(
    close: Decimal, index: int, *, high: Decimal | None = None, low: Decimal | None = None
) -> OhlcvBar:
    ts = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(minutes=index)
    return OhlcvBar(
        instrument_id="ETH/USDT.SIM",
        ts_utc=ts,
        open=close,
        high=high if high is not None else close,
        low=low if low is not None else close,
        close=close,
        volume=Decimal("1"),
    )


def test_uptrend_breakout_buys_new_high() -> None:
    robot = UptrendBreakout(instrument_id="ETH/USDT.SIM", channel_period=3, ema_period=3)
    signals = [robot.on_bar(_bar(Decimal(10 + index), index)) for index in range(6)]

    sides = [signal.side for signal in signals if signal is not None]
    assert SignalSide.BUY in sides


def test_uptrend_breakout_flattens_below_ema() -> None:
    robot = UptrendBreakout(instrument_id="ETH/USDT.SIM", channel_period=3, ema_period=3)
    for index, close in enumerate((Decimal("10"), Decimal("11"), Decimal("12"), Decimal("13"))):
        robot.on_bar(_bar(close, index))
    signal = robot.on_bar(_bar(Decimal("8"), 4))

    assert signal is not None
    assert signal.side is SignalSide.FLAT


def test_downtrend_breakout_sells_new_low() -> None:
    robot = DowntrendBreakout(instrument_id="ETH/USDT.SIM", channel_period=3, ema_period=3)
    signals = [robot.on_bar(_bar(Decimal(20 - index), index)) for index in range(6)]

    sides = [signal.side for signal in signals if signal is not None]
    assert SignalSide.SELL in sides


def test_donchian_does_not_look_ahead() -> None:
    def sides(count: int) -> list[SignalSide]:
        robot = UptrendBreakout(instrument_id="ETH/USDT.SIM", channel_period=3, ema_period=3)
        result: list[SignalSide] = []
        for index in range(count):
            close = Decimal(10 + index)
            if count == 8 and index == 7:
                close = Decimal("1000")
            signal = robot.on_bar(_bar(close, index))
            if signal is not None:
                result.append(signal.side)
        return result

    prefix = sides(7)
    assert prefix == sides(8)[: len(prefix)]
