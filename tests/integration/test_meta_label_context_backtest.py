"""Integration test: `meta_label` trained and backtested with 21 context features."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.persistence.catalog.singleton import clear_singleton_instances

from nautilus_lab.application.dtos import BacktestRequest
from nautilus_lab.application.run_research_backtest import RunResearchBacktest
from nautilus_lab.application.train_meta_label import (
    build_meta_label_dataset,
    train_meta_label_lightgbm,
)
from nautilus_lab.domain.bars import BarOrigin, OhlcvBar
from nautilus_lab.domain.meta_label_strategy import META_FEATURE_NAMES_WITH_CONTEXT
from nautilus_lab.domain.premium_index import PremiumIndexBar
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.domain.triple_barrier import TripleBarrierConfig
from nautilus_lab.infrastructure.lightgbm_classifier import LightGBMSuccessClassifier
from nautilus_lab.infrastructure.nautilus.backtest_runner import NautilusResearchBacktest
from nautilus_lab.infrastructure.nautilus.bar_feed import ResearchBarFeed, attach_premium_index
from nautilus_lab.infrastructure.nautilus.parquet_catalog import NautilusParquetCatalog
from nautilus_lab.infrastructure.premium_index_catalog import ParquetPremiumIndexCatalog


def _paxg_wave_with_premium(
    count: int = 480,
) -> tuple[list[OhlcvBar], list[PremiumIndexBar]]:
    start = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    bars: list[OhlcvBar] = []
    prem_bars: list[PremiumIndexBar] = []
    prev_close = Decimal("2650.00")
    for idx in range(count):
        ts = start + timedelta(hours=idx)
        # Multi-day sinusoidal oscillation triggers both trend breakouts and mean-reversion swings
        delta = Decimal(str(round(10.0 * math.sin(idx / 12.0), 2)))
        close = (prev_close + delta).quantize(Decimal("0.01"))
        high = (max(prev_close, close) + Decimal("3.50")).quantize(Decimal("0.01"))
        low = (min(prev_close, close) - Decimal("3.50")).quantize(Decimal("0.01"))
        bars.append(
            OhlcvBar(
                instrument_id="PAXGUSDT-PERP.SIM",
                ts_utc=ts,
                open=prev_close,
                high=high,
                low=low,
                close=close,
                volume=Decimal("400"),
            )
        )
        basis = Decimal(str(round(0.0008 * math.cos(idx / 8.0), 6)))
        prem_bars.append(
            PremiumIndexBar(
                symbol="PAXGUSDT",
                interval="1h",
                ts_utc=ts,
                open=basis,
                high=basis + Decimal("0.0001"),
                low=basis - Decimal("0.0001"),
                close=basis,
            )
        )
        prev_close = close
    return bars, prem_bars


@pytest.mark.integration
def test_meta_label_context_features_train_and_backtest_deterministically(tmp_path: Path) -> None:
    clear_singleton_instances(ParquetDataCatalog)
    bar_type = "PAXGUSDT-PERP.SIM-1-HOUR-LAST-EXTERNAL"
    bars, prem_bars = _paxg_wave_with_premium(480)

    bar_store = NautilusParquetCatalog(tmp_path)
    bar_store.write(bars, bar_type=bar_type)
    prem_store = ParquetPremiumIndexCatalog(tmp_path)
    prem_store.write(prem_bars, symbol="PAXGUSDT-PERP", interval="1h")

    enriched = attach_premium_index(bars, prem_bars)
    dataset = build_meta_label_dataset(
        enriched,
        instrument_id="PAXGUSDT-PERP.SIM",
        barrier=TripleBarrierConfig(horizon=6),
        include_context=True,
    )
    assert dataset.feature_names == META_FEATURE_NAMES_WITH_CONTEXT
    assert len(dataset.features) >= 8
    assert len(dataset.features[0]) == 21

    model_path = tmp_path / "models" / "meta_label_ctx.txt"
    train_report = train_meta_label_lightgbm(
        dataset,
        model_path,
        n_splits=2,
        embargo=2,
        threshold=Decimal("0.30"),
    )
    assert train_report.rows == len(dataset.features)
    assert LightGBMSuccessClassifier(str(model_path)).num_features == 21

    feed = ResearchBarFeed(bar_store, premium_index=prem_store)
    use_case = RunResearchBacktest(NautilusResearchBacktest(), feed)

    # Mismatch guard: 21-feature model must fail closed when META_LABEL_CONTEXT_FEATURES=false.
    mismatched_req = BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="PAXGUSDT-PERP.SIM",
        bar_type=bar_type,
        bar_count=len(bars),
        starting_equity=Decimal("100000"),
        risk=RiskLimits(
            risk_per_trade=Decimal("0.005"),
            stop_pct=Decimal("0.015"),
            max_daily_loss=Decimal("0.04"),
            max_drawdown=Decimal("0.12"),
        ),
        robot=RobotName.META_LABEL,
        source=BarOrigin.CATALOG,
        meta_label_model_path=str(model_path),
        meta_label_threshold=Decimal("0.30"),
        meta_label_context_features=False,
    )
    with pytest.raises(ValueError, match="expects 21 features"):
        use_case.execute(mismatched_req)

    valid_req = BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="PAXGUSDT-PERP.SIM",
        bar_type=bar_type,
        bar_count=len(bars),
        starting_equity=Decimal("100000"),
        risk=RiskLimits(
            risk_per_trade=Decimal("0.005"),
            stop_pct=Decimal("0.015"),
            max_daily_loss=Decimal("0.04"),
            max_drawdown=Decimal("0.12"),
        ),
        robot=RobotName.META_LABEL,
        source=BarOrigin.CATALOG,
        meta_label_model_path=str(model_path),
        meta_label_threshold=Decimal("0.20"),
        meta_label_context_features=True,
    )
    first = use_case.execute(valid_req)
    second = use_case.execute(valid_req)

    assert "meta_label" in first.notes
    assert first.ending_balance is not None
    assert first.ending_balance == second.ending_balance
    assert first.fills == second.fills
