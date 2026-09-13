from __future__ import annotations

from decimal import Decimal

from nautilus_lab.domain.microstructure import (
    liquidity_fade_velocity,
    order_book_imbalance,
    weighted_order_flow_imbalance,
)
from nautilus_lab.domain.ml_classifier import DirectionClassifier, DirectionProbabilities
from nautilus_lab.domain.order_book import OrderBookSnapshot
from nautilus_lab.domain.signals import Signal, SignalSide


class MlObiStrategy:
    """Classify short-term direction from microstructure features."""

    def __init__(
        self,
        *,
        instrument_id: str,
        classifier: DirectionClassifier,
        threshold: Decimal = Decimal("0.55"),
    ) -> None:
        self._instrument_id = instrument_id
        self._classifier = classifier
        self._threshold = threshold
        self._previous: OrderBookSnapshot | None = None

    def on_book(self, snapshot: OrderBookSnapshot) -> Signal | None:

        snapshot.validate()
        if self._previous is None:
            self._previous = snapshot
            return None
        features = (
            order_book_imbalance(snapshot),
            weighted_order_flow_imbalance(snapshot, self._previous),
            liquidity_fade_velocity(snapshot, self._previous),
        )
        probs = self._classifier.predict(features)
        side = _pick_side(probs, self._threshold)
        self._previous = snapshot
        if side is None:
            return None
        return Signal(
            instrument_id=self._instrument_id,
            side=side,
            bar_ts_utc=snapshot.ts_utc,
            reason="ml_obi",
        )


def _pick_side(probs: DirectionProbabilities, threshold: Decimal) -> SignalSide | None:
    best = max(probs.up, probs.down, probs.flat)
    if best < threshold:
        return None
    if best is probs.up:
        return SignalSide.BUY
    if best is probs.down:
        return SignalSide.SELL
    return SignalSide.FLAT
