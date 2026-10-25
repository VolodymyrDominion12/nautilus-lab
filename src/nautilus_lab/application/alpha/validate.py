"""Preregistered validation of screen survivors: fixed hypotheses, one look.

The screen chooses on exploration, and choosing is exactly what validation must not
do. This module evaluates only what was written down beforehand:

1. **Register.** A hypothesis fixes its legs (signal + direction), horizon, book and
   pass criteria. The file is hashed, the hash is its identity, and it is committed
   before any validation number exists.
2. **Run.** The validation zone is evaluated once per hash. The outcome is appended to
   `research/alpha_validation_log.jsonl`, pass or fail. A second run of the same hash is
   refused. A changed hypothesis is a new hash, and the log shows both.

Criteria are one-sided in the registered direction. They are Bonferroni-corrected over
the hypotheses in one registration, so registering many weak ideas does not buy a pass.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from nautilus_lab.application.alpha.operators import cs_rank, neutralise, ts_sum, unit_gross
from nautilus_lab.application.alpha.panel import BoolArray, FloatArray, Panel
from nautilus_lab.application.alpha.screen import (
    BookStats,
    bar_returns,
    block_t,
    book_stats,
    decision_rows,
    forward_returns,
    only_members,
    pnl_rows,
    rank_ic,
    residual_forward,
    zone_segments,
)
from nautilus_lab.application.alpha.signals import build_context, template
from nautilus_lab.domain.data_zone import DataZone, ZonePolicy

PREREG_KIND = "alpha-validation/v1"


@dataclass(frozen=True)
class Leg:
    signal: str
    direction: int  # +1: long high scores, -1: short them

    def __post_init__(self) -> None:
        if self.direction not in (1, -1):
            raise ValueError("leg direction must be +1 or -1")
        template(self.signal)  # unknown signal -> KeyError at registration, not at run


@dataclass(frozen=True)
class Criteria:
    alpha: float = 0.05  # family-wise, one-sided; split over the hypotheses
    min_net_sharpe: float = 0.5
    max_abs_market_corr: float = 0.30
    min_positive_years: float = 2 / 3


@dataclass(frozen=True)
class Hypothesis:
    id: str
    legs: tuple[Leg, ...]
    horizon: int
    rationale: str
    beta_neutral: bool = True

    def __post_init__(self) -> None:
        if not self.legs:
            raise ValueError(f"hypothesis {self.id} has no legs")
        if self.horizon < 1:
            raise ValueError("horizon must be >= 1 bar")


@dataclass(frozen=True)
class Preregistration:
    hypotheses: tuple[Hypothesis, ...]
    symbols: tuple[str, ...]
    panel_label: str
    cost_bps: float
    criteria: Criteria
    exploration_report: str
    created_at: str
    note: str = ""
    universe: str = ""  # path of the point-in-time universe file; "" = every coin with data
    universe_sha256: str = ""
    kind: str = PREREG_KIND

    def payload(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def digest(self) -> str:
        canonical = json.dumps(self.payload(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class HypothesisOutcome:
    id: str
    ic_mean: float | None
    t_block: float | None
    p_one_sided: float | None
    p_threshold: float
    book: BookStats
    net_sharpe_by_year: dict[int, float]
    passed: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ValidationRun:
    digest: str
    ran_at: str
    windows: tuple[tuple[str, str], ...]
    outcomes: tuple[HypothesisOutcome, ...] = field(default=())


# --------------------------------------------------------------------------- files


def write_preregistration(prereg: Preregistration, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = prereg.created_at.replace(":", "").replace("-", "")[:15]
    path = directory / f"alpha-{stamp}-{prereg.digest}.json"
    data = prereg.payload() | {"digest": prereg.digest}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


def read_preregistration(path: Path) -> Preregistration:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("kind") != PREREG_KIND:
        raise ValueError(f"{path} is not an {PREREG_KIND} preregistration")
    stored = data.pop("digest", None)
    prereg = Preregistration(
        hypotheses=tuple(
            Hypothesis(
                id=h["id"],
                legs=tuple(Leg(**leg) for leg in h["legs"]),
                horizon=int(h["horizon"]),
                rationale=h["rationale"],
                beta_neutral=bool(h["beta_neutral"]),
            )
            for h in data["hypotheses"]
        ),
        symbols=tuple(data["symbols"]),
        panel_label=data["panel_label"],
        cost_bps=float(data["cost_bps"]),
        criteria=Criteria(**data["criteria"]),
        exploration_report=data["exploration_report"],
        created_at=data["created_at"],
        note=data.get("note", ""),
        universe=data.get("universe", ""),
        universe_sha256=data.get("universe_sha256", ""),
    )
    if stored != prereg.digest:
        raise ValueError(
            f"{path} was edited after registration (stored digest {stored}, "
            f"content digest {prereg.digest}); register a new hypothesis instead"
        )
    return prereg


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def already_run(log: Path, digest: str) -> bool:
    if not log.is_file():
        return False
    for raw in log.read_text(encoding="utf-8").splitlines():
        try:
            if json.loads(raw).get("digest") == digest:
                return True
        except json.JSONDecodeError:
            continue
    return False


def append_log(log: Path, run: ValidationRun) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    line = asdict(run)
    for outcome in line["outcomes"]:
        outcome["net_sharpe_by_year"] = {
            str(k): v for k, v in outcome["net_sharpe_by_year"].items()
        }
    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")


# --------------------------------------------------------------------------- run


def composite_scores(ranks: Sequence[FloatArray]) -> FloatArray:
    """Equal-weight mean of leg ranks; a coin needs every leg to be scored."""
    stacked = np.stack(list(ranks))
    complete = np.isfinite(stacked).all(axis=0)
    mean = np.where(complete, np.nan_to_num(stacked).mean(axis=0), np.nan)
    result: FloatArray = mean
    return result


def run_validation(
    panel: Panel,
    prereg: Preregistration,
    *,
    policy: ZonePolicy,
    log: Path,
    ran_at: datetime | None = None,
    min_names: int = 5,
    membership: BoolArray | None = None,
) -> ValidationRun:
    """Evaluate every registered hypothesis on the validation zone, exactly once.

    `membership` must be the point-in-time universe the registration names (see
    `Preregistration.universe`). The script loads it from that file, never from
    something chosen after the fact.
    """
    if already_run(log, prereg.digest):
        raise PermissionError(
            f"preregistration {prereg.digest} was already run on validation; "
            "one look per hypothesis. A new idea is a new registration."
        )
    missing = set(prereg.symbols) - set(panel.symbols)
    if missing:
        raise ValueError(f"panel lacks registered symbols: {sorted(missing)}")
    held = [s for s in prereg.symbols if policy.symbol_is_holdout(s)]
    if held:
        raise PermissionError(f"registered symbols include holdout coins: {held}")

    view = panel.select_symbols(prereg.symbols)
    member = None
    if membership is not None:
        member = membership[:, [panel.column(s) for s in prereg.symbols]]
    ctx = build_context(view, min_names, member)
    segment = zone_segments(view, policy, DataZone.VALIDATION)
    rows_pnl = pnl_rows(segment)
    returns_1 = bar_returns(view)
    years = view.years()
    block = 7 * ctx.bars_per_day
    k = len(prereg.hypotheses)
    threshold = prereg.criteria.alpha / k
    cache: dict[str, FloatArray] = {}

    outcomes: list[HypothesisOutcome] = []
    for hyp in prereg.hypotheses:
        leg_ranks = []
        for leg in hyp.legs:
            if leg.signal not in cache:
                raw = only_members(template(leg.signal).compute(ctx), member)
                cache[leg.signal] = cs_rank(raw, min_names)
            leg_ranks.append(leg.direction * cache[leg.signal])
        score = composite_scores(leg_ranks)
        forward = only_members(forward_returns(view, hyp.horizon), member)
        target = residual_forward(forward, ctx.beta, min_names)
        rows = decision_rows(segment, hyp.horizon)
        ic = rank_ic(cs_rank(score, min_names)[rows], cs_rank(target, min_names)[rows], min_names)
        block_id = (np.arange(view.shape[0]) // max(block, hyp.horizon))[rows]
        t_stat, _ = block_t(ic, block_id)
        ic_mean = float(np.nanmean(ic)) if np.isfinite(ic).any() else None
        p_value = None if t_stat is None else 0.5 * math.erfc(t_stat / math.sqrt(2.0))

        weights = neutralise(score, ctx.beta) if hyp.beta_neutral else score
        book = book_stats(
            weights,
            hyp.horizon,
            returns_1,
            ctx.market,
            rows_pnl,
            cost_bps=prereg.cost_bps,
            bars_per_year=view.bars_per_year,
        )
        by_year = _net_sharpe_by_year(
            weights,
            hyp.horizon,
            returns_1,
            rows_pnl,
            years,
            prereg.cost_bps,
            view.bars_per_year,
            min_bars=60 * ctx.bars_per_day,
        )
        reasons = _failures(p_value, threshold, book, by_year, prereg.criteria)
        outcomes.append(
            HypothesisOutcome(
                id=hyp.id,
                ic_mean=ic_mean,
                t_block=t_stat,
                p_one_sided=p_value,
                p_threshold=threshold,
                book=book,
                net_sharpe_by_year=by_year,
                passed=not reasons,
                reasons=tuple(reasons),
            )
        )

    run = ValidationRun(
        digest=prereg.digest,
        ran_at=(ran_at or datetime.now(UTC)).isoformat(timespec="seconds"),
        windows=tuple(
            (w.start.date().isoformat(), w.end.date().isoformat())
            for w in policy.windows(DataZone.VALIDATION)
        ),
        outcomes=tuple(outcomes),
    )
    append_log(log, run)
    return run


def _net_sharpe_by_year(
    weights: FloatArray,
    horizon: int,
    returns: FloatArray,
    rows: np.ndarray,
    years: np.ndarray,
    cost_bps: float,
    bars_per_year: float,
    *,
    min_bars: int,
) -> dict[int, float]:
    target = np.nan_to_num(unit_gross(weights), nan=0.0)
    held = ts_sum(target, horizon) / horizon
    held[: horizon - 1] = np.cumsum(target, axis=0)[: horizon - 1] / horizon
    held = np.nan_to_num(held, nan=0.0)
    previous = np.zeros_like(held)
    previous[1:] = held[:-1]
    pnl = (previous * np.nan_to_num(returns)).sum(axis=1)
    net = pnl - np.abs(held - previous).sum(axis=1) * cost_bps / 1e4
    out: dict[int, float] = {}
    for year in np.unique(years[rows]):
        mask = rows & (years == year)
        values = net[mask]
        spread = float(values.std(ddof=1)) if values.size > 1 else 0.0
        if int(mask.sum()) >= min_bars and spread > 0:
            out[int(year)] = float(values.mean() / spread * math.sqrt(bars_per_year))
    return out


def _failures(
    p_value: float | None,
    threshold: float,
    book: BookStats,
    by_year: dict[int, float],
    criteria: Criteria,
) -> list[str]:
    reasons: list[str] = []
    if p_value is None or p_value > threshold:
        reasons.append(f"one-sided p > {threshold:.4f} (Bonferroni)")
    if book.sharpe_net is None or book.sharpe_net < criteria.min_net_sharpe:
        reasons.append(f"net Sharpe < {criteria.min_net_sharpe}")
    if book.market_corr is None or abs(book.market_corr) > criteria.max_abs_market_corr:
        reasons.append(f"|corr_mkt| > {criteria.max_abs_market_corr}")
    positive = sum(1 for v in by_year.values() if v > 0)
    if not by_year or positive / len(by_year) < criteria.min_positive_years:
        reasons.append(f"net Sharpe > 0 in fewer than {criteria.min_positive_years:.0%} of years")
    return reasons
