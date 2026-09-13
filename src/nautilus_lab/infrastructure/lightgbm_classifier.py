from __future__ import annotations

from decimal import Decimal

from nautilus_lab.domain.ml_classifier import DirectionProbabilities


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


class LightGBMDirectionClassifier:
    """Optional LightGBM adapter. Model path injected at composition root."""

    def __init__(self, model_path: str) -> None:
        try:
            import lightgbm as lgb  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "lightgbm extra not installed; use HeuristicDirectionClassifier"
            ) from exc
        self._model = lgb.Booster(model_file=model_path)

    def predict(self, features: tuple[Decimal, ...]) -> DirectionProbabilities:
        import numpy as np

        vector = np.array([[float(item) for item in features]], dtype=np.float64)
        raw = self._model.predict(vector)[0]
        if len(raw) == 3:
            up, down, flat = (Decimal(str(value)) for value in raw)
        else:
            up = Decimal(str(raw[0]))
            down = Decimal(str(1 - raw[0]))
            flat = Decimal("0")
        total = up + down + flat
        if total > 0:
            up, down, flat = up / total, down / total, flat / total
        return DirectionProbabilities(up=up, down=down, flat=flat)
