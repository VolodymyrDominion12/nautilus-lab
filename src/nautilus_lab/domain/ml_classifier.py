from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

# Canonical LightGBM class indices for direction models. Training (`label_map`)
# and inference (`probabilities_from_ordered_scores`) must share this order:
# predict()[0] = P(down), [1] = P(flat), [2] = P(up). Unpacking as (up, down, flat)
# silently swaps sides.
DIRECTION_CLASSES: tuple[str, ...] = ("down", "flat", "up")
DIRECTION_CLASS_INDEX: dict[str, int] = {
    name: index for index, name in enumerate(DIRECTION_CLASSES)
}


@dataclass(frozen=True, slots=True)
class DirectionProbabilities:
    up: Decimal
    down: Decimal
    flat: Decimal


class DirectionClassifier(Protocol):
    def predict(self, features: tuple[Decimal, ...]) -> DirectionProbabilities: ...


class SuccessClassifier(Protocol):
    """Binary P(the primary signal will hit take-profit first)."""

    def predict_success(self, features: tuple[Decimal, ...]) -> Decimal: ...


def probabilities_from_ordered_scores(scores: tuple[Decimal, ...]) -> DirectionProbabilities:
    """Map a 3-class score vector in `DIRECTION_CLASSES` order to named probabilities."""
    if len(scores) != len(DIRECTION_CLASSES):
        raise ValueError(
            f"expected {len(DIRECTION_CLASSES)} class scores in {DIRECTION_CLASSES} order, "
            f"got {len(scores)}"
        )
    by_name = dict(zip(DIRECTION_CLASSES, scores, strict=True))
    total = sum(scores, Decimal("0"))
    if total <= 0:
        third = Decimal("1") / Decimal("3")
        return DirectionProbabilities(up=third, down=third, flat=third)
    return DirectionProbabilities(
        up=by_name["up"] / total,
        down=by_name["down"] / total,
        flat=by_name["flat"] / total,
    )
