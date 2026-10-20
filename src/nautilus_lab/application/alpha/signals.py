"""G2 templates: candidate signals that each name an economic mechanism.

A signal here is a raw score per coin and bar, computed from data known at that bar's
close. The direction is not part of the signal: the screen reads it from the sign of
the information coefficient, so "high funding predicts underperformance" and "high
funding predicts outperformance" are the same candidate, not two trials.

Windows are given in days and converted to bars, so the same template runs on 1h, 4h
or 1d panels. A template whose input field is missing from the panel is skipped and
listed as such. It is never filled with zeros.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from nautilus_lab.application.alpha.operators import (
    cs_mean,
    cs_rank,
    delay,
    delta,
    pct_change,
    rolling_beta,
    ts_max,
    ts_mean,
    ts_std,
    ts_sum,
    ts_zscore,
)
from nautilus_lab.application.alpha.panel import FloatArray, Panel

BETA_WINDOW_DAYS = 30


@dataclass(frozen=True)
class Context:
    """Arrays every template shares, computed once per panel."""

    panel: Panel
    ret: FloatArray  # 1-bar simple close-to-close return
    market: FloatArray  # equal-weight 1-bar return, a T vector
    beta: FloatArray  # trailing beta to `market`, past bars only
    bars_per_day: int

    def bars(self, days: float) -> int:
        return max(1, round(days * self.bars_per_day))


def build_context(panel: Panel, min_names: int) -> Context:
    close = panel.get("close")
    ret = pct_change(close, 1)
    market = cs_mean(ret, min_names)
    bars_per_day = max(1, round(24 * 60 / panel.bar_minutes))
    beta = rolling_beta(ret, market, window=BETA_WINDOW_DAYS * bars_per_day)
    return Context(panel=panel, ret=ret, market=market, beta=beta, bars_per_day=bars_per_day)


@dataclass(frozen=True)
class SignalSpec:
    name: str
    family: str
    mechanism: str
    requires: tuple[str, ...]
    compute: Callable[[Context], FloatArray]

    def available(self, panel: Panel) -> bool:
        return all(panel.has(field) for field in self.requires)


def _momentum(days: int) -> Callable[[Context], FloatArray]:
    def compute(ctx: Context) -> FloatArray:
        skipped = delay(ctx.panel.get("close"), ctx.bars(1))
        return pct_change(skipped, ctx.bars(days))

    return compute


def _reversal(days: float) -> Callable[[Context], FloatArray]:
    def compute(ctx: Context) -> FloatArray:
        return pct_change(ctx.panel.get("close"), ctx.bars(days))

    return compute


def _volatility(ctx: Context) -> FloatArray:
    return ts_std(ctx.ret, ctx.bars(7))


def _beta(ctx: Context) -> FloatArray:
    return ctx.beta


def _idio_vol(ctx: Context) -> FloatArray:
    residual = ctx.ret - ctx.beta * ctx.market[:, None]
    return ts_std(residual, ctx.bars(30))


def _max_return(ctx: Context) -> FloatArray:
    return ts_max(ctx.ret, ctx.bars(7))


def _distance_from_high(ctx: Context) -> FloatArray:
    high = ts_max(ctx.panel.get("high"), ctx.bars(30))
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(high > 0, ctx.panel.get("close") / high - 1.0, np.nan)


def _imbalance(ctx: Context) -> FloatArray:
    volume = ctx.panel.get("volume")
    taker = ctx.panel.get("taker_buy")
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(volume > 0, 2.0 * taker / volume - 1.0, np.nan)


def _taker_imbalance_1d(ctx: Context) -> FloatArray:
    volume = ctx.panel.get("volume")
    taker = ctx.panel.get("taker_buy")
    window = ctx.bars(1)
    total = ts_sum(volume, window)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(total > 0, ts_sum(2.0 * taker - volume, window) / total, np.nan)


def _taker_imbalance_z(ctx: Context) -> FloatArray:
    return ts_zscore(ts_mean(_imbalance(ctx), ctx.bars(1)), ctx.bars(30))


def _dollar_volume(ctx: Context) -> FloatArray:
    return ctx.panel.get("volume") * ctx.panel.get("close")


def _volume_shock(ctx: Context) -> FloatArray:
    dollar = _dollar_volume(ctx)
    short = ts_mean(dollar, ctx.bars(1))
    long = ts_mean(dollar, ctx.bars(30))
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where((short > 0) & (long > 0), np.log(short / long), np.nan)


def _amihud(ctx: Context) -> FloatArray:
    dollar = _dollar_volume(ctx)
    with np.errstate(invalid="ignore", divide="ignore"):
        impact = np.where(dollar > 0, np.abs(ctx.ret) / dollar, np.nan)
        level = ts_mean(impact, ctx.bars(7))
        return np.where(level > 0, np.log(level), np.nan)


def _funding(days: int) -> Callable[[Context], FloatArray]:
    def compute(ctx: Context) -> FloatArray:
        return ts_mean(ctx.panel.get("funding_last"), ctx.bars(days))

    return compute


def _funding_change(ctx: Context) -> FloatArray:
    return delta(ts_mean(ctx.panel.get("funding_last"), ctx.bars(1)), ctx.bars(3))


def _premium_level(ctx: Context) -> FloatArray:
    return ts_mean(ctx.panel.get("premium"), ctx.bars(1))


def _premium_change(ctx: Context) -> FloatArray:
    return delta(ts_mean(ctx.panel.get("premium"), ctx.bars(1)), ctx.bars(1))


def _crowding(ctx: Context) -> FloatArray:
    funding = cs_rank(ts_mean(ctx.panel.get("funding_last"), ctx.bars(7)), 1)
    momentum = cs_rank(_momentum(7)(ctx), 1)
    return funding + momentum


TEMPLATES: tuple[SignalSpec, ...] = (
    SignalSpec(
        "mom_3d",
        "momentum",
        "Capital rotates between coins slowly: recent leaders keep leading.",
        ("close",),
        _momentum(3),
    ),
    SignalSpec(
        "mom_7d",
        "momentum",
        "Weekly cross-sectional momentum, last day skipped (short-term reversal).",
        ("close",),
        _momentum(7),
    ),
    SignalSpec(
        "mom_30d",
        "momentum",
        "Monthly momentum: slow diffusion of information across the basket.",
        ("close",),
        _momentum(30),
    ),
    SignalSpec(
        "rev_1d",
        "reversal",
        "Liquidity provision: yesterday's overshoot is paid back.",
        ("close",),
        _reversal(1),
    ),
    SignalSpec(
        "rev_4h",
        "reversal",
        "Intraday overshoot from aggressive flow mean-reverts within hours.",
        ("close",),
        _reversal(1 / 6),
    ),
    SignalSpec(
        "vol_7d",
        "risk",
        "Low-volatility anomaly: leverage-constrained buyers overpay for volatile coins.",
        ("close",),
        _volatility,
    ),
    SignalSpec(
        "beta_30d",
        "risk",
        "Betting against beta: high-beta coins are bid as cheap leverage.",
        ("close",),
        _beta,
    ),
    SignalSpec(
        "idio_vol_30d",
        "risk",
        "Idiosyncratic volatility: lottery demand overprices coin-specific risk.",
        ("close",),
        _idio_vol,
    ),
    SignalSpec(
        "max_ret_7d",
        "risk",
        "MAX effect: the biggest recent jump attracts lottery buyers who overpay.",
        ("close",),
        _max_return,
    ),
    SignalSpec(
        "dist_high_30d",
        "anchoring",
        "Anchoring to the recent high: coins near it break out late.",
        ("close", "high"),
        _distance_from_high,
    ),
    SignalSpec(
        "taker_imb_1d",
        "flow",
        "Aggressive buying is informed flow that prices are slow to absorb.",
        ("close", "volume", "taker_buy"),
        _taker_imbalance_1d,
    ),
    SignalSpec(
        "taker_imb_z",
        "flow",
        "Unusual taker imbalance against the coin's own norm: positioning, not habit.",
        ("close", "volume", "taker_buy"),
        _taker_imbalance_z,
    ),
    SignalSpec(
        "volume_shock_1d",
        "attention",
        "Attention shocks: a volume spike draws noise traders, then the price fades.",
        ("close", "volume"),
        _volume_shock,
    ),
    SignalSpec(
        "amihud_7d",
        "liquidity",
        "Illiquidity premium: coins that move more per dollar traded pay to hold.",
        ("close", "volume"),
        _amihud,
    ),
    SignalSpec(
        "funding_3d",
        "carry",
        "Carry: longs pay funding where demand for leverage is crowded.",
        ("close", "funding_last"),
        _funding(3),
    ),
    SignalSpec(
        "funding_chg_3d",
        "carry",
        "A rising funding rate marks new leveraged demand that later unwinds.",
        ("close", "funding_last"),
        _funding_change,
    ),
    SignalSpec(
        "premium_1d",
        "basis",
        "Perp premium over index: speculative demand for leverage before funding catches up.",
        ("close", "premium"),
        _premium_level,
    ),
    SignalSpec(
        "premium_chg_1d",
        "basis",
        "A widening premium is fresh speculative demand.",
        ("close", "premium"),
        _premium_change,
    ),
    SignalSpec(
        "crowding_7d",
        "crowding",
        "High funding with high momentum: a crowded trade that tends to unwind.",
        ("close", "funding_last"),
        _crowding,
    ),
)


def template(name: str) -> SignalSpec:
    for spec in TEMPLATES:
        if spec.name == name:
            return spec
    raise KeyError(f"unknown signal template {name!r}")
