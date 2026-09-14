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
    # The original assertion was `any("cointegration break" in r or "refit flatten" in r)`.
    # A *successful* refit while holding a position also emits a FLAT ("refit flatten"),
    # so that disjunction was satisfied by refit churn alone and could not notice the
    # break path regressing. Demand the specific reason.
    assert "pairs cointegration break" in flat_reasons


def test_a_refit_that_fails_while_flat_does_not_crash_the_robot() -> None:
    """Regression: a failed periodic refit used to fall through into `_current_spread()`.

    `_maybe_refit` clears the state when the gate closes and returns `None`. The caller
    read that as "nothing happened", carried on to `_current_spread()`, and hit
    `assert self._state is not None` — killing the whole `pairs` run as soon as
    `refit_every_bars > 0`. This scenario trips that path repeatedly, so it fails loudly
    if the guard is ever removed again.
    """
    data = synthetic_cointegrated_pair(
        leg_a="ETH/USDT.SIM",
        leg_b="BTC/USDT.SIM",
        count=140,
        seed=1,
    )
    robot = PairsTrading(
        leg_a="ETH/USDT.SIM",
        leg_b="BTC/USDT.SIM",
        params=PairsParams(lookback=30, z_entry=Decimal("1.5"), refit_every_bars=1),
    )
    for index, (bar_a, bar_b) in enumerate(
        zip(data["ETH/USDT.SIM"], data["BTC/USDT.SIM"], strict=True)
    ):
        if index >= 35:
            bar_b = _broken_bar(bar_b)
        robot.on_bars(bar_a, bar_b)


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
