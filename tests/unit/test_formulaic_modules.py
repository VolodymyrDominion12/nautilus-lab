from datetime import UTC, datetime, timedelta
from decimal import Decimal

from nautilus_lab.application.train_formulaic import build_formulaic_dataset
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.formulaic_alphas import MIN_HISTORY, FormulaicAlphaEngine
from nautilus_lab.domain.formulaic_lgbm_strategy import FormulaicLgbmStrategy
from nautilus_lab.domain.ml_classifier import (
    DIRECTION_CLASS_INDEX,
    DIRECTION_CLASSES,
    DirectionProbabilities,
    probabilities_from_ordered_scores,
)
from nautilus_lab.domain.signals import SignalSide


def _bars(count: int = 60) -> list[OhlcvBar]:
    origin = datetime(2024, 1, 1, tzinfo=UTC)
    bars: list[OhlcvBar] = []
    price = Decimal("100")
    for index in range(count):
        price += Decimal("0.5") if index % 3 else Decimal("-0.2")
        bars.append(
            OhlcvBar(
                instrument_id="ETH/USDT.SIM",
                ts_utc=origin + timedelta(hours=index),
                open=price,
                high=price + Decimal("1"),
                low=price - Decimal("1"),
                close=price,
                volume=Decimal("100") + Decimal(index),
            )
        )
    return bars


def test_formulaic_engine_produces_fixed_width_features() -> None:
    engine = FormulaicAlphaEngine(history=MIN_HISTORY)
    features = None
    for bar in _bars(40):
        features = engine.update(bar)
    assert features is not None
    assert len(features) == 12


class _AlwaysUpClassifier:
    def predict(self, features: tuple[Decimal, ...]) -> DirectionProbabilities:
        return DirectionProbabilities(
            up=Decimal("0.8"),
            down=Decimal("0.1"),
            flat=Decimal("0.1"),
        )


def test_formulaic_strategy_emits_signal_after_warmup() -> None:
    robot = FormulaicLgbmStrategy(
        instrument_id="ETH/USDT.SIM",
        classifier=_AlwaysUpClassifier(),
        threshold=Decimal("0.55"),
    )
    signals = [robot.on_bar(bar) for bar in _bars(50)]
    assert any(signal is not None and signal.side is SignalSide.BUY for signal in signals)


def test_build_formulaic_dataset_records_label_span() -> None:
    dataset = build_formulaic_dataset(_bars(80), horizon=3)
    assert len(dataset.features) == len(dataset.labels)
    assert set(dataset.labels).issubset({"up", "down", "flat"})
    assert dataset.sample_times
    assert dataset.label_ends == tuple(time + 4 for time in dataset.sample_times)
    assert dataset.sample_times[0] >= MIN_HISTORY


def test_direction_scores_map_down_flat_up() -> None:
    """Training writes down=0, flat=1, up=2; unpacking (up, down, flat) would swap sides."""
    assert DIRECTION_CLASSES == ("down", "flat", "up")
    assert DIRECTION_CLASS_INDEX == {"down": 0, "flat": 1, "up": 2}
    probs = probabilities_from_ordered_scores((Decimal("0.7"), Decimal("0.2"), Decimal("0.1")))
    assert probs.down == Decimal("0.7")
    assert probs.flat == Decimal("0.2")
    assert probs.up == Decimal("0.1")


class _AlternatingClassifier:
    def __init__(self) -> None:
        self.call_count = 0

    def predict(self, features: tuple[Decimal, ...]) -> DirectionProbabilities:
        self.call_count += 1
        # First 2 calls: strong UP. Next calls: strong DOWN.
        if self.call_count <= 2:
            return DirectionProbabilities(
                up=Decimal("0.8"), down=Decimal("0.1"), flat=Decimal("0.1")
            )
        return DirectionProbabilities(up=Decimal("0.1"), down=Decimal("0.8"), flat=Decimal("0.1"))


def test_formulaic_strategy_min_hold_bars_prevents_early_exit() -> None:
    clf = _AlternatingClassifier()
    robot = FormulaicLgbmStrategy(
        instrument_id="ETH/USDT.SIM",
        classifier=clf,
        threshold=Decimal("0.55"),
        min_hold_bars=3,
    )
    bars = _bars(40)
    signals = []
    for bar in bars:
        sig = robot.on_bar(bar)
        if sig is not None:
            signals.append(sig)

    # 1st post-warmup bar: BUY (call 1)
    # 2nd bar: held 1, call 2 (still UP, no signal)
    # 3rd bar: held 2, call 3 (DOWN > UP, but held 2 < 3 -> blocked by min_hold_bars)
    # 4th bar: held 3, call 4 (held 3 >= 3 -> exits to FLAT)
    # 5th bar: now flat, call 5 (DOWN > threshold -> enters SELL)
    assert len(signals) == 3
    assert signals[0].side == SignalSide.BUY
    assert signals[1].side == SignalSide.FLAT
    assert signals[2].side == SignalSide.SELL
