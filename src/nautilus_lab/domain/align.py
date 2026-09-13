from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.errors import InvalidWindowError
from nautilus_lab.domain.walk_forward import (
    WalkForwardSplit,
    WalkForwardWindow,
    split_by_window,
)


def align_bars_inner_join(
    series: Mapping[str, Sequence[OhlcvBar]],
) -> dict[str, tuple[OhlcvBar, ...]]:
    """Inner-join multiple bar series on UTC timestamp. No look-ahead."""
    if not series:
        raise InvalidWindowError("need at least one instrument series")
    keys = tuple(series.keys())
    if len(keys) == 1:
        only = tuple(series[keys[0]])
        return {keys[0]: only}

    timestamp_sets: list[set[datetime]] = []
    for instrument_id in keys:
        bars = series[instrument_id]
        if not bars:
            raise InvalidWindowError(f"empty bar series for {instrument_id}")
        timestamp_sets.append({bar.ts_utc for bar in bars})

    common = set.intersection(*timestamp_sets)
    if not common:
        raise InvalidWindowError("no overlapping timestamps across instruments")

    ordered_ts = sorted(common)
    aligned: dict[str, tuple[OhlcvBar, ...]] = {}
    for instrument_id in keys:
        by_ts = {bar.ts_utc: bar for bar in series[instrument_id]}
        aligned[instrument_id] = tuple(by_ts[ts] for ts in ordered_ts)
    return aligned


def split_aligned_by_window(
    bars_by_instrument: dict[str, list[OhlcvBar]],
    window: WalkForwardWindow,
) -> tuple[dict[str, list[OhlcvBar]], dict[str, list[OhlcvBar]]]:
    """Split all instruments using the same timestamp window from the first series."""
    if not bars_by_instrument:
        raise InvalidWindowError("no instruments to split")
    reference = next(iter(bars_by_instrument.values()))
    folds: WalkForwardSplit = split_by_window(reference, window)
    is_ts = {bar.ts_utc for bar in folds.in_sample}
    oos_ts = {bar.ts_utc for bar in folds.out_of_sample}
    in_sample = {
        instrument_id: [bar for bar in series if bar.ts_utc in is_ts]
        for instrument_id, series in bars_by_instrument.items()
    }
    out_of_sample = {
        instrument_id: [bar for bar in series if bar.ts_utc in oos_ts]
        for instrument_id, series in bars_by_instrument.items()
    }
    return in_sample, out_of_sample
