from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.chandelier_stop import (
    ChandelierParams,
    initial_chandelier,
    step_chandelier,
    update_chandelier,
)
from nautilus_lab.domain.errors import InvalidRiskError
from nautilus_lab.domain.signals import SignalSide


def _bar(high: str, low: str, close: str) -> OhlcvBar:
    return OhlcvBar(
        instrument_id="ETH/USDT.SIM",
        ts_utc=datetime.now(UTC),
        open=Decimal(low),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("10"),
    )


def test_chandelier_params_validation() -> None:
    with pytest.raises(InvalidRiskError, match="atr_multiple"):
        ChandelierParams(atr_multiple=Decimal("0"))
    with pytest.raises(InvalidRiskError, match="atr_multiple"):
        ChandelierParams(atr_multiple=Decimal("-1.5"))
    with pytest.raises(InvalidRiskError, match="lookback"):
        ChandelierParams(lookback=0)
    params = ChandelierParams(atr_multiple=Decimal("2.5"), lookback=14)
    assert params.atr_multiple == Decimal("2.5")
    assert params.lookback == 14


def test_initial_chandelier_long_and_short() -> None:
    params = ChandelierParams(atr_multiple=Decimal("3.0"), lookback=22)

    # Long entry at 100, ATR = 2 -> offset = 6 -> stop = 94
    long_state = initial_chandelier(
        entry_price=Decimal("100"),
        side=SignalSide.BUY,
        atr=Decimal("2"),
        params=params,
    )
    assert long_state.side is SignalSide.BUY
    assert long_state.entry_price == Decimal("100")
    assert long_state.stop_price == Decimal("94")
    assert long_state.extreme == Decimal("100")

    # Short entry at 100, ATR = 2 -> offset = 6 -> stop = 106
    short_state = initial_chandelier(
        entry_price=Decimal("100"),
        side=SignalSide.SELL,
        atr=Decimal("2"),
        params=params,
    )
    assert short_state.side is SignalSide.SELL
    assert short_state.entry_price == Decimal("100")
    assert short_state.stop_price == Decimal("106")
    assert short_state.extreme == Decimal("100")


def test_initial_chandelier_anchors_to_lookback_extreme() -> None:
    params = ChandelierParams(atr_multiple=Decimal("2.0"), lookback=22)

    # Long with prior lookback high of 105: stop = 105 - 2*2 = 101,
    # but <= entry_price(100) -> 100 - 4 = 96
    long_state = initial_chandelier(
        entry_price=Decimal("100"),
        side=SignalSide.BUY,
        atr=Decimal("2"),
        params=params,
        lookback_extreme=Decimal("105"),
    )
    assert long_state.stop_price == Decimal("96")
    assert long_state.extreme == Decimal("105")


def test_initial_chandelier_rejects_invalid_inputs() -> None:
    params = ChandelierParams()
    with pytest.raises(InvalidRiskError, match="entry_price"):
        initial_chandelier(
            entry_price=Decimal("0"),
            side=SignalSide.BUY,
            atr=Decimal("2"),
            params=params,
        )
    with pytest.raises(InvalidRiskError, match="chandelier only applies"):
        initial_chandelier(
            entry_price=Decimal("100"),
            side=SignalSide.FLAT,
            atr=Decimal("2"),
            params=params,
        )
    with pytest.raises(InvalidRiskError, match="atr"):
        initial_chandelier(
            entry_price=Decimal("100"),
            side=SignalSide.BUY,
            atr=Decimal("0"),
            params=params,
        )


def test_chandelier_never_loosens_on_adverse_moves() -> None:
    params = ChandelierParams(atr_multiple=Decimal("3.0"), lookback=22)

    # Long entry at 100, ATR = 2 -> stop = 94
    state = initial_chandelier(
        entry_price=Decimal("100"),
        side=SignalSide.BUY,
        atr=Decimal("2"),
        params=params,
    )
    assert state.stop_price == Decimal("94")

    # Bar 1: Price goes up to High=110, Close=108 -> stop tightens to 110 - 6 = 104
    bar1 = _bar(high="110", low="99", close="108")
    state = update_chandelier(state, bar1, atr=Decimal("2"), params=params)
    assert state.stop_price == Decimal("104")
    assert state.extreme == Decimal("110")

    # Bar 2: Adverse pullback to High=105, Low=98, Close=99. Stop MUST NOT LOOSEN!
    bar2 = _bar(high="105", low="98", close="99")
    state = update_chandelier(state, bar2, atr=Decimal("2"), params=params)
    assert state.stop_price == Decimal("104"), "Stop must never loosen on pullback"
    assert state.extreme == Decimal("110")

    # Bar 3: Volatility spikes (ATR=4), High=106. Candidate = 110 - 3*4 = 98 < 104 -> stays 104!
    bar3 = _bar(high="106", low="100", close="102")
    state = update_chandelier(state, bar3, atr=Decimal("4"), params=params)
    assert state.stop_price == Decimal("104"), "Stop must never loosen even when ATR expands"


