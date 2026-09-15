"""Offline scoring of a DSL recipe on closed bars. Never called from on_bar."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.counterfactual import perturb_bars
from nautilus_lab.domain.factor_dsl import (
    FactorNode,
    crowding_hits,
    evaluate_recipe,
    parse_recipe,
    recipe_complexity,
    recipe_depth,
)
from nautilus_lab.domain.formulaic_alphas import FEATURE_NAMES, FormulaicAlphaEngine


@dataclass(frozen=True, slots=True)
class RecipeScore:
    formula: str
    complexity: Decimal
    depth: int
    observations: int
    information_coefficient: Decimal | None
    hit_rate: Decimal | None
    counterfactual_ic: Decimal | None
    crowding_index: tuple[int, ...]


def feature_rows(bars: Sequence[OhlcvBar]) -> list[dict[str, Decimal] | None]:
    """One feature map per bar. None until the formulaic engine is warmed up."""
    engine = FormulaicAlphaEngine()
    rows: list[dict[str, Decimal] | None] = []
    for bar in bars:
        values = engine.update(bar)
        if values is None:
            rows.append(None)
            continue
        rows.append(dict(zip(FEATURE_NAMES, values, strict=True)))
    return rows


def score_recipe(
    bars: Sequence[OhlcvBar],
    formula: str,
    *,
    horizon_bars: int,
    expected_sign: int = 1,
    pool: Sequence[FactorNode] = (),
    perturb_magnitude: Decimal = Decimal("0.02"),
    perturb_seed: int = 1,
) -> RecipeScore:
    """IC of the recipe vs future close-to-close return, plus a counterfactual IC."""
    if horizon_bars < 1:
        raise ValueError("horizon_bars must be >= 1")
    if expected_sign not in {1, -1}:
        raise ValueError("expected_sign must be +1 or -1")
    node = parse_recipe(formula)
    rows = feature_rows(bars)
    ic, hit_rate, observations = _ic_on_rows(
        bars,
        rows,
        node,
        horizon_bars=horizon_bars,
        expected_sign=expected_sign,
    )
    shocked = perturb_bars(bars, magnitude=perturb_magnitude, seed=perturb_seed)
    shocked_rows = feature_rows(shocked)
    counterfactual_ic, _, _ = _ic_on_rows(
        shocked,
        shocked_rows,
        node,
        horizon_bars=horizon_bars,
        expected_sign=expected_sign,
    )
    return RecipeScore(
        formula=formula,
        complexity=recipe_complexity(node),
        depth=recipe_depth(node),
        observations=observations,
        information_coefficient=ic,
        hit_rate=hit_rate,
        counterfactual_ic=counterfactual_ic,
        crowding_index=crowding_hits(node, pool),
    )


def _ic_on_rows(
    bars: Sequence[OhlcvBar],
    rows: Sequence[Mapping[str, Decimal] | None],
    node: FactorNode,
    *,
    horizon_bars: int,
    expected_sign: int,
) -> tuple[Decimal | None, Decimal | None, int]:
    predictions: list[Decimal] = []
    realised: list[Decimal] = []
    for index in range(len(bars) - horizon_bars):
        row = rows[index]
        if row is None:
            continue
        value = evaluate_recipe(node, _filled(rows), index=index)
        future = _forward_return(bars, index, horizon_bars)
        if value is None or future is None:
            continue
        predictions.append(value * Decimal(expected_sign))
        realised.append(future)
    observations = len(predictions)
    if observations == 0:
        return None, None, 0
    hits = sum(
        1
        for pred, actual in zip(predictions, realised, strict=True)
        if (pred > 0 and actual > 0) or (pred < 0 and actual < 0)
    )
    hit_rate = Decimal(hits) / Decimal(observations)
    return pearson(predictions, realised), hit_rate, observations


def _filled(rows: Sequence[Mapping[str, Decimal] | None]) -> list[dict[str, Decimal]]:
    """Blank maps for warmup bars so the DSL evaluator can skip them as missing."""
    return [dict(row) if row is not None else {} for row in rows]


def _forward_return(bars: Sequence[OhlcvBar], index: int, horizon: int) -> Decimal | None:
    current = bars[index].close
    future = bars[index + horizon].close
    if current <= 0:
        return None
    return (future - current) / current


def pearson(xs: Sequence[Decimal], ys: Sequence[Decimal]) -> Decimal | None:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    count = Decimal(len(xs))
    mean_x = sum(xs, Decimal("0")) / count
    mean_y = sum(ys, Decimal("0")) / count
    cov = sum(((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)), Decimal("0"))
    var_x = sum(((x - mean_x) ** 2 for x in xs), Decimal("0"))
    var_y = sum(((y - mean_y) ** 2 for y in ys), Decimal("0"))
    if var_x <= 0 or var_y <= 0:
        return None
    return cov / (var_x.sqrt() * var_y.sqrt())
