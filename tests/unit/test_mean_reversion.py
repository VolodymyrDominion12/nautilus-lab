from datetime import UTC, datetime, timedelta
from decimal import Decimal

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.mean_reversion import RangeMeanReversion
from nautilus_lab.domain.signals import SignalSide


def _bar(close: Decimal, index: int) -> OhlcvBar:
    ts = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(minutes=index)
    return OhlcvBar(
        instrument_id="ETH/USDT.SIM",
        ts_utc=ts,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=Decimal("1"),
    )


def test_mean_reversion_buys_lower_band() -> None:
    robot = RangeMeanReversion(instrument_id="ETH/USDT.SIM", period=5, band_k=Decimal("1"))
    for index in range(5):
        robot.on_bar(_bar(Decimal("100"), index))
    signal = robot.on_bar(_bar(Decimal("90"), 5))

    assert signal is not None
    assert signal.side is SignalSide.BUY


def test_mean_reversion_sells_upper_band() -> None:
    robot = RangeMeanReversion(instrument_id="ETH/USDT.SIM", period=5, band_k=Decimal("1"))
    for index in range(5):
        robot.on_bar(_bar(Decimal("100"), index))
    signal = robot.on_bar(_bar(Decimal("110"), 5))

    assert signal is not None
    assert signal.side is SignalSide.SELL


def test_mean_reversion_flattens_at_mean() -> None:
    robot = RangeMeanReversion(instrument_id="ETH/USDT.SIM", period=5, band_k=Decimal("1"))
    for index in range(5):
        robot.on_bar(_bar(Decimal("100"), index))
    signal = robot.on_bar(_bar(Decimal("100"), 5))

    assert signal is not None
    assert signal.side is SignalSide.FLAT
