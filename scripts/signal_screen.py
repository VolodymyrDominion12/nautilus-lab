"""Signal screen: does a candidate predictor predict forward returns at all?

This is a *measuring instrument*, not a strategy. It answers one question per candidate
before anyone writes a robot around it: is there signed predictive content, how big is it
in percent, is the sign stable across symbols, and is it big enough to survive a
round-trip cost? It measures the raw predictor against raw forward returns — the trading
direction is whatever the sign of the relationship says, so a negative IC is a finding too.

Honesty rules it follows:

* the screen reads the **in-sample slice only** (`--is-fraction`, default 0.7). The tail is
  left untouched and never reported; selection on out-of-sample data is forbidden in this
  repository, and an IC table is selection;
* every estimate carries `n` and a **block-bootstrap** confidence interval (blocks, because
  overlapping horizons and volatility clustering make i.i.d. intervals lie);
* two controls are always in the table: a seeded random predictor (a null the pipeline
  must show as ~0) and a leak self-test (the forward return used as its own predictor must
  show ~1.0). A screen that passes neither says nothing about the candidates;
* a real but small effect is reported as *uninvestable*, not as an edge: the spread is
  compared with the configured round-trip cost.

Run:
  .venv/bin/python scripts/signal_screen.py --catalog catalog --interval 1h \
      --symbols BTCUSDT,ETHUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,BNBUSDT,SOLUSDT \
      --out reports/screens/signal_screen.json --markdown reports/screens/signal_screen.md
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from nautilus_lab.infrastructure.funding_catalog import ParquetFundingCatalog
from nautilus_lab.infrastructure.nautilus.bar_convert import datetime_to_nanos
from nautilus_lab.infrastructure.nautilus.parquet_catalog import NautilusParquetCatalog
from nautilus_lab.infrastructure.taker_flow_catalog import ParquetTakerFlowCatalog

#: Spot taker fee per side (infrastructure/settings.py); a round trip is twice this.
FEE_RATE = 0.00075
ROUND_TRIP_PCT = 2 * FEE_RATE * 100.0
#: Bootstrap block length in bars: one day on an hourly grid.
BLOCK = 24
#: A spread has to clear this multiple of the round trip to be worth a strategy.
COST_MULTIPLE = 3.0
#: Bars of warmup before a predictor is defined.
WARMUP = 200


@dataclass
class Series:
    """One symbol: aligned bars plus the optional flow and funding inputs."""

    symbol: str
    ts: np.ndarray
    close: np.ndarray
    high: np.ndarray
    low: np.ndarray
    volume: np.ndarray
    taker_buy: np.ndarray | None = None
    funding_ts: np.ndarray | None = None
    funding_rate: np.ndarray | None = None


@dataclass
class Screen:
    """Bookkeeping for the report."""

    symbols: list[str] = field(default_factory=list)
    bars_total: int = 0
    bars_is: int = 0
    rows: list[dict[str, Any]] = field(default_factory=list)
    cross_sectional: list[dict[str, Any]] = field(default_factory=list)
    controls: dict[str, Any] = field(default_factory=dict)


#: Bar-series spec suffix per interval, as the catalog folders spell it.
SPEC = {
    1: "1-MINUTE",
    5: "5-MINUTE",
    15: "15-MINUTE",
    30: "30-MINUTE",
    60: "1-HOUR",
    240: "4-HOUR",
    1440: "1-DAY",
}


def _minutes(interval: str) -> int:
    unit = interval[-1]
    value = int(interval[:-1])
    return value * {"m": 1, "h": 60, "d": 1440}[unit]


def load_symbol(catalog: Path, symbol: str, interval: str) -> Series:
    """Bars, taker flow and funding for one symbol, through the project's own catalogs.

    The bar Parquet store holds Nautilus' 16-byte decimal, so decoding is never
    re-derived here: `infrastructure/nautilus/parquet_catalog.py` already does it, and
    reusing it also inherits its dedup and ordering invariants.
    """
    bar_type = f"{symbol}.SIM-{SPEC[_minutes(interval)]}-LAST-EXTERNAL"
    bars = NautilusParquetCatalog(catalog).load(bar_type=bar_type)
    flow = ParquetTakerFlowCatalog(catalog).load(symbol=symbol, interval=interval)
    flow_by_ns = {datetime_to_nanos(ts): float(value) for ts, value in flow.items()}
    ts = np.array([datetime_to_nanos(bar.ts_utc) for bar in bars], dtype="int64")
    taker = None
    if flow_by_ns:
        taker = np.array([flow_by_ns.get(int(item), np.nan) for item in ts])
    snapshots = ParquetFundingCatalog(catalog).load(symbol=symbol)
    funding_ts = None
    funding_rate = None
    if snapshots:
        funding_ts = np.array([datetime_to_nanos(item.ts_utc) for item in snapshots], dtype="int64")
        funding_rate = np.array([float(item.funding_rate) for item in snapshots])
    return Series(
        symbol=symbol,
        ts=ts,
        close=np.array([float(bar.close) for bar in bars]),
        high=np.array([float(bar.high) for bar in bars]),
        low=np.array([float(bar.low) for bar in bars]),
        volume=np.array([float(bar.volume) for bar in bars]),
        taker_buy=taker,
        funding_ts=funding_ts,
        funding_rate=funding_rate,
    )


def rolling_mean(values: np.ndarray, window: int) -> np.ndarray:
    """Trailing mean ending on the current bar; a window holding a NaN stays NaN.

    A plain `cumsum` is poisoned by one NaN for the rest of the series — the first bar has
    no true range and no return — so the running sum and the running count of finite
    values are accumulated separately.
    """
    out = np.full(values.shape, np.nan)
    if values.size < window:
        return out
    finite = np.isfinite(values)
    filled = np.where(finite, values, 0.0)
    total = np.cumsum(np.insert(filled, 0, 0.0))
    count = np.cumsum(np.insert(finite.astype(float), 0, 0.0))
    sums = total[window:] - total[:-window]
    counts = count[window:] - count[:-window]
    with np.errstate(invalid="ignore", divide="ignore"):
        out[window - 1 :] = np.where(counts == window, sums / window, np.nan)
    return out


def rolling_std(values: np.ndarray, window: int) -> np.ndarray:
    """Trailing standard deviation with the same NaN rule as `rolling_mean`."""
    out = np.full(values.shape, np.nan)
    if values.size < window:
        return out
    finite = np.isfinite(values)
    filled = np.where(finite, values, 0.0)
    total = np.cumsum(np.insert(filled, 0, 0.0))
    total_sq = np.cumsum(np.insert(filled * filled, 0, 0.0))
    count = np.cumsum(np.insert(finite.astype(float), 0, 0.0))
    sums = total[window:] - total[:-window]
    sums_sq = total_sq[window:] - total_sq[:-window]
    counts = count[window:] - count[:-window]
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(counts == window, sums / window, np.nan)
        variance = np.where(counts == window, sums_sq / window - mean * mean, np.nan)
    out[window - 1 :] = np.sqrt(np.maximum(variance, 0.0))
    return out


def predictors(series: Series, *, seed: int) -> dict[str, np.ndarray]:
    """Candidate predictors, each defined at bar t from bars up to and including t."""
    close, high, low, volume = series.close, series.high, series.low, series.volume
    n = close.size
    out: dict[str, np.ndarray] = {}

    ret = np.full(n, np.nan)
    ret[1:] = np.diff(close) / close[:-1]

    for window in (24, 168):
        values = np.full(n, np.nan)
        values[window:] = close[window:] / close[:-window] - 1.0
        out[f"mom_{window}"] = values * 100.0

    sma = rolling_mean(close, 20)
    sd = rolling_std(close, 20)
    with np.errstate(invalid="ignore", divide="ignore"):
        out["rev_z"] = (close - sma) / np.where(sd > 0, sd, np.nan)

    high_24 = np.full(n, np.nan)
    for index in range(24, n):
        high_24[index] = high[index - 24 : index].max()
    with np.errstate(invalid="ignore"):
        out["dist_high_24"] = (close / high_24 - 1.0) * 100.0

    # Kaufman efficiency ratio: net move over the sum of absolute moves.
    abs_move = np.abs(ret)
    for window in (20,):
        net = np.full(n, np.nan)
        path = rolling_mean(abs_move, window) * window
        net[window:] = np.abs(close[window:] - close[:-window])
        with np.errstate(invalid="ignore", divide="ignore"):
            out[f"er{window}"] = net / np.where(path > 0, path, np.nan)

    # ATR%: simple mean of true range.
    tr = np.full(n, np.nan)
    tr[1:] = np.maximum.reduce(
        [high[1:] - low[1:], np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1])]
    )
    atr = rolling_mean(tr, 14)
    out["atr_pct"] = atr / close * 100.0

    # Volatility-scaled momentum: the drift per unit of risk (a screening favourite).
    with np.errstate(invalid="ignore", divide="ignore"):
        out["mom24_over_atr"] = out["mom_24"] / np.where(
            atr / close * 100.0 > 0, atr / close * 100.0, np.nan
        )

    if series.taker_buy is not None and volume is not None:
        with np.errstate(invalid="ignore", divide="ignore"):
            imbalance = 2.0 * series.taker_buy / np.where(volume > 0, volume, np.nan) - 1.0
        out["flow_imb"] = imbalance * 100.0
        out["flow_z"] = (imbalance - rolling_mean(imbalance, 100)) / rolling_std(imbalance, 100)

    if series.funding_ts is not None and series.funding_rate is not None:
        index = np.searchsorted(series.funding_ts, series.ts, side="right") - 1
        filled = np.where(index >= 0, series.funding_rate[np.clip(index, 0, None)], np.nan)
        filled = np.where(index >= 0, filled, np.nan)
        out["funding"] = filled * 100.0

    # The control must differ per symbol: repeating one draw across symbols would let the
    # pooled test treat a single series as seven independent ones and fake significance.
    rng = np.random.default_rng(seed)
    out["control_rand"] = rng.standard_normal(n)
    return out


def forward_return(close: np.ndarray, horizon: int) -> np.ndarray:
    out = np.full(close.size, np.nan)
    out[:-horizon] = (close[horizon:] / close[:-horizon] - 1.0) * 100.0
    return out


def block_sums(values: np.ndarray, block: int = BLOCK) -> np.ndarray:
    """Per-block sums, dropping the remainder so every block has the same length."""
    usable = (values.size // block) * block
    return values[:usable].reshape(-1, block).sum(axis=1)


def ic_with_ci(
    x: np.ndarray, y: np.ndarray, draws: int, rng: np.random.Generator
) -> dict[str, Any]:
    """Pearson IC of standardised series + block-bootstrap CI and p-value."""
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    if x.size < 200:
        return {"n": int(x.size), "ic": None, "ci": [None, None], "p": None}
    xz = (x - x.mean()) / x.std(ddof=1)
    yz = (y - y.mean()) / y.std(ddof=1)
    product = xz * yz
    ic = float(product.mean())
    sums = block_sums(product)
    if sums.size < 8:
        return {"n": int(x.size), "ic": ic, "ci": [None, None], "p": None}
    picks = rng.integers(0, sums.size, size=(draws, sums.size))
    boot = sums[picks].sum(axis=1) / (sums.size * BLOCK)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    p = 2.0 * min(float((boot <= 0).mean()), float((boot >= 0).mean()))
    rank_ic = float(np.corrcoef(_rank(x), _rank(y))[0, 1])
    return {
        "n": int(x.size),
        "ic": round(ic, 4),
        "ci": [round(float(lo), 4), round(float(hi), 4)],
        "p": round(min(p, 1.0), 4),
        "rank_ic": round(rank_ic, 4),
    }


def _rank(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="stable")
    ranks = np.empty(values.size, dtype=float)
    ranks[order] = np.arange(values.size, dtype=float)
    # average ties, so a discrete predictor (funding) is not ranked arbitrarily
    sorted_values = values[order]
    start = 0
    for index in range(1, values.size + 1):
        if index == values.size or sorted_values[index] != sorted_values[start]:
            if index - start > 1:
                ranks[order[start:index]] = ranks[order[start:index]].mean()
            start = index
    return ranks


def decile_spread(
    x: np.ndarray, y: np.ndarray, deciles: int, draws: int, rng: np.random.Generator
) -> dict[str, Any]:
    """Mean forward return in the top vs bottom decile of the predictor, in percent."""
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    if x.size < 500:
        return {
            "n": int(x.size),
            "top_pct": None,
            "bottom_pct": None,
            "spread_pct": None,
            "ci": None,
        }
    edges = np.quantile(x, np.linspace(0, 1, deciles + 1))
    bucket = np.clip(np.digitize(x, edges[1:-1]), 0, deciles - 1)
    top, bottom = y[bucket == deciles - 1], y[bucket == 0]
    spread = float(top.mean() - bottom.mean())
    # bootstrap the spread through block sums of each bucket's sum and count
    usable = (y.size // BLOCK) * BLOCK
    block_bucket = bucket[:usable].reshape(-1, BLOCK)
    block_y = y[:usable].reshape(-1, BLOCK)
    sums = np.zeros((block_bucket.shape[0], deciles))
    counts = np.zeros((block_bucket.shape[0], deciles))
    for index in range(block_bucket.shape[0]):
        sums[index] = np.bincount(block_bucket[index], weights=block_y[index], minlength=deciles)
        counts[index] = np.bincount(block_bucket[index], minlength=deciles)
    picks = rng.integers(0, sums.shape[0], size=(draws, sums.shape[0]))
    top_sum = sums[:, deciles - 1][picks].sum(axis=1)
    top_cnt = counts[:, deciles - 1][picks].sum(axis=1)
    bot_sum = sums[:, 0][picks].sum(axis=1)
    bot_cnt = counts[:, 0][picks].sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        boot = top_sum / np.where(top_cnt > 0, top_cnt, np.nan) - bot_sum / np.where(
            bot_cnt > 0, bot_cnt, np.nan
        )
    lo, hi = np.nanpercentile(boot, [2.5, 97.5])
    return {
        "n": int(x.size),
        "top_pct": round(float(top.mean()), 3),
        "bottom_pct": round(float(bottom.mean()), 3),
        "spread_pct": round(spread, 3),
        "ci": [round(float(lo), 3), round(float(hi), 3)],
        "top_n": int(top.size),
    }


def bh_adjust(pvalues: list[float | None]) -> list[float | None]:
    """Benjamini-Hochberg FDR across the family of tests in one table."""
    indexed = [(p, i) for i, p in enumerate(pvalues) if p is not None]
    if not indexed:
        return pvalues
    indexed.sort()
    m = len(indexed)
    adjusted: list[float | None] = [None] * len(pvalues)
    running = 1.0
    for rank, (p, index) in enumerate(reversed(indexed), start=1):
        position = m - rank + 1
        running = min(running, p * m / position)
        adjusted[index] = round(min(running, 1.0), 4)
    return adjusted


def load_universe(args: argparse.Namespace) -> tuple[list[Series], np.ndarray]:
    """Every requested symbol, plus the timestamp grid they all share."""
    catalog = Path(args.catalog)
    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    series = [load_symbol(catalog, symbol, args.interval) for symbol in symbols]
    grid = series[0].ts
    for item in series[1:]:
        grid = np.intersect1d(grid, item.ts)
    if grid.size == 0:
        raise SystemExit("the requested symbols share no timestamps; check catalog and interval")
    return series, grid


def main() -> None:
    parser = argparse.ArgumentParser(description="Screen candidate predictors on forward returns")
    parser.add_argument("--catalog", default="catalog")
    parser.add_argument("--interval", default="1h")
    parser.add_argument(
        "--symbols", default="BTCUSDT,ETHUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,BNBUSDT,SOLUSDT"
    )
    parser.add_argument("--is-fraction", type=float, default=0.7)
    parser.add_argument("--horizons", default="1,4,24")
    parser.add_argument("--deciles", type=int, default=10)
    parser.add_argument("--bootstrap", type=int, default=1000)
    parser.add_argument("--out", default="reports/screens/signal_screen.json")
    parser.add_argument("--markdown", default="reports/screens/signal_screen.md")
    args = parser.parse_args()

    rng = np.random.default_rng(7)
    series, grid = load_universe(args)
    horizons = [int(item) for item in args.horizons.split(",")]
    is_end = int(grid.size * args.is_fraction)
    screen = Screen(
        symbols=[item.symbol for item in series], bars_total=int(grid.size), bars_is=is_end
    )

    aligned: dict[str, dict[str, np.ndarray]] = {}
    forward: dict[str, dict[int, np.ndarray]] = {}
    for item in series:
        index = np.searchsorted(item.ts, grid)
        index = np.clip(index, 0, item.ts.size - 1)
        aligned[item.symbol] = {
            "close": item.close[index],
            "high": item.high[index],
            "low": item.low[index],
            "volume": item.volume[index],
            "taker": np.full(grid.size, np.nan)
            if item.taker_buy is None
            else item.taker_buy[index],
            "funding_ts": item.funding_ts,
            "funding_rate": item.funding_rate,
            "index": index,
        }
        forward[item.symbol] = {
            horizon: forward_return(item.close, horizon)[index] for horizon in horizons
        }

    # Predictors are computed per symbol on its own (aligned) arrays.
    table: dict[str, dict[str, np.ndarray]] = {}
    for position, item in enumerate(series):
        data = aligned[item.symbol]
        local = Series(
            symbol=item.symbol,
            ts=grid,
            close=data["close"],
            high=data["high"],
            low=data["low"],
            volume=data["volume"],
            taker_buy=None if np.isnan(data["taker"]).all() else data["taker"],
            funding_ts=item.funding_ts,
            funding_rate=item.funding_rate,
        )
        table[item.symbol] = predictors(local, seed=20261001 + position)

    names = sorted(next(iter(table.values())).keys())
    is_slice = slice(WARMUP, is_end)

    # ---- pipeline self-test: the forward return used as its own predictor ---------
    # A screen that cannot report IC = 1.00 here is broken, and every other number in
    # the table is then meaningless.
    leak_series = forward[series[0].symbol][horizons[0]]
    screen.controls["leak_self_test"] = ic_with_ci(
        leak_series[is_slice], leak_series[is_slice], 200, rng
    )

    # ---- per symbol ---------------------------------------------------------------
    for name in names:
        for horizon in horizons:
            ics, spreads = [], []
            for item in series:
                x = table[item.symbol][name][is_slice]
                y = forward[item.symbol][horizon][is_slice]
                result = ic_with_ci(x, y, args.bootstrap, rng)
                result.update({"predictor": name, "symbol": item.symbol, "horizon": horizon})
                spread = decile_spread(x, y, args.deciles, args.bootstrap, rng)
                result["spread"] = spread
                screen.rows.append(result)
                if result["ic"] is not None:
                    ics.append(result["ic"])
                if spread["spread_pct"] is not None:
                    spreads.append(spread["spread_pct"])
            if name == "control_rand":
                screen.controls.setdefault("control_rand", {})[f"+{horizon}"] = {
                    "mean_ic": None if not ics else round(float(np.mean(ics)), 4),
                    "mean_spread_pct": None if not spreads else round(float(np.mean(spreads)), 3),
                }

    # ---- pooled across symbols (returns demeaned per symbol) ----------------------
    pooled: list[dict[str, Any]] = []
    for name in names:
        for horizon in horizons:
            xs, ys = [], []
            for item in series:
                y = forward[item.symbol][horizon][is_slice]
                y = y - np.nanmean(y)
                xs.append(table[item.symbol][name][is_slice])
                ys.append(y)
            x = np.concatenate(xs)
            y = np.concatenate(ys)
            base = ic_with_ci(x, y, args.bootstrap, rng)
            magnitude = ic_with_ci(x, np.abs(y), args.bootstrap, rng)
            spread = decile_spread(x, y, args.deciles, args.bootstrap, rng)
            pooled.append(
                {
                    "predictor": name,
                    "horizon": horizon,
                    "n": base["n"],
                    "ic": base["ic"],
                    "ci": base["ci"],
                    "p": base["p"],
                    "rank_ic": base.get("rank_ic"),
                    "spread_pct": spread["spread_pct"],
                    "spread_ci": spread["ci"],
                    "spread_top_pct": spread["top_pct"],
                    "spread_bottom_pct": spread["bottom_pct"],
                    "abs_ic": magnitude["ic"],
                    "abs_ic_ci": magnitude["ci"],
                }
            )
    adjusted = bh_adjust([item["p"] for item in pooled])
    for item, q in zip(pooled, adjusted, strict=True):
        item["q_bh"] = q
        item["survives_fdr_10"] = bool(q is not None and q <= 0.10)
        # "tradable" needs all three: direction distinguishable from zero, large enough to
        # clear the round trip, and alive after multiplicity control. Any one alone is noise
        # dressed up as a finding.
        item["tradable"] = bool(
            item["survives_fdr_10"]
            and item["ci"][0] is not None
            and (item["ci"][0] > 0 or item["ci"][1] < 0)
            and item["spread_pct"] is not None
            and abs(item["spread_pct"]) > COST_MULTIPLE * ROUND_TRIP_PCT
        )

    # ---- cross-sectional long/short spread (the basket version) -------------------
    for name in names:
        for horizon in horizons:
            matrix = np.vstack([table[item.symbol][name][is_slice] for item in series])
            returns = np.vstack([forward[item.symbol][horizon][is_slice] for item in series])
            valid = np.isfinite(matrix) & np.isfinite(returns)
            valid[:, :] &= valid.sum(axis=0) >= 4
            picks = []
            for column in range(matrix.shape[1]):
                if not valid[:, column].all():
                    picks.append(np.nan)
                    continue
                order = np.argsort(matrix[:, column])
                picks.append(returns[order[-1], column] - returns[order[0], column])
            values = np.array([item for item in picks if np.isfinite(item)])
            if values.size < 200:
                continue
            sums = block_sums(values)
            draws = rng.integers(0, sums.size, size=(args.bootstrap, sums.size))
            boot = sums[draws].sum(axis=1) / (sums.size * BLOCK)
            lo, hi = np.percentile(boot, [2.5, 97.5])
            screen.cross_sectional.append(
                {
                    "predictor": name,
                    "horizon": horizon,
                    "n": int(values.size),
                    "mean_spread_pct": round(float(values.mean()), 3),
                    "median_spread_pct": round(float(np.median(values)), 3),
                    "ci": [round(float(lo), 3), round(float(hi), 3)],
                }
            )

    screen.rows = [
        {key: value for key, value in row.items() if key != "spread"} | {"spread": row["spread"]}
        for row in screen.rows
    ]
    payload = {
        "config": {
            "catalog": args.catalog,
            "interval": args.interval,
            "symbols": screen.symbols,
            "is_fraction": args.is_fraction,
            "bars_total": screen.bars_total,
            "bars_in_sample": screen.bars_is,
            "horizons": horizons,
            "round_trip_cost_pct": ROUND_TRIP_PCT,
            "cost_multiple_required": COST_MULTIPLE,
            "bootstrap_draws": args.bootstrap,
            "block_bars": BLOCK,
            "note": "in-sample slice only; the tail was not looked at",
        },
        "controls": screen.controls,
        "pooled": pooled,
        "cross_sectional": screen.cross_sectional,
        "per_symbol": screen.rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    Path(args.markdown).write_text(render_markdown(screen, pooled, horizons), encoding="utf-8")
    print(f"wrote {out} and {args.markdown}")
    print_table(pooled, horizons)
    print("\ncontrols:", json.dumps(screen.controls, ensure_ascii=False))


def render_markdown(screen: Screen, pooled: list[dict[str, Any]], horizons: list[int]) -> str:
    lines = [
        "# Скринінг сигналів (in-sample slice)",
        "",
        f"- Символи: {', '.join(screen.symbols)}",
        f"- Барів усього: {screen.bars_total}; у вибірці скринінгу: {screen.bars_is} "
        f"(хвіст не дивились)",
        f"- Round-trip cost: {ROUND_TRIP_PCT:.2f}%; поріг «торговано»: "
        f"{COST_MULTIPLE * ROUND_TRIP_PCT:.2f}% спреду",
        f"- Блок-бутстрап: {BLOCK} барів/блок",
        "",
        "## Пул (усі символи, форвард демінований по символу)",
        "",
        "| Предиктор | +h | n | IC | 95% CI | rank | p | q(BH) | Спред | 95% CI | VolIC | Торг.? |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    lines.extend(
        "| {} | +{} | {} | {} | [{}; {}] | {} | {} | {} | {} | {} | {} | {} |".format(
            item["predictor"],
            item["horizon"],
            item["n"],
            _num(item["ic"]),
            _num(item["ci"][0]),
            _num(item["ci"][1]),
            _num(item["rank_ic"]),
            _num(item["p"], 4),
            _num(item["q_bh"], 4),
            _num(item["spread_pct"], 3, "%"),
            f"{_num((item['spread_ci'] or [None, None])[0], 2)}; "
            f"{_num((item['spread_ci'] or [None, None])[1], 2)}",
            _num(item.get("abs_ic")),
            "✅" if item["tradable"] else "—",
        )
        for item in sorted(pooled, key=lambda r: (r["horizon"], -abs(r["ic"] or 0)))
    )
    lines += [
        "",
        "## Крос-секційний лонг/шорт (найкращий проти найгіршого з кошика)",
        "",
        "| Предиктор | Горизонт | n | Середній спред | 95% CI |",
        "|---|---|---|---|---|",
    ]
    for item in sorted(
        screen.cross_sectional, key=lambda r: (r["horizon"], -abs(r["mean_spread_pct"]))
    ):
        lines.append(
            "| {} | +{} | {} | {} | [{}; {}] |".format(
                item["predictor"],
                item["horizon"],
                item["n"],
                _num(item["mean_spread_pct"], 3, "%"),
                _num(item["ci"][0], 2),
                _num(item["ci"][1], 2),
            )
        )
    lines += [
        "",
        "## Контролі",
        "",
        "```json",
        json.dumps(screen.controls, ensure_ascii=False, indent=1),
        "```",
        "",
    ]
    return "\n".join(lines)


def _num(value: float | None, digits: int = 4, suffix: str = "") -> str:
    if value is None:
        return "—"
    return f"{value:+.{digits}f}{suffix}"


def _shown(value: float | None, default: float) -> float:
    """None means 'not measured'; 0.0 is a measurement and must survive the formatting."""
    return default if value is None else value


def print_table(pooled: list[dict[str, Any]], horizons: list[int]) -> None:
    for horizon in horizons:
        print(f"\n--- горизонт +{horizon} барів (in-sample) ---")
        for item in sorted(
            [row for row in pooled if row["horizon"] == horizon], key=lambda r: -abs(r["ic"] or 0)
        ):
            flag = "ТОРГОВАНО" if item["tradable"] else ("fdr" if item["survives_fdr_10"] else "")
            print(
                "  {:16s} n={:6d} IC {:+.4f} [{:+.4f};{:+.4f}] p={:6.3f} q={:6.3f} "
                "спред {:+.3f}% |y|IC {:+.3f} {:s}".format(
                    item["predictor"],
                    item["n"],
                    _shown(item["ic"], 0.0),
                    _shown(item["ci"][0], 0.0),
                    _shown(item["ci"][1], 0.0),
                    _shown(item["p"], 1.0),
                    _shown(item["q_bh"], 1.0),
                    _shown(item["spread_pct"], 0.0),
                    _shown(item.get("abs_ic"), 0.0),
                    flag,
                )
            )


if __name__ == "__main__":
    main()
