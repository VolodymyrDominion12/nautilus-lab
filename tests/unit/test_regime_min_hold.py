from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.errors import InvalidRiskError
from nautilus_lab.domain.regime import RegimeParams
from nautilus_lab.domain.regime_router import RegimeRouter
from nautilus_lab.domain.signals import Signal, SignalSide


def _bar(index: int) -> OhlcvBar:
    return OhlcvBar(
        instrument_id="ETH/USDT.SIM",
        ts_utc=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=index),
        open=Decimal(100),
        high=Decimal(101),
        low=Decimal(99),
        close=Decimal(100),
        volume=Decimal(1),
    )


def _scripted(min_hold: int, sides: list[SignalSide | None]) -> list[SignalSide | None]:
    """Feed the router a scripted inner decision per bar; return what it emits."""
    router = RegimeRouter(instrument_id="ETH/USDT.SIM", params=RegimeParams(min_hold_bars=min_hold))
    script: Iterator[SignalSide | None] = iter(sides)

    def route(bar: OhlcvBar) -> Signal | None:
        side = next(script)
        if side is None:
            return None
        router._current_side = side
        return Signal(instrument_id=bar.instrument_id, side=side, bar_ts_utc=bar.ts_utc, reason="t")

    router._route_bar = route  # type: ignore[method-assign]
    out: list[SignalSide | None] = []
    for index in range(len(sides)):
        signal = router.on_bar(_bar(index))
        out.append(signal.side if signal else None)
    return out


def test_min_hold_defaults_to_off() -> None:
    assert RegimeParams().min_hold_bars == 0


def test_negative_min_hold_is_rejected() -> None:
    with pytest.raises(InvalidRiskError):
        RegimeParams(min_hold_bars=-1)


def test_exit_is_dropped_until_min_hold_then_allowed() -> None:
    buy, flat = SignalSide.BUY, SignalSide.FLAT
    # Entry, then an exit every bar: with min_hold=3 the first two exits are dropped.
    assert _scripted(3, [buy, flat, flat, flat]) == [buy, None, None, flat]


def test_without_min_hold_exits_immediately() -> None:
    buy, flat = SignalSide.BUY, SignalSide.FLAT
    assert _scripted(0, [buy, flat]) == [buy, flat]


def test_flip_is_also_held() -> None:
    buy, sell = SignalSide.BUY, SignalSide.SELL
    assert _scripted(2, [buy, sell, sell]) == [buy, None, sell]
