from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.decision_trace import (
    Stage,
    TraceStep,
    Verdict,
    margin_pct,
    step,
)
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
        self._meta_step: TraceStep | None = None
        self._trace: tuple[TraceStep, ...] = ()

    @property
    def last_trace(self) -> tuple[TraceStep, ...]:
        """The primary robot's own trace, then the classifier's verdict on its signal.

        Without the classifier step a rejected entry looks exactly like "no signal": the
        primary did fire, but the log could not say so, nor with which probability. That
        rejected-signal set is the whole point of a meta-label, so it is logged as a
        `BLOCK` on the `meta_label` filter with the primary side and the margin to the
        threshold (see `Outcome.SIGNAL_VETOED`).
        """
        return self._trace

    def on_bar(self, bar: OhlcvBar) -> Signal | None:
        self._meta_step = None
        signal = self._decide(bar)
        primary_trace = getattr(self._primary, "last_trace", ())
        steps = list(primary_trace) if isinstance(primary_trace, (tuple, list)) else []
        if self._meta_step is not None:
            steps.append(self._meta_step)
        self._trace = tuple(steps)
        return signal

    def _decide(self, bar: OhlcvBar) -> Signal | None:
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
            self._meta_step = step(
                Stage.FILTER,
                "meta_label",
                Verdict.BLOCK,
                result="reject",
                values={"primary_side": primary.side.value},
                thresholds={"threshold": self._threshold},
                note="formulaic features still warming up: entry not scored",
            )
            return None
        vector = encode_meta_features(features, primary.side)
        raw = self._classifier.predict_success(vector)
        # A float from a model would not be a `TraceValue`; the log keeps Decimals only.
        probability = raw if isinstance(raw, Decimal) else Decimal(str(raw))
        accepted = probability >= self._threshold
        self._meta_step = step(
            Stage.FILTER,
            "meta_label",
            Verdict.PASS if accepted else Verdict.BLOCK,
            result="accept" if accepted else "reject",
            values={
                "p_success": probability,
                "primary_side": primary.side.value,
                "margin_pct": margin_pct(probability, self._threshold),
            },
            thresholds={"threshold": self._threshold},
            note=(
                "P(take-profit) passes the threshold: take the primary signal"
                if accepted
                else "P(take-profit) below the threshold: primary signal rejected"
            ),
        )
        if not accepted:
            return None
        return Signal(
            instrument_id=primary.instrument_id,
            side=primary.side,
            bar_ts_utc=primary.bar_ts_utc,
            reason=f"meta-label p={probability} {primary.reason}",
            regime=primary.regime,
        )
