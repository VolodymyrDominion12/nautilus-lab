"""REGIME_LEGS: a disabled leg's entries are dropped and logged, its exits pass (docs/31)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from nautilus_lab.domain.decision_trace import Verdict
from nautilus_lab.domain.regime import MarketRegime
from nautilus_lab.domain.regime_router import ALL_LEGS, gate_leg, parse_legs
from nautilus_lab.domain.signals import Signal, SignalSide

TS = datetime(2026, 7, 1, tzinfo=UTC)


def _signal(side: SignalSide) -> Signal:
    return Signal(instrument_id="BTC/USDT.SIM", side=side, bar_ts_utc=TS, reason="test")


def test_parse_legs_defaults_to_all_and_rejects_typos() -> None:
    assert parse_legs("") == ALL_LEGS
    assert parse_legs(None) == ALL_LEGS
    assert parse_legs(" Uptrend , range ") == {MarketRegime.UPTREND, MarketRegime.RANGE}
    with pytest.raises(ValueError, match="unknown regime leg"):
        parse_legs("uptrend,short")


def test_enabled_leg_is_untouched() -> None:
    signal = _signal(SignalSide.SELL)
    out, steps = gate_leg("R", regime=MarketRegime.DOWNTREND, signal=signal, legs=ALL_LEGS)
    assert out is signal
    assert steps == ()


def test_disabled_leg_entry_is_dropped_and_logged() -> None:
    legs = parse_legs("uptrend,range")
    out, (note,) = gate_leg(
        "R", regime=MarketRegime.DOWNTREND, signal=_signal(SignalSide.SELL), legs=legs
    )
    assert out is None
    assert note.verdict is Verdict.BLOCK
    assert "downtrend leg disabled" in (note.result or "")


def test_disabled_leg_exit_still_passes() -> None:
    legs = parse_legs("uptrend,downtrend")
    flat = _signal(SignalSide.FLAT)
    out, (note,) = gate_leg("R", regime=MarketRegime.RANGE, signal=flat, legs=legs)
    assert out is flat
    assert note.verdict is Verdict.INFO
