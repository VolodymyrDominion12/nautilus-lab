"""The coin x time panel every alpha operator works on.

Layout: one timestamp grid of T rows (bar *close*, in epoch minutes) and N symbol
columns. Each field is a float64 `T x N` array, and NaN means "unknown", never zero: a
coin before its listing or a gap in a series stays NaN all the way through.

Point-in-time conventions, the ones the catalogs use:

* a bar row `t` is known at its close;
* `funding_paid[t]` is the sum of settlements in `(t-1, t]`. A position held over bar
  `t` pays it, and its rate is known at `t`;
* `funding_last[t]` is the last settled rate at or before `t`. It is a feature;
* `premium[t]` is the premium-index close of the bar ending at `t`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]
BoolArray = npt.NDArray[np.bool_]

PRICE_FIELDS = ("close", "high", "low", "volume")
OPTIONAL_FIELDS = ("taker_buy", "funding_paid", "funding_last", "premium")


@dataclass(frozen=True)
class Panel:
    ts_min: IntArray
    symbols: tuple[str, ...]
    fields: Mapping[str, FloatArray]
    bar_minutes: int

    def __post_init__(self) -> None:
        if self.ts_min.ndim != 1:
            raise ValueError("ts_min must be one-dimensional")
        if self.ts_min.size > 1 and not bool(np.all(np.diff(self.ts_min) > 0)):
            raise ValueError("panel timestamps must be strictly increasing")
        if len(set(self.symbols)) != len(self.symbols):
            raise ValueError("panel symbols must be unique")
        shape = (self.ts_min.size, len(self.symbols))
        for name in PRICE_FIELDS:
            if name not in self.fields:
                raise ValueError(f"panel is missing required field {name!r}")
        for name, values in self.fields.items():
            if values.shape != shape:
                raise ValueError(f"field {name!r} has shape {values.shape}, expected {shape}")
        if self.bar_minutes < 1:
            raise ValueError("bar_minutes must be >= 1")

    @property
    def shape(self) -> tuple[int, int]:
        return (self.ts_min.size, len(self.symbols))

    @property
    def bars_per_year(self) -> float:
        return 365.0 * 24.0 * 60.0 / self.bar_minutes

    def has(self, name: str) -> bool:
        return name in self.fields and bool(np.isfinite(self.fields[name]).any())

    def get(self, name: str) -> FloatArray:
        try:
            return self.fields[name]
        except KeyError:
            raise KeyError(f"panel has no field {name!r}") from None

    def column(self, symbol: str) -> int:
        return self.symbols.index(symbol)

    def select_symbols(self, symbols: Sequence[str]) -> Panel:
        index = [self.column(s) for s in symbols]
        return Panel(
            ts_min=self.ts_min,
            symbols=tuple(symbols),
            fields={k: v[:, index] for k, v in self.fields.items()},
            bar_minutes=self.bar_minutes,
        )

    def datetimes(self) -> list[datetime]:
        return [datetime.fromtimestamp(int(m) * 60, tz=UTC) for m in self.ts_min]

    def years(self) -> IntArray:
        return self.ts_min.astype("datetime64[m]").astype("datetime64[Y]").astype(np.int64) + 1970


def minutes_from_ns(ts_ns: IntArray) -> IntArray:
    """Round nanosecond close stamps (`...59.999000064`) to the nearest minute."""
    return ((ts_ns + 30_000_000_000) // 60_000_000_000).astype(np.int64)


def align_columns(grid: IntArray, series: Mapping[str, tuple[IntArray, FloatArray]]) -> FloatArray:
    """Place per-symbol `(ts_min, values)` onto `grid`. Missing rows stay NaN."""
    out = np.full((grid.size, len(series)), np.nan)
    for column, (ts, values) in enumerate(series.values()):
        if ts.size == 0:
            continue
        position = np.searchsorted(grid, ts)
        inside = position < grid.size
        inside[inside] &= grid[position[inside]] == ts[inside]
        out[position[inside], column] = values[inside]
    return out


def bucket_events(
    grid: IntArray, event_min: IntArray, values: FloatArray
) -> tuple[FloatArray, FloatArray]:
    """Settlement events onto bar rows: `(sum over (t-1, t], last known at t)`.

    An event lands on the first bar whose close is at or after it, so a settlement at
    08:00 belongs to the bar closing at 08:00 and is known from that close on.
    Events after the last close are dropped, because no closed bar can know them yet.
    """
    paid = np.full(grid.size, np.nan)
    last = np.full(grid.size, np.nan)
    if event_min.size == 0 or grid.size == 0:
        return paid, last
    order = np.argsort(event_min, kind="stable")
    event_min, values = event_min[order], values[order]
    row = np.searchsorted(grid, event_min, side="left")
    keep = row < grid.size
    row, kept = row[keep], values[keep]
    sums = np.zeros(grid.size)
    np.add.at(sums, row, kept)
    seen = np.zeros(grid.size, dtype=bool)
    seen[row] = True
    paid[seen] = sums[seen]
    first = int(row.min()) if row.size else grid.size
    paid[first:][~seen[first:]] = 0.0
    # last settled rate at each row: forward-fill the final event of each row
    last_rate = np.full(grid.size, np.nan)
    # the latest event of each row wins: take the first occurrence in reversed order
    rows_unique, first_reversed = np.unique(row[::-1], return_index=True)
    last_rate[rows_unique] = kept[::-1][first_reversed]
    filled = np.where(np.isfinite(last_rate), np.arange(grid.size), -1)
    np.maximum.accumulate(filled, out=filled)
    mask = filled >= 0
    last[mask] = last_rate[filled[mask]]
    return paid, last
