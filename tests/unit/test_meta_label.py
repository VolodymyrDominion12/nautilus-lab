from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from nautilus_lab.application.train_meta_label import build_meta_label_dataset
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.errors import ModelArtifactMissingError
from nautilus_lab.domain.meta_label_strategy import MetaLabelStrategy, encode_meta_features
from nautilus_lab.domain.signals import Signal, SignalSide
from nautilus_lab.infrastructure.lightgbm_classifier import require_model_path

ORIGIN = datetime(2024, 1, 1, tzinfo=UTC)


def _bars(count: int, *, step: Decimal = Decimal("1")) -> list[OhlcvBar]:
    bars: list[OhlcvBar] = []
    price = Decimal("100")
    for index in range(count):
        price += step
        bars.append(
            OhlcvBar(
                instrument_id="ETH/USDT.SIM",
                ts_utc=ORIGIN + timedelta(hours=index),
                open=price,
                high=price + Decimal("1"),
                low=price - Decimal("1"),
                close=price,
                volume=Decimal("10"),
            )
        )
    return bars


class _BuyThenFlat:
    def __init__(self, buy_at: int) -> None:
        self._buy_at = buy_at
        self._seen = 0

    def on_bar(self, bar: OhlcvBar) -> Signal | None:
        self._seen += 1
        if self._seen == self._buy_at:
            return Signal(
                instrument_id=bar.instrument_id,
                side=SignalSide.BUY,
                bar_ts_utc=bar.ts_utc,
                reason="primary buy",
            )
        if self._seen == self._buy_at + 5:
            return Signal(
                instrument_id=bar.instrument_id,
                side=SignalSide.FLAT,
                bar_ts_utc=bar.ts_utc,
                reason="primary exit",
            )
        return None


class _FixedSuccess:
    def __init__(self, probability: Decimal) -> None:
        self.probability = probability

    def predict_success(self, features: tuple[Decimal, ...]) -> Decimal:
        assert len(features) == 13
        return self.probability


def test_encode_meta_features_signs_the_side() -> None:
    formulaic = tuple(Decimal("0") for _ in range(12))
    buy = encode_meta_features(formulaic, SignalSide.BUY)
    sell = encode_meta_features(formulaic, SignalSide.SELL)
    assert buy[-1] == Decimal("1")
    assert sell[-1] == Decimal("-1")
    with pytest.raises(ValueError, match="entry side"):
        encode_meta_features(formulaic, SignalSide.FLAT)


def test_meta_label_rejects_an_entry_below_threshold() -> None:
    robot = MetaLabelStrategy(
        instrument_id="ETH/USDT.SIM",
        primary=_BuyThenFlat(buy_at=40),
        classifier=_FixedSuccess(Decimal("0.40")),
        threshold=Decimal("0.55"),
    )
    signals = [robot.on_bar(bar) for bar in _bars(50)]
    entries = [item for item in signals if item is not None and item.side is SignalSide.BUY]
    assert entries == []


def test_meta_label_takes_an_entry_at_or_above_threshold() -> None:
    robot = MetaLabelStrategy(
        instrument_id="ETH/USDT.SIM",
        primary=_BuyThenFlat(buy_at=40),
        classifier=_FixedSuccess(Decimal("0.80")),
        threshold=Decimal("0.55"),
    )
    signals = [robot.on_bar(bar) for bar in _bars(50)]
    entries = [item for item in signals if item is not None and item.side is SignalSide.BUY]
    exits = [item for item in signals if item is not None and item.side is SignalSide.FLAT]
    assert len(entries) == 1
    assert "meta-label" in entries[0].reason
    assert len(exits) == 1


def test_meta_label_always_passes_a_primary_exit() -> None:
    robot = MetaLabelStrategy(
        instrument_id="ETH/USDT.SIM",
        primary=_BuyThenFlat(buy_at=40),
        classifier=_FixedSuccess(Decimal("0.90")),
        threshold=Decimal("0.55"),
    )
    bars = _bars(50)
    signals = [robot.on_bar(bar) for bar in bars]
    assert any(item is not None and item.side is SignalSide.FLAT for item in signals)


def test_build_meta_label_dataset_labels_primary_entries() -> None:
    dataset = build_meta_label_dataset(
        _bars(80, step=Decimal("2")),
        instrument_id="ETH/USDT.SIM",
        primary=_BuyThenFlat(buy_at=40),
    )
    assert dataset.features
    assert len(dataset.features) == len(dataset.labels) == len(dataset.outcomes)
    assert len(dataset.features[0]) == 13
    assert set(dataset.labels) <= {0, 1}
    assert dataset.sample_times == (39,)
    assert dataset.label_ends == (39 + dataset.outcomes[0].bars_held + 1,)


def test_require_model_path_fails_closed_without_a_file(tmp_path: Path) -> None:
    with pytest.raises(ModelArtifactMissingError, match="meta_label"):
        require_model_path(None, robot="meta_label")
    with pytest.raises(ModelArtifactMissingError, match="meta_label"):
        require_model_path("  ", robot="meta_label")
    missing = tmp_path / "no-such-model.txt"
    with pytest.raises(ModelArtifactMissingError, match="not found"):
        require_model_path(str(missing), robot="meta_label")
