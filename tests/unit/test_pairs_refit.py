from decimal import Decimal

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.pairs.pairs_trading import PairsTrading
from nautilus_lab.domain.pairs.params import PairsParams
from nautilus_lab.domain.signals import SignalSide
from nautilus_lab.infrastructure.nautilus.synthetic_pairs import synthetic_cointegrated_pair


def test_pairs_refit_zero_preserves_legacy_freeze() -> None:
    data = synthetic_cointegrated_pair(
        leg_a="ETH/USDT.SIM",
        leg_b="BTC/USDT.SIM",
        count=250,
        seed=1,
    )
    robot = PairsTrading(
        leg_a="ETH/USDT.SIM",
        leg_b="BTC/USDT.SIM",
        params=PairsParams(lookback=120, z_entry=Decimal("1.5"), refit_every_bars=0),
    )
    signals = 0
    for bar_a, bar_b in zip(data["ETH/USDT.SIM"], data["BTC/USDT.SIM"], strict=True):
        if robot.on_bars(bar_a, bar_b) is not None:
            signals += 1
    assert signals > 0


def test_pairs_refit_emits_flat_on_cointegration_break() -> None:
    data = synthetic_cointegrated_pair(
        leg_a="ETH/USDT.SIM",
        leg_b="BTC/USDT.SIM",
        count=300,
        seed=5,
    )
    robot = PairsTrading(
        leg_a="ETH/USDT.SIM",
        leg_b="BTC/USDT.SIM",
        params=PairsParams(lookback=120, z_entry=Decimal("1.5"), refit_every_bars=5),
    )
    flat_reasons: list[str] = []
    for index, (bar_a, bar_b) in enumerate(
        zip(data["ETH/USDT.SIM"], data["BTC/USDT.SIM"], strict=True)
    ):
        if index > 200:
            bar_b = _broken_bar(bar_b)
        signal = robot.on_bars(bar_a, bar_b)
        if signal is not None and signal.leg_a.side is SignalSide.FLAT:
            flat_reasons.append(signal.reason)
    assert any(
        "cointegration break" in reason or "refit flatten" in reason for reason in flat_reasons
    )


def _broken_bar(bar: OhlcvBar) -> OhlcvBar:
    shock = bar.close * Decimal("50")
    return OhlcvBar(
        instrument_id=bar.instrument_id,
        ts_utc=bar.ts_utc,
        open=shock,
        high=shock + Decimal("1"),
        low=shock - Decimal("1"),
        close=shock,
        volume=bar.volume,
    )
