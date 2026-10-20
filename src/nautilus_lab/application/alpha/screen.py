"""Cross-sectional screen of signal templates against residual forward returns.

The question is the one the P1 verdict forced (2026-10-19). A curve that is 0.9
correlated with buy&hold is beta, so the screen never scores a signal on raw returns.
For every signal x horizon it measures:

* **Target.** Forward return over `(t, t+h]`, net of the funding a long pays, minus the
  coin's trailing beta times the equal-weight market forward return. What is left is
  the part of the move that the market does not explain.
* **Rank IC.** One Spearman correlation per decision row across coins. Its mean, its
  IR, and a *block* t-statistic (blocks of at least a week, because overlapping
  horizons and slow signals make consecutive ICs far from independent).
* **Permutation null.** The signal is shuffled across coins with one permutation per
  block, which keeps every coin's time series intact. The observed mean IC is
  reported as a z-score against that null.
* **Stability.** IC by calendar year, and the share of years whose sign agrees.
* **Tradability.** A dollar-neutral and a dollar+beta-neutral rank-weighted long/short
  book, held for `h` bars as staggered cohorts. Its Sharpe gross and net, turnover,
  and breakeven cost in bps per unit of one-way turnover. The book's correlation with
  the market should be about zero.
* **Multiplicity.** Benjamini-Hochberg over the whole run, and every trial is written
  to the ledger so that DSR elsewhere sees the real count.

Every row the screen evaluates lies inside the requested zone, *including the end of
its target window*. A decision on 2021-12-31 with a 7-day horizon would read 2022
returns (holdout), so it is dropped. Features may look back across a boundary, because
inputs are not outcomes.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

import numpy as np

from nautilus_lab.application.alpha.operators import (
    cs_mean,
    cs_rank,
    lead,
    neutralise,
    pct_change,
    ts_sum,
    unit_gross,
)
from nautilus_lab.application.alpha.panel import BoolArray, FloatArray, IntArray, Panel
from nautilus_lab.application.alpha.signals import TEMPLATES, Context, SignalSpec, build_context
from nautilus_lab.domain.data_zone import DataZone, ZonePolicy

CONTROL_RANDOM = "control_random"
CONTROL_LEAK = "control_leak"


@dataclass(frozen=True)
class ScreenConfig:
    horizons: tuple[int, ...] = (1, 4, 24, 72, 168)
    cost_bps: float = 7.0  # one-way, per unit of turnover: taker 5 bps + 2 bps slippage
    permutations: int = 200
    min_block_days: int = 7
    min_names: int = 5
    seed: int = 20261020
    t_threshold: float = 2.5
    q_threshold: float = 0.10
    breakeven_multiple: float = 2.0
    max_abs_market_corr: float = 0.30
    min_year_consistency: float = 2 / 3
    min_year_days: int = 60

    def __post_init__(self) -> None:
        if not self.horizons or min(self.horizons) < 1:
            raise ValueError("horizons must be positive bar counts")
        if self.permutations < 20:
            raise ValueError("permutations must be >= 20 for a usable null")
        if self.cost_bps < 0:
            raise ValueError("cost_bps must be >= 0")


@dataclass(frozen=True)
class BookStats:
    sharpe_gross: float | None
    sharpe_net: float | None
    mean_bps: float | None  # gross pnl per bar, bps of gross exposure
    turnover: float | None  # one-way turnover per bar, fraction of gross
    breakeven_bps: float | None
    market_corr: float | None
    market_beta: float | None
    bars: int


@dataclass(frozen=True)
class SignalResult:
    name: str
    family: str
    horizon: int
    control: bool
    dates: int
    names_mean: float
    ic_mean: float | None
    ic_std: float | None
    ic_ir: float | None
    hit_rate: float | None
    t_block: float | None
    blocks: int
    perm_z: float | None
    p_value: float | None
    ic_by_year: dict[int, float]
    year_consistency: float | None
    direction: int
    book: BookStats
    book_beta_neutral: BookStats
    q_value: float | None = None
    verdict: str = "reject"
    reasons: tuple[str, ...] = ()

    @property
    def trial_id(self) -> str:
        return f"alpha|{self.name}|h={self.horizon}"


@dataclass(frozen=True)
class ScreenReport:
    zone: DataZone
    symbols: tuple[str, ...]
    held_out: tuple[str, ...]
    windows: tuple[tuple[str, str], ...]
    bar_minutes: int
    config: ScreenConfig
    results: tuple[SignalResult, ...]
    skipped: tuple[str, ...]
    rows_by_horizon: dict[int, int]
    generated_at: str
    trials_total: int | None = None
    controls_ok: bool = False
    notes: tuple[str, ...] = field(default=())

    @property
    def candidates(self) -> tuple[SignalResult, ...]:
        return tuple(r for r in self.results if not r.control and r.verdict == "candidate")


# --------------------------------------------------------------------------- targets


def bar_returns(panel: Panel) -> FloatArray:
    """1-bar return a long earns on bar t: price move minus funding paid on t."""
    price = pct_change(panel.get("close"), 1)
    funding = _funding_paid(panel)
    return price - funding


def forward_returns(panel: Panel, horizon: int) -> FloatArray:
    """Return over `(t, t+h]` for a long held from t's close, funding included."""
    close = panel.get("close")
    with np.errstate(invalid="ignore", divide="ignore"):
        price = np.where(close > 0, lead(close, horizon) / close - 1.0, np.nan)
    funding = lead(ts_sum(_funding_paid(panel), horizon), horizon)
    return price - np.nan_to_num(funding, nan=0.0)


