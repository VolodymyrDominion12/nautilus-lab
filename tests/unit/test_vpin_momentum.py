from datetime import UTC, datetime, timedelta
from decimal import Decimal

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.signals import SignalSide
from nautilus_lab.domain.vpin import BarVpin
from nautilus_lab.domain.vpin_momentum import VpinMomentum


def _bars(closes: list[str]) -> list[OhlcvBar]:
    origin = datetime(2024, 1, 1, tzinfo=UTC)
    return [
        OhlcvBar(
            instrument_id="ETH/USDT.SIM",
            ts_utc=origin + timedelta(hours=index),
            open=Decimal(close),
            high=Decimal(close) + Decimal("1"),
            low=Decimal(close) - Decimal("1"),
            close=Decimal(close),
            volume=Decimal("100"),
        )
        for index, close in enumerate(closes)
    ]


def test_no_signal_while_indicators_warm_up() -> None:
    vpin = BarVpin(bucket_volume=Decimal("100"), toxic_threshold=Decimal("0.6"))
    robot = VpinMomentum(
        instrument_id="ETH/USDT.SIM",
        vpin=vpin,
        ema_period=5,
        atr_period=3,
    )
    bars = _bars(["100", "101"])
    assert [robot.on_bar(bar) for bar in bars] == [None, None]


def test_enters_long_on_toxic_upward_flow() -> None:
    vpin = BarVpin(bucket_volume=Decimal("100"), toxic_threshold=Decimal("0.6"))
    robot = VpinMomentum(
        instrument_id="ETH/USDT.SIM",
        vpin=vpin,
        ema_period=2,
        atr_period=1,
        min_hold_bars=0,
    )
    signals = [robot.on_bar(bar) for bar in _bars(["100", "101", "102", "103", "104"])]
    sides = [signal.side for signal in signals if signal is not None]
    assert SignalSide.BUY in sides


def test_exits_when_price_loses_the_ema() -> None:
    vpin = BarVpin(bucket_volume=Decimal("100"), toxic_threshold=Decimal("0.6"))
    robot = VpinMomentum(
        instrument_id="ETH/USDT.SIM",
        vpin=vpin,
        ema_period=2,
        atr_period=1,
        min_hold_bars=0,
    )
    sides = []
    for bar in _bars(["100", "110", "120", "130", "100", "90"]):
        signal = robot.on_bar(bar)
        if signal is not None:
            sides.append(signal.side)
    assert SignalSide.FLAT in sides
