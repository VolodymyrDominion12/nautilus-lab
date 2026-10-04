from __future__ import annotations

from decimal import Decimal

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.decision_trace import (
    Stage,
    TraceStep,
    Verdict,
    margin_pct,
    step,
    warmup_step,
)
from nautilus_lab.domain.formulaic_alphas import FormulaicAlphaEngine
from nautilus_lab.domain.ml_classifier import DirectionClassifier, DirectionProbabilities
from nautilus_lab.domain.signals import Signal, SignalSide


class FormulaicLgbmStrategy:
    """Direction from formulaic OHLCV features + injected classifier (LightGBM or heuristic)."""

    def __init__(
        self,
        *,
        instrument_id: str,
        classifier: DirectionClassifier,
        threshold: Decimal = Decimal("0.55"),
        min_hold_bars: int = 0,
    ) -> None:
        if threshold <= 0 or threshold >= 1:
            raise ValueError("threshold must be in (0, 1)")
        if min_hold_bars < 0:
            raise ValueError("min_hold_bars must be >= 0")
        self._instrument_id = instrument_id
        self._classifier = classifier
        self._threshold = threshold
        self._min_hold_bars = min_hold_bars
        self._bars_held = 0
        self._engine = FormulaicAlphaEngine()
        self._position: SignalSide | None = None
        self._seen = 0
        self._trace: tuple[TraceStep, ...] = ()

    @property
    def last_trace(self) -> tuple[TraceStep, ...]:
        return self._trace

    def _explain(
        self, verdict: Verdict, result: str | None, probs: DirectionProbabilities, note: str
    ) -> None:
        self._trace = (
            step(
                Stage.STRATEGY,
                "FormulaicLgbm",
                verdict,
                result=result,
                values={
                    "p_up": probs.up,
                    "p_down": probs.down,
                    "p_flat": probs.flat,
                    "holding": None if self._position is None else self._position.value,
                    # The stronger direction against the entry threshold (-5% = 5% short).
                    "margin_pct": margin_pct(max(probs.up, probs.down), self._threshold),
                },
                thresholds={"threshold": self._threshold},
                note=note,
            ),
        )

    def on_bar(self, bar: OhlcvBar) -> Signal | None:
        self._seen += 1
        features = self._engine.update(bar)
        if features is None:
            self._trace = (warmup_step("FormulaicAlphaEngine", seen=self._seen),)
            return None
        probs = self._classifier.predict(features)
        if self._position is not None:
            self._bars_held += 1
            if self._bars_held < self._min_hold_bars:
                self._explain(
                    Verdict.INFO,
                    None,
                    probs,
                    f"min_hold_bars={self._min_hold_bars} not reached (held {self._bars_held})",
                )
                return None
            if (
                probs.flat >= self._threshold
                or (self._position is SignalSide.BUY and probs.down > probs.up)
                or (self._position is SignalSide.SELL and probs.up > probs.down)
            ):
                self._explain(Verdict.EMIT, "flat", probs, "model no longer supports the position")
                self._position = None
                self._bars_held = 0
                return self._signal(bar, SignalSide.FLAT, "formulaic exit")
            self._explain(Verdict.INFO, None, probs, "model still supports the position: hold")
            return None
        if probs.up >= self._threshold and probs.up > probs.down:
            self._explain(Verdict.EMIT, "buy", probs, "P(up) passes the threshold")
            self._position = SignalSide.BUY
            self._bars_held = 0
            return self._signal(bar, SignalSide.BUY, f"formulaic up p={probs.up}")
        if probs.down >= self._threshold and probs.down > probs.up:
            self._explain(Verdict.EMIT, "sell", probs, "P(down) passes the threshold")
            self._position = SignalSide.SELL
            self._bars_held = 0
            return self._signal(bar, SignalSide.SELL, f"formulaic down p={probs.down}")
        self._explain(Verdict.INFO, None, probs, "no direction passes the threshold")
        return None

    def _signal(self, bar: OhlcvBar, side: SignalSide, reason: str) -> Signal:
        return Signal(
            instrument_id=self._instrument_id,
            side=side,
            bar_ts_utc=bar.ts_utc,
            reason=reason,
        )
