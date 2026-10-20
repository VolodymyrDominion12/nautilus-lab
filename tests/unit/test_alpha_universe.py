from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest

from nautilus_lab.application.alpha.panel import Panel
from nautilus_lab.application.alpha.screen import ScreenConfig, run_screen
from nautilus_lab.application.alpha.signals import Context, SignalSpec
from nautilus_lab.application.alpha.universe import load_universe, pit_universe, save_universe
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.data_zone import TimeWindow, ZonePolicy
from nautilus_lab.domain.universe import top_by_dollar_volume

DAY = 1440
START = datetime(2021, 1, 1, tzinfo=UTC)


def _daily(dollar: np.ndarray, symbols: tuple[str, ...]) -> Panel:
    days = dollar.shape[0]
    # daily bars close at 23:59:59.999, i.e. the next midnight on the minute grid
    ts = int(START.timestamp() // 60) + DAY * np.arange(1, days + 1, dtype=np.int64)
    close = np.ones_like(dollar)
    fields = {"close": close, "high": close, "low": close, "volume": dollar}
    return Panel(ts, symbols, fields, bar_minutes=DAY)


def test_membership_matches_the_domain_rule() -> None:
    rng = np.random.default_rng(1)
    symbols = tuple(f"C{i}USDT" for i in range(8))
    dollar = rng.uniform(1, 100, (120, 8))
    dollar[:50, 3] = np.nan  # lists late
    dollar[80:, 5] = np.nan  # delisted
    panel = _daily(dollar, symbols)
    universe = pit_universe(panel, top_n=3, lookback_days=30, min_days=20)

    bars = {
        s: [
            OhlcvBar(
                instrument_id=f"{s}.SIM",
                ts_utc=START + timedelta(days=d + 1) - timedelta(milliseconds=1),
                open=Decimal(1),
                high=Decimal(1),
                low=Decimal(1),
                close=Decimal(1),
                volume=Decimal(str(dollar[d, j])),
            )
            for d in range(dollar.shape[0])
            if np.isfinite(dollar[d, j])
        ]
        for j, s in enumerate(symbols)
    }
    for month, members in universe.months:
        as_of = datetime.strptime(month, "%Y-%m").replace(tzinfo=UTC)
        expected = top_by_dollar_volume(bars, as_of=as_of, n=3, min_bars=20)
        assert set(members) == set(expected), month


def test_a_late_listing_is_not_a_member_before_it_has_history() -> None:
    symbols = tuple(f"C{i}USDT" for i in range(4))
    dollar = np.ones((100, 4))
    dollar[:, 3] = np.nan
    dollar[45:, 3] = 1000.0  # huge volume, but only from mid-February
    universe = pit_universe(_daily(dollar, symbols), top_n=2, lookback_days=30, min_days=20)
    months = dict(universe.months)
    assert "C3USDT" not in months["2021-03"]  # 14 days of history on 1 March
    assert "C3USDT" in months["2021-04"]


def test_mask_uses_the_month_of_the_bar_open() -> None:
    universe = pit_universe(
        _daily(np.ones((70, 2)), ("AUSDT", "BUSDT")), top_n=1, lookback_days=30, min_days=20
    )
    months = dict(universe.months)
    assert months["2021-02"] == ("AUSDT",)  # tie broken by symbol
    hourly_ts = np.array(
        [
            int(datetime(2021, 3, 1, tzinfo=UTC).timestamp() // 60),
            int(datetime(2021, 3, 1, 1, tzinfo=UTC).timestamp() // 60),
        ],
        dtype=np.int64,
    )
    ones = np.ones((2, 2))
    hourly = Panel(
        hourly_ts, ("AUSDT", "BUSDT"), dict.fromkeys(("close", "high", "low", "volume"), ones), 60
    )
    mask = universe.mask(hourly)
    assert mask[0, 0]  # the bar closing at 03-01 00:00 opened in February
    assert mask[1, 0]


def test_universe_file_round_trips(tmp_path: Path) -> None:
    universe = pit_universe(_daily(np.ones((70, 2)), ("AUSDT", "BUSDT")), top_n=2, min_days=20)
    path = tmp_path / "u.json"
    save_universe(universe, path)
    assert load_universe(path) == universe
    assert universe.ever() == ("AUSDT", "BUSDT")


def test_hourly_panel_needs_daily_input() -> None:
    panel = _daily(np.ones((40, 2)), ("AUSDT", "BUSDT"))
    hourly = Panel(panel.ts_min, panel.symbols, panel.fields, 60)
    with pytest.raises(ValueError, match="daily"):
        pit_universe(hourly)


def test_screen_ignores_coins_outside_the_universe() -> None:
    """A perfect signal on a non-member must not leak into the screen."""
    rng = np.random.default_rng(4)
    bars, names = 24 * 300, 7
    returns = rng.normal(0, 0.01, (bars, names))
    close = 100 * np.cumprod(1 + returns, axis=0)
    ts = int(datetime(2020, 1, 1, tzinfo=UTC).timestamp() // 60) + 60 * np.arange(bars)
    symbols = tuple(f"C{i}USDT" for i in range(names))
    panel = Panel(
        ts.astype(np.int64),
        symbols,
        {"close": close, "high": close, "low": close, "volume": np.ones_like(close)},
        60,
    )
    future = np.full_like(close, np.nan)
    future[:-24] = close[24:] / close[:-24] - 1  # leak: knows the next day

    def leak_on_c6(_: Context) -> np.ndarray:
        out = rng.normal(size=close.shape)
        out[:, 6] = future[:, 6] * 1e3
        return out

    policy = ZonePolicy(
        exploration=(
            TimeWindow(datetime(2020, 1, 1, tzinfo=UTC), datetime(2020, 10, 1, tzinfo=UTC)),
        ),
        validation=(),
        holdout=(),
        holdout_symbol_fraction=Decimal(0),
    )
    member = np.ones(panel.shape, dtype=bool)
    member[:, 6] = False
    spec = SignalSpec("leak_c6", "test", "x", ("close",), leak_on_c6)
    cfg = ScreenConfig(horizons=(24,), permutations=20)
    without = run_screen(panel, policy=policy, config=cfg, templates=(spec,), membership=member)
    result = next(r for r in without.results if r.name == "leak_c6")
    assert abs(result.ic_mean or 1.0) < 0.03
    with pytest.raises(ValueError, match="membership shape"):
        run_screen(panel, policy=policy, config=cfg, templates=(spec,), membership=member[:10])
