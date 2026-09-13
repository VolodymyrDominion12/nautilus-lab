from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DirectionProbabilities:
    up: Decimal
    down: Decimal
    flat: Decimal


class DirectionClassifier(Protocol):
    def predict(self, features: tuple[Decimal, ...]) -> DirectionProbabilities: ...
