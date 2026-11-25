from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from nautilus_lab.application.dtos import BacktestRequest
from nautilus_lab.application.train_meta_label import build_meta_label_dataset
from nautilus_lab.domain.bars import BarOrigin, OhlcvBar, validate_bar
from nautilus_lab.domain.errors import ModelArtifactMissingError
from nautilus_lab.domain.meta_label_strategy import (
    META_CONTEXT_FEATURE_NAMES,
    META_FEATURE_NAMES,
    META_FEATURE_NAMES_WITH_CONTEXT,
    MetaContextExtractor,
    MetaLabelStrategy,
    encode_meta_features,
)
from nautilus_lab.domain.premium_index import PremiumIndexBar
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.signals import Signal, SignalSide
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.infrastructure.lightgbm_classifier import require_model_path
from nautilus_lab.infrastructure.nautilus.bar_feed import ResearchBarFeed
from nautilus_lab.infrastructure.premium_index_catalog import ParquetPremiumIndexCatalog
from nautilus_lab.infrastructure.settings import Settings
from nautilus_lab.interfaces.composition import research_request

ORIGIN = datetime(2024, 1, 1, tzinfo=UTC)


def _bars(
    count: int,
    *,
    step: Decimal = Decimal("1"),
    start: datetime = ORIGIN,
    instrument_id: str = "ETH/USDT.SIM",
) -> list[OhlcvBar]:
    bars: list[OhlcvBar] = []
    price = Decimal("100")
    for index in range(count):
        price += step
        bars.append(
            OhlcvBar(
                instrument_id=instrument_id,
                ts_utc=start + timedelta(hours=index),
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
    def __init__(self, probability: Decimal, *, expected_len: int = 13) -> None:
        self.probability = probability
        self.expected_len = expected_len
        self.seen_vectors: list[tuple[Decimal, ...]] = []

    def predict_success(self, features: tuple[Decimal, ...]) -> Decimal:
        assert len(features) == self.expected_len
        self.seen_vectors.append(features)
        return self.probability


class _DimensionAwareClassifier(_FixedSuccess):
    def __init__(self, probability: Decimal, *, num_features: int) -> None:
        super().__init__(probability, expected_len=num_features)
        self.num_features = num_features


class _FakeBarCatalog:
    def __init__(self, bars: list[OhlcvBar]) -> None:
        self._bars = bars

    def write(self, bars: object, *, bar_type: str, instrument_id: str) -> int:
        return 0

    def load(
        self,
        *,
        bar_type: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[OhlcvBar]:
        return list(self._bars)


def test_encode_meta_features_signs_the_side() -> None:
    formulaic = tuple(Decimal("0") for _ in range(12))
    buy = encode_meta_features(formulaic, SignalSide.BUY)
    sell = encode_meta_features(formulaic, SignalSide.SELL)
    assert buy[-1] == Decimal("1")
    assert sell[-1] == Decimal("-1")
    assert len(META_FEATURE_NAMES) == 13
    assert len(META_CONTEXT_FEATURE_NAMES) == 8
    assert len(META_FEATURE_NAMES_WITH_CONTEXT) == 21
    with pytest.raises(ValueError, match="entry side"):
        encode_meta_features(formulaic, SignalSide.FLAT)

    ctx = tuple(Decimal(i) for i in range(8))
    with_ctx = encode_meta_features(formulaic, SignalSide.BUY, context=ctx)
    assert len(with_ctx) == 21
    assert with_ctx[12] == Decimal("1")
    assert with_ctx[13:] == ctx

    with pytest.raises(ValueError, match="8 features"):
        encode_meta_features(formulaic, SignalSide.BUY, context=(Decimal("1"),))


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
    assert dataset.feature_names == META_FEATURE_NAMES
    assert set(dataset.labels) <= {0, 1}
    assert dataset.sample_times == (39,)
    assert dataset.label_ends == (39 + dataset.outcomes[0].bars_held + 1,)


def test_meta_context_extractor_handles_unknown_negative_and_sessions() -> None:
    extractor = MetaContextExtractor(zscore_window=5)

    def _bar(ts: datetime, premium: Decimal | None) -> OhlcvBar:
        bar = OhlcvBar(
            instrument_id="PAXGUSDT-PERP.SIM",
            ts_utc=ts,
            open=Decimal("2600"),
            high=Decimal("2605"),
            low=Decimal("2595"),
            close=Decimal("2602"),
            volume=Decimal("100"),
            premium_index_close=premium,
        )
        validate_bar(bar, now=ts)
        return bar

    # 1. Unknown premium_index (None) during Asia session (2026-01-05 03:00 UTC)
    asia_unknown = extractor.update(_bar(datetime(2026, 1, 5, 3, 0, tzinfo=UTC), None))
    assert asia_unknown == (
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        Decimal("1"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
    )

    # 2. First known negative basis during London session (09:00 London, 04:00 NY)
    london_first = extractor.update(
        _bar(datetime(2026, 1, 5, 9, 0, tzinfo=UTC), Decimal("-0.0010"))
    )
    assert london_first[:4] == (Decimal("-0.0010"), Decimal("0"), Decimal("0"), Decimal("1"))
    assert london_first[4:] == (Decimal("0"), Decimal("1"), Decimal("0"), Decimal("0"))

    # 3. Second known positive basis during London-NY overlap (14:00 London, 09:00 NY)
    overlap_second = extractor.update(
        _bar(datetime(2026, 1, 5, 14, 0, tzinfo=UTC), Decimal("0.0010"))
    )
    assert overlap_second[0] == Decimal("0.0010")
    assert overlap_second[1] == Decimal("1")  # z-score of +0.001 over {-0.001, +0.001} is +1
    assert overlap_second[2] == Decimal("0.0020")  # delta
    assert overlap_second[3] == Decimal("1")  # has_premium_index
    assert overlap_second[4:] == (Decimal("0"), Decimal("0"), Decimal("1"), Decimal("0"))

    # 4. NY afternoon (18:00 UTC = 18:00 London, 13:00 NY) with unknown basis again
    ny_afternoon = extractor.update(_bar(datetime(2026, 1, 5, 18, 0, tzinfo=UTC), None))
    assert ny_afternoon[:4] == (Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))
    assert ny_afternoon[4:] == (Decimal("0"), Decimal("0"), Decimal("0"), Decimal("1"))

    # 5. True zero basis is distinguished from unknown via has_premium_index=1
    weekend_zero = extractor.update(_bar(datetime(2026, 1, 10, 12, 0, tzinfo=UTC), Decimal("0")))
    assert weekend_zero[0] == Decimal("0")
    assert weekend_zero[3] == Decimal("1")
    assert weekend_zero[4:] == (Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))


def test_meta_label_strategy_with_context_and_dimension_guard() -> None:
    classifier = _DimensionAwareClassifier(Decimal("0.80"), num_features=21)
    robot = MetaLabelStrategy(
        instrument_id="PAXGUSDT-PERP.SIM",
        primary=_BuyThenFlat(buy_at=40),
        classifier=classifier,
        threshold=Decimal("0.55"),
        include_context=True,
    )
    bars = [
        OhlcvBar(
            instrument_id=bar.instrument_id,
            ts_utc=bar.ts_utc,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            premium_index_close=Decimal("0.0005") + Decimal(idx) * Decimal("0.00001"),
        )
        for idx, bar in enumerate(_bars(50, instrument_id="PAXGUSDT-PERP.SIM"))
    ]
    signals = [robot.on_bar(bar) for bar in bars]
    entries = [item for item in signals if item is not None and item.side is SignalSide.BUY]
    assert len(entries) == 1
    assert len(classifier.seen_vectors) == 1
    assert len(classifier.seen_vectors[0]) == 21
    assert classifier.seen_vectors[0][13] == bars[39].premium_index_close
    assert classifier.seen_vectors[0][16] == Decimal("1")  # has_premium_index

    with pytest.raises(ValueError, match="expects 13 features"):
        MetaLabelStrategy(
            instrument_id="PAXGUSDT-PERP.SIM",
            primary=_BuyThenFlat(buy_at=40),
            classifier=_DimensionAwareClassifier(Decimal("0.80"), num_features=13),
            include_context=True,
        )

    with pytest.raises(ValueError, match="expects 21 features"):
        MetaLabelStrategy(
            instrument_id="PAXGUSDT-PERP.SIM",
            primary=_BuyThenFlat(buy_at=40),
            classifier=_DimensionAwareClassifier(Decimal("0.80"), num_features=21),
            include_context=False,
        )


def test_build_meta_label_dataset_with_context_produces_21_features() -> None:
    bars = [
        OhlcvBar(
            instrument_id=bar.instrument_id,
            ts_utc=bar.ts_utc,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            premium_index_close=Decimal("-0.0003") if idx % 2 == 0 else Decimal("0.0004"),
        )
        for idx, bar in enumerate(_bars(80, step=Decimal("2")))
    ]
    dataset = build_meta_label_dataset(
        bars,
        instrument_id="ETH/USDT.SIM",
        primary=_BuyThenFlat(buy_at=40),
        include_context=True,
    )
    assert dataset.feature_names == META_FEATURE_NAMES_WITH_CONTEXT
    assert len(dataset.features[0]) == 21
    assert dataset.features[0][16] == Decimal("1")


def test_bar_feed_attaches_premium_index_by_timestamp(tmp_path: Path) -> None:
    bars = _bars(3, instrument_id="PAXGUSDT-PERP.SIM")
    prem_store = ParquetPremiumIndexCatalog(tmp_path)
    prem_store.write(
        [
            PremiumIndexBar(
                symbol="PAXGUSDT",
                interval="1h",
                ts_utc=bars[0].ts_utc,
                open=Decimal("-0.0002"),
                high=Decimal("-0.0001"),
                low=Decimal("-0.0004"),
                close=Decimal("-0.0003"),
            ),
            PremiumIndexBar(
                symbol="PAXGUSDT",
                interval="1h",
                ts_utc=bars[2].ts_utc,
                open=Decimal("0.0001"),
                high=Decimal("0.0005"),
                low=Decimal("0.0000"),
                close=Decimal("0.0004"),
            ),
        ],
        symbol="PAXGUSDT-PERP",
        interval="1h",
    )
    feed = ResearchBarFeed(_FakeBarCatalog(bars), premium_index=prem_store)
    req = BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="PAXGUSDT-PERP.SIM",
        bar_type="PAXGUSDT-PERP.SIM-1-HOUR-LAST-EXTERNAL",
        bar_count=3,
        starting_equity=Decimal("100000"),
        risk=RiskLimits(
            risk_per_trade=Decimal("0.005"),
            stop_pct=Decimal("0.015"),
            max_daily_loss=Decimal("0.04"),
            max_drawdown=Decimal("0.12"),
        ),
        robot=RobotName.META_LABEL,
        source=BarOrigin.CATALOG,
    )
    loaded = feed.load(req)
    assert loaded[0].premium_index_close == Decimal("-0.0003")
    assert loaded[1].premium_index_close is None
    assert loaded[2].premium_index_close == Decimal("0.0004")


def test_settings_forwards_meta_label_context_features_to_request() -> None:
    default_cfg = Settings(_env_file=None)  # type: ignore[call-arg]
    assert default_cfg.meta_label_context_features is False
    assert research_request(default_cfg, bar_count=200).meta_label_context_features is False

    enabled_cfg = Settings(_env_file=None, meta_label_context_features=True)  # type: ignore[call-arg]
    assert research_request(enabled_cfg, bar_count=200).meta_label_context_features is True


def test_require_model_path_fails_closed_without_a_file(tmp_path: Path) -> None:
    with pytest.raises(ModelArtifactMissingError, match="meta_label"):
        require_model_path(None, robot="meta_label")
    with pytest.raises(ModelArtifactMissingError, match="meta_label"):
        require_model_path("  ", robot="meta_label")
    missing = tmp_path / "no-such-model.txt"
    with pytest.raises(ModelArtifactMissingError, match="not found"):
        require_model_path(str(missing), robot="meta_label")