def residual_forward(forward: FloatArray, beta: FloatArray, min_names: int) -> FloatArray:
    market = cs_mean(forward, min_names)
    return forward - beta * market[:, None]


def _funding_paid(panel: Panel) -> FloatArray:
    if "funding_paid" not in panel.fields:
        return np.zeros(panel.shape)
    # NaN only before a coin's first settlement; a missing settlement is not a
    # payment, so it costs nothing rather than poisoning the return.
    return np.nan_to_num(panel.get("funding_paid"), nan=0.0)


# --------------------------------------------------------------------------- zones


def zone_segments(panel: Panel, policy: ZonePolicy, zone: DataZone) -> IntArray:
    """Window index per row inside `zone`, -1 outside it."""
    segment = np.full(panel.ts_min.size, -1, dtype=np.int64)
    for index, window in enumerate(policy.windows(zone)):
        lo = int(window.start.timestamp() // 60)
        hi = int(window.end.timestamp() // 60)
        inside = (panel.ts_min >= lo) & (panel.ts_min < hi)
        segment[inside] = index
    return segment


def decision_rows(segment: IntArray, horizon: int) -> BoolArray:
    """Rows whose whole target window `(t, t+h]` stays inside the same zone window."""
    ahead = np.full(segment.size, -2, dtype=np.int64)
    if horizon < segment.size:
        ahead[:-horizon] = segment[horizon:]
    result: BoolArray = (segment >= 0) & (ahead == segment)
    return result


def pnl_rows(segment: IntArray) -> BoolArray:
    """Rows whose bar `(t-1, t]` lies inside one zone window."""
    behind = np.full(segment.size, -2, dtype=np.int64)
    behind[1:] = segment[:-1]
    result: BoolArray = (segment >= 0) & (behind == segment)
    return result


# --------------------------------------------------------------------------- statistics


def rank_ic(signal_rank: FloatArray, target_rank: FloatArray, min_names: int) -> FloatArray:
    """Per-row Pearson correlation of two rank matrices over their common names."""
    common = np.isfinite(signal_rank) & np.isfinite(target_rank)
    count = common.sum(axis=1)
    x = np.where(common, signal_rank, 0.0)
    y = np.where(common, target_rank, 0.0)
    safe = np.maximum(count, 1)
    x = np.where(common, x - (x.sum(axis=1) / safe)[:, None], 0.0)
    y = np.where(common, y - (y.sum(axis=1) / safe)[:, None], 0.0)
    num = (x * y).sum(axis=1)
    den = np.sqrt((x * x).sum(axis=1) * (y * y).sum(axis=1))
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where((count >= min_names) & (den > 0), num / den, np.nan)


def block_t(
    values: FloatArray, block_id: IntArray, min_blocks: int = 8
) -> tuple[float | None, int]:
    """t-statistic of the mean over block means; blocks absorb serial correlation."""
    finite = np.isfinite(values)
    if not finite.any():
        return None, 0
    ids = block_id[finite]
    vals = values[finite]
    uniq, inverse = np.unique(ids, return_inverse=True)
    sums = np.bincount(inverse, weights=vals)
    counts = np.bincount(inverse)
    means = sums / counts
    blocks = int(uniq.size)
    if blocks < min_blocks:
        return None, blocks
    spread = float(np.std(means, ddof=1))
    if spread == 0:
        return None, blocks
    return float(np.mean(means) / (spread / math.sqrt(blocks))), blocks


def permutation_null(
    signal_rank: FloatArray,
    target_rank: FloatArray,
    block_id: IntArray,
    *,
    draws: int,
    min_names: int,
    rng: np.random.Generator,
) -> FloatArray:
    """Mean IC under coin shuffles that are constant within each block."""
    uniq, inverse = np.unique(block_id, return_inverse=True)
    columns = signal_rank.shape[1]
    out = np.empty(draws)
    for draw in range(draws):
        perms = np.argsort(rng.random((uniq.size, columns)), axis=1)
        shuffled = np.take_along_axis(signal_rank, perms[inverse], axis=1)
        out[draw] = np.nanmean(rank_ic(shuffled, target_rank, min_names))
    return out


def two_sided_p(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2.0))


def benjamini_hochberg(pvalues: Sequence[float | None]) -> list[float | None]:
    indexed = sorted((p, i) for i, p in enumerate(pvalues) if p is not None)
    adjusted: list[float | None] = [None] * len(pvalues)
    m = len(indexed)
    running = 1.0
    for position in range(m, 0, -1):
        p, index = indexed[position - 1]
        running = min(running, p * m / position)
        adjusted[index] = min(running, 1.0)
    return adjusted


def book_stats(
    weights: FloatArray,
    horizon: int,
    returns: FloatArray,
    market: FloatArray,
    rows: BoolArray,
    *,
    cost_bps: float,
    bars_per_year: float,
) -> BookStats:
    """Staggered-cohort book: each bar's weights are held for `horizon` bars."""
    target = np.nan_to_num(unit_gross(weights), nan=0.0)
    held = ts_sum(target, horizon) / horizon
    held[: horizon - 1] = np.cumsum(target, axis=0)[: horizon - 1] / horizon
    previous = np.zeros_like(held)
    previous[1:] = held[:-1]
    pnl = (previous * np.nan_to_num(returns, nan=0.0)).sum(axis=1)
    turnover = np.abs(held - previous).sum(axis=1)
    pnl, turnover, mkt = pnl[rows], turnover[rows], market[rows]
    bars = int(pnl.size)
    if bars < 200:
        return BookStats(None, None, None, None, None, None, None, bars)
    net = pnl - turnover * cost_bps / 1e4
    scale = math.sqrt(bars_per_year)
    mean_turn = float(turnover.mean())
    finite = np.isfinite(mkt)
    corr: float | None = None
    beta: float | None = None
    if finite.sum() > 200 and float(np.std(pnl[finite])) > 0 and float(np.std(mkt[finite])) > 0:
        corr = float(np.corrcoef(pnl[finite], mkt[finite])[0, 1])
        var = float(np.var(mkt[finite]))
        beta = float(np.cov(pnl[finite], mkt[finite], ddof=0)[0, 1] / var) if var > 0 else None
    return BookStats(
        sharpe_gross=_sharpe(pnl, scale),
        sharpe_net=_sharpe(net, scale),
        mean_bps=float(pnl.mean() * 1e4),
        turnover=mean_turn,
        breakeven_bps=float(pnl.mean() / mean_turn * 1e4) if mean_turn > 0 else None,
        market_corr=corr,
        market_beta=beta,
        bars=bars,
    )


def _sharpe(values: FloatArray, scale: float) -> float | None:
    spread = float(np.std(values, ddof=1))
    if spread == 0:
        return None
    return float(values.mean() / spread * scale)


# --------------------------------------------------------------------------- engine


def run_screen(
    panel: Panel,
    *,
    policy: ZonePolicy,
    zone: DataZone = DataZone.EXPLORATION,
    config: ScreenConfig | None = None,
    templates: Iterable[SignalSpec] = TEMPLATES,
    generated_at: datetime | None = None,
) -> ScreenReport:
    """Screen `templates` on the research coins of `panel` inside `zone`.

    Only exploration may be screened. A screen is selection, and selection on
    validation or holdout data turns them into exploration for good.
    """
    if zone is not DataZone.EXPLORATION:
        raise PermissionError(
            f"the screen is selection and runs on exploration only, not {zone.value}; "
            "validation is for preregistered walk-forward tests, holdout for one disclosure"
        )
    cfg = config or ScreenConfig()
    research = policy.research_symbols(panel.symbols)
    held_out = policy.holdout_symbols(panel.symbols)
    if len(research) < cfg.min_names:
        raise ValueError(
            f"{len(research)} research symbols left after the holdout split; "
            f"a cross-section needs at least {cfg.min_names}"
        )
    view = panel.select_symbols(research)
    ctx = build_context(view, cfg.min_names)
    returns_1 = bar_returns(view)
    segment = zone_segments(view, policy, zone)
    rows_pnl = pnl_rows(segment)
    block = max(cfg.min_block_days * ctx.bars_per_day, 1)
    rng = np.random.default_rng(cfg.seed)
    years = view.years()

    available = [spec for spec in templates if spec.available(view)]
    skipped = tuple(spec.name for spec in templates if not spec.available(view))
    signal_ranks = {spec.name: cs_rank(spec.compute(ctx), cfg.min_names) for spec in available}
    families = {spec.name: spec.family for spec in available}
    noise = rng.standard_normal(view.shape)
    noise[~np.isfinite(view.get("close"))] = np.nan
    signal_ranks[CONTROL_RANDOM] = cs_rank(noise, cfg.min_names)
    families[CONTROL_RANDOM] = "control"

    results: list[SignalResult] = []
    rows_by_horizon: dict[int, int] = {}
    for horizon in cfg.horizons:
        target = residual_forward(forward_returns(view, horizon), ctx.beta, cfg.min_names)
        target_rank = cs_rank(target, cfg.min_names)
        rows = decision_rows(segment, horizon)
        rows_by_horizon[horizon] = int(rows.sum())
        block_id = (np.arange(view.shape[0]) // max(block, horizon)).astype(np.int64)
        horizon_ranks = dict(signal_ranks)
        horizon_ranks[CONTROL_LEAK] = target_rank
        for name, ranks in horizon_ranks.items():
            results.append(
                _evaluate(
                    name=name,
                    family=families.get(name, "control"),
                    horizon=horizon,
                    ranks=ranks,
                    target_rank=target_rank,
                    rows=rows,
                    rows_pnl=rows_pnl,
                    block_id=block_id,
                    years=years,
                    ctx=ctx,
                    returns_1=returns_1,
                    cfg=cfg,
                    rng=rng,
                    bars_per_year=view.bars_per_year,
                )
            )

    results = _apply_gate(results, cfg)
    return ScreenReport(
        zone=zone,
        symbols=research,
        held_out=held_out,
        windows=tuple(
            (w.start.date().isoformat(), w.end.date().isoformat()) for w in policy.windows(zone)
        ),
        bar_minutes=view.bar_minutes,
        config=cfg,
        results=tuple(results),
        skipped=skipped,
        rows_by_horizon=rows_by_horizon,
        generated_at=(generated_at or datetime.now(UTC)).isoformat(timespec="seconds"),
        controls_ok=_controls_ok(results, cfg),
    )


def _evaluate(
    *,
    name: str,
    family: str,
    horizon: int,
    ranks: FloatArray,
    target_rank: FloatArray,
    rows: BoolArray,
    rows_pnl: BoolArray,
    block_id: IntArray,
    years: IntArray,
    ctx: Context,
    returns_1: FloatArray,
    cfg: ScreenConfig,
    rng: np.random.Generator,
    bars_per_year: float,
) -> SignalResult:
    control = name in (CONTROL_RANDOM, CONTROL_LEAK)
    sub_s, sub_y, sub_b = ranks[rows], target_rank[rows], block_id[rows]
    ic = rank_ic(sub_s, sub_y, cfg.min_names)
    finite = np.isfinite(ic)
    dates = int(finite.sum())
    names = np.isfinite(sub_s) & np.isfinite(sub_y)
    names_mean = float(names.sum(axis=1)[finite].mean()) if dates else 0.0
    empty_book = BookStats(None, None, None, None, None, None, None, 0)
    if dates < 200:
        return SignalResult(
            name,
            family,
            horizon,
            control,
            dates,
            names_mean,
            None,
            None,
            None,
            None,
            None,
            0,
            None,
            None,
            {},
            None,
            0,
            empty_book,
            empty_book,
        )
    ic_mean = float(np.nanmean(ic))
    ic_std = float(np.nanstd(ic, ddof=1))
    t_stat, blocks = block_t(ic, sub_b)

    perm_z: float | None = None
    p_value: float | None = None
    if name != CONTROL_LEAK:
        null = permutation_null(
            sub_s, sub_y, sub_b, draws=cfg.permutations, min_names=cfg.min_names, rng=rng
        )
        spread = float(np.std(null, ddof=1))
        if spread > 0:
            perm_z = (ic_mean - float(null.mean())) / spread
    if t_stat is not None and perm_z is not None:
        # the weaker of the two tests decides: neither alone is trusted
        p_value = max(two_sided_p(t_stat), two_sided_p(perm_z))

    direction = 1 if ic_mean >= 0 else -1
    by_year: dict[int, float] = {}
    min_rows = cfg.min_year_days * ctx.bars_per_day
    sub_years = years[rows]
    for year in np.unique(sub_years):
        mask = (sub_years == year) & finite
        if int(mask.sum()) >= min_rows:
            by_year[int(year)] = float(ic[mask].mean())
    consistency = (
        sum(1 for v in by_year.values() if v * direction > 0) / len(by_year) if by_year else None
    )

    weights = direction * ranks
    book = book_stats(
        weights,
        horizon,
        returns_1,
        ctx.market,
        rows_pnl,
        cost_bps=cfg.cost_bps,
        bars_per_year=bars_per_year,
    )
    book_bn = book_stats(
        neutralise(weights, ctx.beta),
        horizon,
        returns_1,
        ctx.market,
        rows_pnl,
        cost_bps=cfg.cost_bps,
        bars_per_year=bars_per_year,
    )
    return SignalResult(
        name=name,
        family=family,
        horizon=horizon,
        control=control,
        dates=dates,
        names_mean=names_mean,
        ic_mean=ic_mean,
        ic_std=ic_std,
        ic_ir=ic_mean / ic_std if ic_std > 0 else None,
        hit_rate=float((ic[finite] * direction > 0).mean()),
        t_block=t_stat,
        blocks=blocks,
        perm_z=perm_z,
        p_value=p_value,
        ic_by_year=by_year,
        year_consistency=consistency,
        direction=direction,
        book=book,
        book_beta_neutral=book_bn,
    )


def _apply_gate(results: list[SignalResult], cfg: ScreenConfig) -> list[SignalResult]:
    trials = [r for r in results if not r.control]
    qvalues = benjamini_hochberg([r.p_value for r in trials])
    q_by_id = {r.trial_id: q for r, q in zip(trials, qvalues, strict=True)}
    gated: list[SignalResult] = []
    for result in results:
        if result.control:
            gated.append(result)
            continue
        q = q_by_id[result.trial_id]
        reasons = _reasons(result, q, cfg)
        gated.append(
            replace(
                result,
                q_value=q,
                verdict="reject" if reasons else "candidate",
                reasons=tuple(reasons),
            )
        )
    return gated


def _reasons(result: SignalResult, q: float | None, cfg: ScreenConfig) -> list[str]:
    reasons: list[str] = []
    book = result.book_beta_neutral
    if result.t_block is None or abs(result.t_block) < cfg.t_threshold:
        reasons.append(f"|t_block| < {cfg.t_threshold}")
    if result.perm_z is None or abs(result.perm_z) < cfg.t_threshold:
        reasons.append(f"|perm_z| < {cfg.t_threshold}")
    if q is None or q > cfg.q_threshold:
        reasons.append(f"q_BH > {cfg.q_threshold}")
    need = cfg.breakeven_multiple * cfg.cost_bps
    if book.breakeven_bps is None or book.breakeven_bps < need:
        reasons.append(f"breakeven < {need:g} bps")
    if book.market_corr is None or abs(book.market_corr) > cfg.max_abs_market_corr:
        reasons.append(f"|corr_mkt| > {cfg.max_abs_market_corr}")
    if result.year_consistency is None or result.year_consistency < cfg.min_year_consistency:
        reasons.append("sign unstable across years")
    if book.sharpe_net is None or book.sharpe_net <= 0:
        reasons.append("net Sharpe <= 0")
    return reasons


def _controls_ok(results: Sequence[SignalResult], cfg: ScreenConfig) -> bool:
    """The leak control must find its own target, the random one must find nothing."""
    leak = [r for r in results if r.name == CONTROL_LEAK]
    noise = [r for r in results if r.name == CONTROL_RANDOM]
    leak_ok = bool(leak) and all((r.ic_mean or 0.0) > 0.95 for r in leak)
    noise_ok = bool(noise) and all(
        r.perm_z is not None and abs(r.perm_z) < cfg.t_threshold + 1.0 for r in noise
    )
    return leak_ok and noise_ok
