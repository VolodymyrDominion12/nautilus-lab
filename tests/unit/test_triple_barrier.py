from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.signals import SignalSide
from nautilus_lab.domain.triple_barrier import (
    BarrierTouch,
    TripleBarrierConfig,
    label_triple_barrier,
    rolling_volatility,
)

ORIGIN = datetime(2024, 1, 1, tzinfo=UTC)


def _make_bars(
    closes: list[float],
    highs: list[float] | None = None,
    lows: list[float] | None = None,
) -> list[OhlcvBar]:
    bars: list[OhlcvBar] = []
    for i, close in enumerate(closes):
        c = Decimal(str(close))
        h = Decimal(str(highs[i])) if highs else c + Decimal("1")
        low_val = Decimal(str(lows[i])) if lows else c - Decimal("1")
        bars.append(
            OhlcvBar(
                instrument_id="ETH/USDT.SIM",
                ts_utc=ORIGIN + timedelta(hours=i),
                open=c,
                high=h,
                low=low_val,
                close=c,
                volume=Decimal("100"),
            )
        )
    return bars


def test_triple_barrier_config_validation() -> None:
    with pytest.raises(ValueError, match="multiples must be > 0"):
        TripleBarrierConfig(profit_multiple=Decimal("0"))
    with pytest.raises(ValueError, match="multiples must be > 0"):
        TripleBarrierConfig(stop_multiple=Decimal("-1"))
    with pytest.raises(ValueError, match="horizon must be >= 1"):
        TripleBarrierConfig(horizon=0)


def test_rolling_volatility_edge_cases() -> None:
    bars = _make_bars([100, 102, 101, 103, 105])

    # window < 2
    assert rolling_volatility(bars, 3, window=1) is None
    # index < window
    assert rolling_volatility(bars, 1, window=3) is None
    # index >= len(bars)
    assert rolling_volatility(bars, 10, window=3) is None

    # Normal case
    vol = rolling_volatility(bars, 4, window=3)
    assert vol is not None and vol > 0

    # Constant prices -> zero variance -> None
    flat_bars = _make_bars([100, 100, 100, 100])
    assert rolling_volatility(flat_bars, 3, window=3) is None


def test_label_triple_barrier_validation_and_outcomes() -> None:
    cfg = TripleBarrierConfig(profit_multiple=Decimal("2"), stop_multiple=Decimal("1"), horizon=3)

    bars = _make_bars(
        closes=[100, 101, 102, 103, 104],
        highs=[100, 105, 102, 103, 104],
        lows=[100, 95, 101, 102, 103],
    )

    # Invalid side
    with pytest.raises(ValueError, match="BUY or SELL"):
        label_triple_barrier(bars, 0, volatility=Decimal("0.01"), config=cfg, side=SignalSide.FLAT)

    # Invalid vol
    with pytest.raises(ValueError, match="volatility must be > 0"):
        label_triple_barrier(bars, 0, volatility=Decimal("0"), config=cfg)

    # Invalid index
    assert label_triple_barrier(bars, -1, volatility=Decimal("0.01"), config=cfg) is None
    assert label_triple_barrier(bars, 10, volatility=Decimal("0.01"), config=cfg) is None

    # Stop level <= 0 (extreme stop multiple / vol)
    extreme_cfg = TripleBarrierConfig(
        profit_multiple=Decimal("1"), stop_multiple=Decimal("100"), horizon=3
    )
    assert label_triple_barrier(bars, 0, volatility=Decimal("0.02"), config=extreme_cfg) is None

    # Profit hit
    # entry at index 0 (close=100), profit_distance = 100 * 2 * 0.02 = 4 (profit_level=104)
    # bar 1 high is 105 >= 104, low is 99 > 98 -> profit hit
    res_profit = label_triple_barrier(
        _make_bars(closes=[100, 103, 101], highs=[100, 105, 102], lows=[100, 99, 100]),
        0,
        volatility=Decimal("0.02"),
        config=cfg,
        side=SignalSide.BUY,
    )
    assert res_profit is not None
    assert res_profit.is_win is True
    assert res_profit.touch is BarrierTouch.PROFIT
    assert res_profit.label == 1
    assert res_profit.bars_held == 1

    # Stop hit
    # entry 100, stop_distance = 100 * 1 * 0.02 = 2 (stop_level=98)
    res_stop = label_triple_barrier(
        _make_bars(closes=[100, 99, 100], highs=[100, 101, 101], lows=[100, 97, 98]),
        0,
        volatility=Decimal("0.02"),
        config=cfg,
        side=SignalSide.BUY,
    )
    assert res_stop is not None
    assert res_stop.is_win is False
    assert res_stop.touch is BarrierTouch.STOP
    assert res_stop.label == -1

    # Both hit in one bar -> stop wins
    res_both = label_triple_barrier(
        _make_bars(closes=[100, 100], highs=[100, 110], lows=[100, 90]),
        0,
        volatility=Decimal("0.02"),
        config=cfg,
        side=SignalSide.BUY,
    )
    assert res_both is not None
    assert res_both.touch is BarrierTouch.STOP

    # Vertical barrier (holding time cap reached)
    res_vertical = label_triple_barrier(
        _make_bars(
            closes=[100, 100.5, 100.2, 100.8],
            highs=[100, 101, 101, 101],
            lows=[100, 99.5, 99.5, 99.5],
        ),
        0,
        volatility=Decimal("0.02"),
        config=cfg,
        side=SignalSide.BUY,
    )
    assert res_vertical is not None
    assert res_vertical.touch is BarrierTouch.VERTICAL
    assert res_vertical.label == 0
    assert res_vertical.bars_held == 3

    # SELL entry test
    res_sell = label_triple_barrier(
        _make_bars(closes=[100, 95], highs=[100, 99], lows=[100, 94]),
        0,
        volatility=Decimal("0.02"),
        config=cfg,
        side=SignalSide.SELL,
    )
    assert res_sell is not None
    assert res_sell.touch is BarrierTouch.PROFIT  # price fell, which is profit for SELL
    assert res_sell.label == 1
