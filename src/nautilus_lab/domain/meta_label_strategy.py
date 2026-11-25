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
from nautilus_lab.domain.formulaic_alphas import FEATURE_NAMES, FormulaicAlphaEngine
from nautilus_lab.domain.ml_classifier import SuccessClassifier
from nautilus_lab.domain.sessions import GoldSession, classify_gold_session
from nautilus_lab.domain.signals import Signal, SignalSide
from nautilus_lab.domain.windows import RollingWindow

META_FEATURE_NAMES: tuple[str, ...] = (*FEATURE_NAMES, "signal_side")

META_CONTEXT_FEATURE_NAMES: tuple[str, ...] = (
    "premium_close",
    "premium_zscore",
    "premium_delta",
    "has_premium_index",
    "session_asia",
    "session_london",
    "session_overlap",
    "session_ny_afternoon",
)

META_FEATURE_NAMES_WITH_CONTEXT: tuple[str, ...] = (
    *META_FEATURE_NAMES,
    *META_CONTEXT_FEATURE_NAMES,
)


class PrimaryRobot(Protocol):
    def on_bar(self, bar: OhlcvBar) -> Signal | None: ...


class MetaContextExtractor:
    """Causal per-bar context features: premium-index basis and IANA DST gold sessions.

    All outputs are `Decimal`. Unknown `premium_index_close` (`None`) sets
    `has_premium_index = 0` and zeroes the basis features without polluting the
    rolling z-score window with synthetic zeros.
    """

    def __init__(self, *, zscore_window: int = 20) -> None:
        if zscore_window < 2:
            raise ValueError("zscore_window must be >= 2")
        self._premium_history = RollingWindow(zscore_window)

    def update(self, bar: OhlcvBar) -> tuple[Decimal, ...]:
        premium = bar.premium_index_close
        if premium is not None:
            self._premium_history.push(premium)
            known = self._premium_history.values()
            premium_close = premium
            has_premium = Decimal("1")
            premium_delta = known[-1] - known[-2] if len(known) >= 2 else Decimal("0")
            premium_zscore = _rolling_zscore(known, current=premium)
        else:
            premium_close = Decimal("0")
            premium_zscore = Decimal("0")
            premium_delta = Decimal("0")
            has_premium = Decimal("0")

        session = classify_gold_session(bar.ts_utc)
        return (
            premium_close,
            premium_zscore,
            premium_delta,
            has_premium,
            Decimal("1") if session is GoldSession.ASIA else Decimal("0"),
            Decimal("1") if session is GoldSession.LONDON else Decimal("0"),
            Decimal("1") if session is GoldSession.LONDON_NY_OVERLAP else Decimal("0"),
            Decimal("1") if session is GoldSession.NY_AFTERNOON else Decimal("0"),
        )


def _rolling_zscore(values: tuple[Decimal, ...], *, current: Decimal) -> Decimal:
    count = len(values)
    if count < 2:
        return Decimal("0")
    mean = sum(values, Decimal("0")) / Decimal(count)
    variance = sum(((value - mean) ** 2 for value in values), Decimal("0")) / Decimal(count)
    if variance <= 0:
        return Decimal("0")
    std = variance.sqrt()
    if std <= 0:
        return Decimal("0")
    return (current - mean) / std


def encode_meta_features(
    formulaic: tuple[Decimal, ...],
    side: SignalSide,
    *,
    context: tuple[Decimal, ...] | None = None,
) -> tuple[Decimal, ...]:
    """Append signed entry side (+1/-1) and optional 8 context features to formulaic vector."""
    if side not in (SignalSide.BUY, SignalSide.SELL):
        raise ValueError("meta features are only defined for an entry side")
    signed = Decimal("1") if side is SignalSide.BUY else Decimal("-1")
    if context is None:
        return (*formulaic, signed)
    if len(context) != len(META_CONTEXT_FEATURE_NAMES):
        raise ValueError(
            f"context vector must have {len(META_CONTEXT_FEATURE_NAMES)} features, "
            f"got {len(context)}"
        )
    return (*formulaic, signed, *context)


class MetaLabelStrategy:
    """Gate a primary robot's entries with P(triple-barrier take-profit). Exits pass."""

    def __init__(
        self,
        *,
        instrument_id: str,
        primary: PrimaryRobot,
        classifier: SuccessClassifier,
        threshold: Decimal = Decimal("0.55"),
        include_context: bool = False,
    ) -> None:
        if threshold <= 0 or threshold >= 1:
            raise ValueError("threshold must be in (0, 1)")
        expected_dim = (
            len(META_FEATURE_NAMES_WITH_CONTEXT) if include_context else len(META_FEATURE_NAMES)
        )
        model_dim = getattr(classifier, "num_features", None)
        if (
            isinstance(model_dim, int)
            and not isinstance(model_dim, bool)
            and model_dim != expected_dim
        ):
            raise ValueError(
                f"meta_label classifier expects {model_dim} features, but "
                f"META_LABEL_CONTEXT_FEATURES={str(include_context).lower()} produces "
                f"{expected_dim} features; align META_LABEL_CONTEXT_FEATURES with how "
                "the model was trained"
            )
        self._instrument_id = instrument_id
        self._primary = primary
        self._classifier = classifier
        self._threshold = threshold
        self._include_context = include_context
        self._engine = FormulaicAlphaEngine()
        self._context_extractor = MetaContextExtractor() if include_context else None
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

    def on_trade_tick(self, *, is_buy: bool, volume: Decimal, dt_seconds: Decimal) -> None:
        handler = getattr(self._primary, "on_trade_tick", None)
        if callable(handler):
            handler(is_buy=is_buy, volume=volume, dt_seconds=dt_seconds)

    def sync_holding(self, holding: SignalSide) -> None:
        """Keep the internal position state in sync with the broker/account."""
        self._position = None if holding is SignalSide.FLAT else holding
        handler = getattr(self._primary, "sync_holding", None)
        if callable(handler):
            handler(holding)

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
        context = (
            self._context_extractor.update(bar) if self._context_extractor is not None else None
        )
        primary = self._primary.on_bar(bar)
        if self._position is not None:
            return self._maybe_exit(bar, primary, features, context)
        if primary is None or primary.side is SignalSide.FLAT:
            return None
        return self._maybe_enter(primary, features, context)

    def _maybe_exit(
        self,
        bar: OhlcvBar,
        primary: Signal | None,
        features: tuple[Decimal, ...] | None,
        context: tuple[Decimal, ...] | None,
    ) -> Signal | None:
        if primary is None:
            return None
        if primary.side is SignalSide.FLAT:
            self._position = None
            return primary
        if primary.side is self._position:
            return None
        self._position = None
        accepted = self._accept_entry(primary, features, context)
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
        context: tuple[Decimal, ...] | None,
    ) -> Signal | None:
        accepted = self._accept_entry(primary, features, context)
        if accepted is None:
            return None
        self._position = accepted.side
        return accepted

    def _accept_entry(
        self,
        primary: Signal,
        features: tuple[Decimal, ...] | None,
        context: tuple[Decimal, ...] | None,
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
        vector = encode_meta_features(features, primary.side, context=context)
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
