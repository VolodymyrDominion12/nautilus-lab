"""Model card: what an offline-trained booster was trained on (docs/27 wave 4, A1/A2).

A booster file alone says nothing about the data behind it. The 2026-09-26 matrix
showed what that costs: the `formulaic_lgbm` model was trained on a window that fully
covered every out-of-sample fold (+14.73% OOS became -5.41% once retrained), and the
ETH model silently ran on BTC bars. The card travels next to the model file and lets
a research run refuse a model that has already seen its out-of-sample bars, belongs
to another instrument or interval, or was swapped without a new card.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from nautilus_lab.domain.errors import DomainError

MODEL_CARD_SCHEMA = "model_card/1"


class ModelLeakError(DomainError):
    """A research run was about to use a model that cannot give an honest OOS number."""


@dataclass(frozen=True, slots=True)
class ModelCard:
    """Provenance of one trained booster.

    `train_last_ts` is the timestamp of the last bar (or book) whose information the
    model saw, labels included. An out-of-sample window is clean only when its first
    bar comes strictly after it.
    """

    robot: str
    instrument_id: str
    # The exact bar series the features came from; None for book-based models.
    bar_type: str | None
    train_first_ts: datetime
    train_last_ts: datetime
    horizon: int
    rows: int
    model_sha256: str
    schema: str = MODEL_CARD_SCHEMA

    def __post_init__(self) -> None:
        if self.train_first_ts.tzinfo is None or self.train_last_ts.tzinfo is None:
            raise ValueError("model card timestamps must be timezone-aware UTC")
        if self.train_last_ts < self.train_first_ts:
            raise ValueError("model card train_last_ts is before train_first_ts")
        if not self.model_sha256:
            raise ValueError("model card needs the model file sha256")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "robot": self.robot,
            "instrument_id": self.instrument_id,
            "bar_type": self.bar_type,
            "train_first_ts": self.train_first_ts.isoformat(),
            "train_last_ts": self.train_last_ts.isoformat(),
            "horizon": self.horizon,
            "rows": self.rows,
            "model_sha256": self.model_sha256,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelCard:
        schema = str(data.get("schema", ""))
        if schema != MODEL_CARD_SCHEMA:
            raise ValueError(f"unsupported model card schema {schema!r}")
        bar_type = data.get("bar_type")
        return cls(
            robot=str(data["robot"]),
            instrument_id=str(data["instrument_id"]),
            bar_type=None if bar_type is None else str(bar_type),
            train_first_ts=datetime.fromisoformat(str(data["train_first_ts"])),
            train_last_ts=datetime.fromisoformat(str(data["train_last_ts"])),
            horizon=int(data["horizon"]),
            rows=int(data["rows"]),
            model_sha256=str(data["model_sha256"]),
            schema=schema,
        )


def card_problems(
    card: ModelCard | None,
    *,
    robot: str,
    bar_type: str,
    first_clean_ts: datetime,
    model_sha256: str | None,
) -> tuple[str, ...]:
    """Every reason this model cannot be used on a run whose scored bars start at
    `first_clean_ts`. Empty means the model is admissible.
    """
    if card is None:
        return (
            "model has no card (<model>.card.json); retrain with `lab ml train --end <date>` "
            "so the training window is recorded",
        )
    problems: list[str] = []
    if card.robot != robot:
        problems.append(f"card is for robot {card.robot!r}, run is {robot!r}")
    if card.bar_type is not None:
        if card.bar_type != bar_type:
            problems.append(f"card bar_type {card.bar_type} != run bar_type {bar_type}")
    elif not bar_type.startswith(f"{card.instrument_id}-"):
        problems.append(f"card instrument {card.instrument_id} does not match {bar_type}")
    if model_sha256 is None:
        problems.append("model file is missing")
    elif model_sha256 != card.model_sha256:
        problems.append("model file sha256 differs from its card (file replaced after training)")
    if card.train_last_ts >= first_clean_ts:
        problems.append(
            f"training saw data up to {card.train_last_ts.isoformat()}, but scored bars "
            f"start at {first_clean_ts.isoformat()}: the model has seen them (leak)"
        )
    return tuple(problems)
