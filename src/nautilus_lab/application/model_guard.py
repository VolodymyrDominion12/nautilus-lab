"""Refuse research runs whose ML model has already seen the scored bars (A1/A2).

Walk-forward protects *parameters* by selecting them on in-sample bars only; a booster
is not a grid parameter, so that protocol never covered it. This guard does: before
any out-of-sample fold (or an audit block) is scored, the model's card must show it
was trained on this robot and series, strictly before the first scored bar.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from nautilus_lab.application.dtos import BacktestRequest
from nautilus_lab.domain.errors import ModelArtifactMissingError
from nautilus_lab.domain.model_card import ModelCard, ModelLeakError, card_problems
from nautilus_lab.domain.regime import RobotName


class ModelCardSource(Protocol):
    def card_for(self, model_path: str) -> ModelCard | None: ...

    def sha256_of(self, model_path: str) -> str | None: ...


def model_path_for(request: BacktestRequest) -> str | None:
    """The booster a robot loads, or None when the robot uses no model."""
    if request.robot is RobotName.FORMULAIC_LGBM:
        return request.formulaic_model_path or ""
    if request.robot is RobotName.META_LABEL:
        return request.meta_label_model_path or ""
    if request.robot is RobotName.ML_OBI:
        return request.ml_obi_model_path or ""
    return None


def require_clean_model(
    request: BacktestRequest,
    *,
    first_clean_ts: datetime,
    source: ModelCardSource | None,
) -> None:
    """Raise unless the robot's model is admissible for bars from `first_clean_ts` on.

    `source=None` disables the check (unit tests with fake engines); the composition
    root always wires a real source.
    """
    model_path = model_path_for(request)
    if model_path is None or source is None:
        return
    if not model_path.strip():
        raise ModelArtifactMissingError(
            f"robot {request.robot.value!r} needs a trained model; set its *_MODEL_PATH"
        )
    problems = card_problems(
        source.card_for(model_path),
        robot=request.robot.value,
        bar_type=request.bar_type,
        first_clean_ts=first_clean_ts,
        model_sha256=source.sha256_of(model_path),
    )
    if problems:
        raise ModelLeakError(f"model {model_path} refused: " + "; ".join(problems))
