import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.pairs.pairs_trading import PairsTrading, _PairState
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


def _count_fits(robot: PairsTrading, pairs: list[tuple[OhlcvBar, OhlcvBar]]) -> int:
    """Run the robot and count how many ADF fits it performed."""
    calls = [0]
    original = robot._fit_state

    def spy() -> _PairState | None:
        calls[0] += 1
        return original()

    robot._fit_state = spy  # type: ignore[method-assign]
    for bar_a, bar_b in pairs:
        robot.on_bars(bar_a, bar_b)
    return calls[0]


def _never_cointegrated(count: int) -> list[tuple[OhlcvBar, OhlcvBar]]:
    """Two unrelated random walks, so the gate stays closed.

    Scaling one leg by a constant would *not* work here: it keeps the pair cointegrated
    (the hedge ratio just divides by the same factor), which is what made an earlier
    version of this helper silently test nothing.
    """
    random_a = random.Random(1)
    random_b = random.Random(2)
    origin = datetime(2024, 1, 1, tzinfo=UTC)
    price_a = price_b = 100.0
    bars: list[tuple[OhlcvBar, OhlcvBar]] = []
    for index in range(count):
        price_a += random_a.gauss(0.0, 1.0)
        price_b += random_b.gauss(0.0, 1.0)
        ts_utc = origin + timedelta(hours=index)
        bars.append(
            (
                _walk_bar("ETH/USDT.SIM", price_a, ts_utc),
                _walk_bar("BTC/USDT.SIM", price_b, ts_utc),
            )
        )
    return bars


def _walk_bar(instrument_id: str, price: float, ts_utc: datetime) -> OhlcvBar:
    close = Decimal(repr(round(price, 6)))
    return OhlcvBar(
        instrument_id=instrument_id,
        ts_utc=ts_utc,
        open=close,
        high=close + Decimal("0.1"),
        low=close - Decimal("0.1"),
        close=close,
        volume=Decimal("1"),
    )


_NEVER_LOOKBACK = 60


def test_a_failed_refit_backs_off_instead_of_probing_every_bar() -> None:
    """A closed gate must not turn `refit_every_bars` into a per-bar fit.

    Probing every bar ran an ADF fit on ~75% of bars instead of the ~4% that
    `refit_every_bars=24` implies, which is what made a rolling refit take over an hour
    per walk-forward. The threshold here is what separates the two regimes: the intended
    cadence is `bars / refit_every`, the regressed one is `bars`.
    """
    refit_every = 10
    bars = _never_cointegrated(120)
    robot = PairsTrading(
        leg_a="ETH/USDT.SIM",
        leg_b="BTC/USDT.SIM",
        params=PairsParams(
            lookback=_NEVER_LOOKBACK,
            z_entry=Decimal("1.5"),
            refit_every_bars=refit_every,
        ),
    )

    fits = _count_fits(robot, bars)

    assert fits > 0, "the robot never even tried to fit"
    assert fits <= 3 * (len(bars) // refit_every), (
        f"{fits} fits for {len(bars)} bars means the robot probes per bar rather than "
        f"per refit interval ({refit_every})"
    )


def test_refit_zero_keeps_the_legacy_per_bar_probe() -> None:
    """`refit_every_bars=0` disables the cadence, and the old timing must survive.

    With refitting switched off the robot has no other way to ever enter, so once the
    window is full it keeps probing on every bar.
    """
    bars = _never_cointegrated(120)
    robot = PairsTrading(
        leg_a="ETH/USDT.SIM",
        leg_b="BTC/USDT.SIM",
        params=PairsParams(
            lookback=_NEVER_LOOKBACK,
            z_entry=Decimal("1.5"),
            refit_every_bars=0,
        ),
    )

    fits = _count_fits(robot, bars)

    assert fits >= len(bars) - _NEVER_LOOKBACK - 1
