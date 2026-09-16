from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from nautilus_lab.domain.errors import ModelArtifactMissingError
from nautilus_lab.domain.ml_classifier import (
    DirectionProbabilities,
    probabilities_from_ordered_scores,
)


class HeuristicDirectionClassifier:
    """Research fallback when LightGBM is not installed."""

    def predict(self, features: tuple[Decimal, ...]) -> DirectionProbabilities:
        if not features:
            return DirectionProbabilities(
                up=Decimal("0.33"),
                down=Decimal("0.33"),
                flat=Decimal("0.34"),
            )
        obi = features[0]
        if obi > Decimal("0.2"):
            return DirectionProbabilities(
                up=Decimal("0.6"), down=Decimal("0.2"), flat=Decimal("0.2")
            )
        if obi < Decimal("-0.2"):
            return DirectionProbabilities(
                up=Decimal("0.2"), down=Decimal("0.6"), flat=Decimal("0.2")
            )
        return DirectionProbabilities(up=Decimal("0.25"), down=Decimal("0.25"), flat=Decimal("0.5"))


def require_model_path(model_path: str | None, *, robot: str) -> str:
    """Fail closed when a robot that needs an offline booster has no file."""
    if model_path is None or not model_path.strip():
        raise ModelArtifactMissingError(
            f"robot {robot!r} needs a trained booster; set the model path and train offline"
        )
    path = Path(model_path)
    if not path.is_file():
        raise ModelArtifactMissingError(
            f"robot {robot!r} model file not found: {model_path}. Train offline first."
        )
    return str(path)


class LightGBMDirectionClassifier:
    """Optional LightGBM adapter. Model path injected at composition root."""

    def __init__(self, model_path: str) -> None:
        try:
            import lightgbm as lgb
        except ImportError as exc:
            raise RuntimeError(
                "lightgbm extra not installed; use HeuristicDirectionClassifier"
            ) from exc
        self._model = lgb.Booster(model_file=model_path)

    def predict(self, features: tuple[Decimal, ...]) -> DirectionProbabilities:
        import numpy as np

        vector = np.array([[float(item) for item in features]], dtype=np.float64)
        raw = np.asarray(self._model.predict(vector)[0], dtype=np.float64)
        scores = tuple(Decimal(str(item)) for item in raw.tolist())
        return probabilities_from_ordered_scores(scores)


class LightGBMSuccessClassifier:
    """Binary LightGBM: P(primary signal hits take-profit first)."""

    def __init__(self, model_path: str) -> None:
        try:
            import lightgbm as lgb
        except ImportError as exc:
            raise RuntimeError("lightgbm extra not installed; train meta-label offline") from exc
        self._model = lgb.Booster(model_file=model_path)

    def predict_success(self, features: tuple[Decimal, ...]) -> Decimal:
        import numpy as np

        vector = np.array([[float(item) for item in features]], dtype=np.float64)
        raw = self._model.predict(vector)[0]
        probability = Decimal(str(raw))
        if probability < 0:
            return Decimal("0")
        if probability > 1:
            return Decimal("1")
        return probability
