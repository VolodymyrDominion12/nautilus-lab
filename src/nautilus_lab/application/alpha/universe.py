"""Point-in-time universe for the alpha screen: monthly top-N by trailing dollar volume.

A fixed list of today's large coins only contains the survivors (docs/34, B2). It has
none of the coins that were liquid in 2021 and are gone now, and none of the 2024
listings that would have been invisible in 2021. Here membership is decided at each
month start from daily bars that closed *before* that instant:

* rank by `sum(close * volume)` over the trailing `lookback_days`;
* require `min_days` finite days in that window, so a coin listed two days ago is
  not a liquid market yet;
* break ties by symbol, so the answer never depends on dict order.

The rule is the same as `domain.universe.top_by_dollar_volume`, vectorised over a
daily panel (a unit test checks the two agree). Members of month M are the coins a
researcher at M's first second could have picked.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from nautilus_lab.application.alpha.panel import BoolArray, IntArray, Panel


@dataclass(frozen=True)
class PitUniverse:
    top_n: int
    lookback_days: int
    min_days: int
    months: tuple[tuple[str, tuple[str, ...]], ...]  # ("2021-05", members), ascending

    def ever(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for _, members in self.months:
            seen.update(dict.fromkeys(members))
        return tuple(sorted(seen))

    def mask(self, panel: Panel) -> BoolArray:
        """`T x N` membership for a panel: row t uses the month of its bar's *open*."""
        month_of_row = _month_keys(panel.ts_min - 1)
        lookup = {month: set(members) for month, members in self.months}
        out = np.zeros(panel.shape, dtype=bool)
        for month in np.unique(month_of_row):
            members = lookup.get(str(month))
            if not members:
                continue
            rows = month_of_row == month
            cols = [i for i, s in enumerate(panel.symbols) if s in members]
            if cols:
                out[np.ix_(rows, cols)] = True
        return out

    def to_json(self) -> dict[str, object]:
        return {
            "kind": "alpha-universe/v1",
            "top_n": self.top_n,
            "lookback_days": self.lookback_days,
            "min_days": self.min_days,
            "months": {month: list(members) for month, members in self.months},
            "ever": list(self.ever()),
        }


def pit_universe(
    daily: Panel, *, top_n: int = 30, lookback_days: int = 30, min_days: int = 20
) -> PitUniverse:
    if daily.bar_minutes != 1440:
        raise ValueError("pit_universe needs a daily panel")
    if top_n < 1 or min_days < 1 or lookback_days < min_days:
        raise ValueError("need top_n >= 1 and lookback_days >= min_days >= 1")
    dollar = daily.get("close") * daily.get("volume")
    ts = daily.ts_min
    if ts.size == 0:
        return PitUniverse(top_n, lookback_days, min_days, ())
    starts = _month_starts(int(ts[0]), int(ts[-1]))
    months: list[tuple[str, tuple[str, ...]]] = []
    lookback_min = lookback_days * 1440
    symbols = np.array(daily.symbols)
    for start in starts:
        # bars that closed at or before the month start, inside the lookback
        rows = (ts <= start) & (ts > start - lookback_min)
        window = dollar[rows]
        counts = np.isfinite(window).sum(axis=0)
        totals = np.where(np.isfinite(window), window, 0.0).sum(axis=0)
        eligible = (counts >= min_days) & (totals > 0)
        if not eligible.any():
            continue
        order = sorted(np.flatnonzero(eligible), key=lambda i: (-totals[i], symbols[i]))
        chosen = tuple(str(symbols[i]) for i in order[:top_n])
        key = datetime.fromtimestamp(start * 60, tz=UTC).strftime("%Y-%m")
        months.append((key, chosen))
    return PitUniverse(top_n, lookback_days, min_days, tuple(months))


def save_universe(universe: PitUniverse, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(universe.to_json(), indent=1) + "\n", encoding="utf-8")


def load_universe(path: Path) -> PitUniverse:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("kind") != "alpha-universe/v1":
        raise ValueError(f"{path} is not an alpha universe file")
    return PitUniverse(
        top_n=int(data["top_n"]),
        lookback_days=int(data["lookback_days"]),
        min_days=int(data["min_days"]),
        months=tuple((month, tuple(members)) for month, members in data["months"].items()),
    )


def _month_starts(first_min: int, last_min: int) -> list[int]:
    first = datetime.fromtimestamp(first_min * 60, tz=UTC)
    year, month = first.year, first.month
    out: list[int] = []
    while True:
        month += 1
        if month == 13:
            year, month = year + 1, 1
        start = int(datetime(year, month, 1, tzinfo=UTC).timestamp() // 60)
        if start > last_min + 31 * 1440:
            return out
        out.append(start)


def _month_keys(ts_min: IntArray) -> np.ndarray:
    months = ts_min.astype("datetime64[m]").astype("datetime64[M]")
    return np.datetime_as_string(months, unit="M")
