from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.formulaic_alphas import FormulaicAlphaEngine
from nautilus_lab.domain.ml_classifier import SuccessClassifier
from nautilus_lab.domain.signals import Signal, SignalSide


class PrimaryRobot(Protocol):
    def on_bar(self, bar: OhlcvBar) -> Signal | None: ...


def encode_meta_features(formulaic: tuple[Decimal, ...], side: SignalSide) -> tuple[Decimal, ...]:
    """Append the signed entry side (+1 buy, -1 sell) to the formulaic vector."""
    if side not in (SignalSide.BUY, SignalSide.SELL):
        raise ValueError("meta features are only defined for an entry side")
    signed = Decimal("1") if side is SignalSide.BUY else Decimal("-1")
    return (*formulaic, signed)


class MetaLabelStrategy:
    """Gate a primary robot's entries with P(triple-barrier take-profit). Exits pass."""

    def __init__(
        self,
        *,
        instrument_id: str,
        primary: PrimaryRobot,
        classifier: SuccessClassifier,
        threshold: Decimal = Decimal("0.55"),
    ) -> None:
        if threshold <= 0 or threshold >= 1:
            raise ValueError("threshold must be in (0, 1)")
        self._instrument_id = instrument_id
        self._primary = primary
        self._classifier = classifier
        self._threshold = threshold
        self._engine = FormulaicAlphaEngine()
        self._position: SignalSide | None = None

    def on_bar(self, bar: OhlcvBar) -> Signal | None:
        features = self._engine.update(bar)
        primary = self._primary.on_bar(bar)
        if self._position is not None:
            return self._maybe_exit(bar, primary, features)
        if primary is None or primary.side is SignalSide.FLAT:
            return None
        return self._maybe_enter(primary, features)

    def _maybe_exit(
        self,
        bar: OhlcvBar,
        primary: Signal | None,
        features: tuple[Decimal, ...] | None,
    ) -> Signal | None:
        if primary is None:
            return None
        if primary.side is SignalSide.FLAT:
            self._position = None
            return primary
        if primary.side is self._position:
            return None
        self._position = None
        accepted = self._accept_entry(primary, features)
        if accepted is not None:
            self._position = accepted.side
            return accepted
        return Signal(
            instrument_id=self._instrument_id,
            side=SignalSide.FLAT,
            bar_ts_utc=bar.ts_utc,
            reason="meta-label flatten; opposite primary rejected",
            regime=primary.regime,
        )

    def _maybe_enter(
        self,
        primary: Signal,
        features: tuple[Decimal, ...] | None,
    ) -> Signal | None:
        accepted = self._accept_entry(primary, features)
        if accepted is None:
            return None
        self._position = accepted.side
        return accepted

    def _accept_entry(
        self,
        primary: Signal,
        features: tuple[Decimal, ...] | None,
    ) -> Signal | None:
        if features is None:
            return None
        vector = encode_meta_features(features, primary.side)
        probability = self._classifier.predict_success(vector)
        if probability < self._threshold:
            return None
        return Signal(
            instrument_id=primary.instrument_id,
            side=primary.side,
            bar_ts_utc=primary.bar_ts_utc,
            reason=f"meta-label p={probability} {primary.reason}",
            regime=primary.regime,
        )