def test_chandelier_short_tightens_and_never_loosens() -> None:
    params = ChandelierParams(atr_multiple=Decimal("3.0"), lookback=22)

    # Short entry at 100, ATR = 2 -> stop = 106
    state = initial_chandelier(
        entry_price=Decimal("100"),
        side=SignalSide.SELL,
        atr=Decimal("2"),
        params=params,
    )
    assert state.stop_price == Decimal("106")

    # Bar 1: Price drops to Low=90, Close=92 -> candidate = 90 + 6 = 96 < 106 -> tightens to 96
    bar1 = _bar(high="101", low="90", close="92")
    state = update_chandelier(state, bar1, atr=Decimal("2"), params=params)
    assert state.stop_price == Decimal("96")
    assert state.extreme == Decimal("90")

    # Bar 2: Bounce to High=98, Low=93. Stop must not loosen upwards!
    bar2 = _bar(high="98", low="93", close="97")
    state = update_chandelier(state, bar2, atr=Decimal("2"), params=params)
    assert state.stop_price == Decimal("96")


def test_step_chandelier_triggers_stop_hit() -> None:
    params = ChandelierParams(atr_multiple=Decimal("3.0"), lookback=22)

    # Long entry at 100, stop = 94
    state = initial_chandelier(
        entry_price=Decimal("100"),
        side=SignalSide.BUY,
        atr=Decimal("2"),
        params=params,
    )

    # Bar holding above 94, high reaches 103 -> stop tightens to 103 - 6 = 97.0
    bar_ok = _bar(high="103", low="96", close="101")
    new_state, hit = step_chandelier(state, bar_ok, atr=Decimal("2"), params=params)
    assert not hit
    assert new_state is not None
    assert new_state.stop_price == Decimal("97.0")

    # Bar touching 97 (Low = 96.5) -> stop hit!
    bar_hit = _bar(high="101", low="96.5", close="98")
    terminal_state, hit = step_chandelier(new_state, bar_hit, atr=Decimal("2"), params=params)
    assert hit
    assert terminal_state is None


def test_risk_overlay_chandelier_params() -> None:
    from nautilus_lab.domain.risk_overlay import RiskOverlay

    overlay = RiskOverlay(
        use_chandelier_stop=True,
        chandelier_atr_multiple=Decimal("2.5"),
        chandelier_lookback=14,
    )
    params = overlay.chandelier_params()
    assert params.atr_multiple == Decimal("2.5")
    assert params.lookback == 14


def test_risk_overlay_chandelier_validation() -> None:
    from nautilus_lab.domain.risk_overlay import RiskOverlay

    with pytest.raises(InvalidRiskError, match="chandelier_atr_multiple"):
        RiskOverlay(chandelier_atr_multiple=Decimal("0"))

    with pytest.raises(InvalidRiskError, match="chandelier_lookback"):
        RiskOverlay(chandelier_lookback=0)


def test_risk_overlay_repr_backward_compatibility() -> None:
    from nautilus_lab.domain.risk_overlay import RiskOverlay

    default_overlay = RiskOverlay()
    # Must match legacy repr when use_chandelier_stop is False to preserve preregistration hash
    assert "use_chandelier_stop" not in repr(default_overlay)

    enabled_overlay = RiskOverlay(use_chandelier_stop=True)
    assert "use_chandelier_stop=True" in repr(enabled_overlay)


def test_settings_chandelier_wiring() -> None:
    from nautilus_lab.infrastructure.settings import Settings

    settings = Settings(
        use_chandelier_stop=True,
        chandelier_atr_multiple=Decimal("2.8"),
        chandelier_lookback=18,
    )
    overlay = settings.risk_overlay()
    assert overlay.use_chandelier_stop is True
    assert overlay.chandelier_atr_multiple == Decimal("2.8")
    assert overlay.chandelier_lookback == 18
