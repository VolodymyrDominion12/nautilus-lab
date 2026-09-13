from datetime import UTC, datetime, timedelta
from decimal import Decimal

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.regime import RegimeParams
from nautilus_lab.domain.regime_router import RegimeRouter
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


def _params() -> RegimeParams:
    return RegimeParams(
        er_period=5,
        trend_ema_period=5,
        slope_lookback=3,
        enter_trend_er=Decimal("0.40"),
        exit_trend_er=Decimal("0.20"),
        donchian_period=3,
        bb_period=5,
        bb_k=Decimal("1.5"),
    )


def test_router_flattens_on_regime_change() -> None:
    router = RegimeRouter(instrument_id="ETH/USDT.SIM", params=_params())
    for index in range(1, 20):
        router.on_bar(_bar(Decimal(100 + index), index))
    crash_signals = []
    for offset, close in enumerate((Decimal("80"), Decimal("60"), Decimal("40"), Decimal("20"))):
        crash_signals.append(router.on_bar(_bar(close, 20 + offset)))

    flats = [
        signal for signal in crash_signals if signal is not None and signal.side is SignalSide.FLAT
    ]
    assert flats
    assert flats[0].reason.startswith("regime change")


def test_router_is_silent_until_classifier_is_warm() -> None:
    router = RegimeRouter(instrument_id="ETH/USDT.SIM", params=_params())
    first = router.on_bar(_bar(Decimal("100"), 0))
    assert first is None
