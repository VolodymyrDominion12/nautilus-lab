from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.persistence.catalog.singleton import clear_singleton_instances

from nautilus_lab.application.dtos import BacktestRequest
from nautilus_lab.application.run_research_backtest import RunResearchBacktest
from nautilus_lab.domain.bars import BarOrigin, OhlcvBar
from nautilus_lab.domain.errors import CatalogEmptyError
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.infrastructure.nautilus.backtest_runner import NautilusResearchBacktest
from nautilus_lab.infrastructure.nautilus.bar_feed import ResearchBarFeed
from nautilus_lab.infrastructure.nautilus.parquet_catalog import NautilusParquetCatalog
from nautilus_lab.infrastructure.nautilus.synthetic_bars import synthetic_regime_ohlcv


def _limits() -> RiskLimits:
    return RiskLimits(
        risk_per_trade=Decimal("0.005"),
        stop_pct=Decimal("0.01"),
        max_daily_loss=Decimal("0.02"),
        max_drawdown=Decimal("0.06"),
    )


@pytest.mark.integration
def test_research_backtest_runs_locally_without_network() -> None:
    class UnusedCatalog:
        def write(
            self,
            bars: Sequence[OhlcvBar],
            *,
            bar_type: str,
            instrument_id: str = "",
        ) -> int:
            raise AssertionError("synthetic path must not touch catalog")

        def load(
            self,
            *,
            bar_type: str,
            start: datetime | None = None,
            end: datetime | None = None,
        ) -> list[OhlcvBar]:
            raise AssertionError("synthetic path must not load catalog")

        def load_multi(self, request: BacktestRequest) -> dict[str, list[OhlcvBar]]:
            raise AssertionError("synthetic path must not load catalog")

    use_case = RunResearchBacktest(NautilusResearchBacktest(), ResearchBarFeed(UnusedCatalog()))
    report = use_case.execute(
        BacktestRequest(
            mode=TradingMode.RESEARCH,
            instrument_id="ETH/USDT.SIM",
            bar_count=900,
            starting_equity=Decimal("100000"),
            risk=_limits(),
            robot=RobotName.REGIME,
            seed=7,
            source=BarOrigin.SYNTHETIC,
        ),
    )

    assert report.fills >= 0
    assert report.positions >= 0
    assert "fees" in report.notes
    assert "regime" in report.notes


@pytest.mark.integration
def test_parquet_catalog_roundtrip_and_backtest(tmp_path: Path) -> None:
    clear_singleton_instances(ParquetDataCatalog)
    bar_type = "ETH/USDT.SIM-1-HOUR-LAST-EXTERNAL"
    bars = synthetic_regime_ohlcv(instrument_id="ETH/USDT.SIM", count=400, seed=11)
    store = NautilusParquetCatalog(tmp_path)
    written = store.write(bars, bar_type=bar_type)
    loaded = store.load(bar_type=bar_type)

    assert written == 400
    assert len(loaded) == 400
    assert loaded[0].close == bars[0].close
    assert loaded[-1].ts_utc == bars[-1].ts_utc

    report = RunResearchBacktest(NautilusResearchBacktest(), ResearchBarFeed(store)).execute(
        BacktestRequest(
            mode=TradingMode.RESEARCH,
            instrument_id="ETH/USDT.SIM",
            bar_count=400,
            starting_equity=Decimal("100000"),
            risk=_limits(),
            robot=RobotName.REGIME,
            seed=11,
            source=BarOrigin.CATALOG,
            bar_type=bar_type,
        ),
    )
    assert report.fills >= 0
    assert "catalog" in report.notes


@pytest.mark.integration
def test_pairs_synthetic_backtest_runs() -> None:
    class UnusedCatalog:
        def write(
            self,
            bars: Sequence[OhlcvBar],
            *,
            bar_type: str,
            instrument_id: str = "",
        ) -> int:
            raise AssertionError("synthetic path must not touch catalog")

        def load(self, **kwargs: object) -> list[OhlcvBar]:
            raise AssertionError("synthetic path must not load catalog")

        def load_multi(self, request: BacktestRequest) -> dict[str, list[OhlcvBar]]:
            raise AssertionError("synthetic path must not load catalog")

    use_case = RunResearchBacktest(NautilusResearchBacktest(), ResearchBarFeed(UnusedCatalog()))
    report = use_case.execute(
        BacktestRequest(
            mode=TradingMode.RESEARCH,
            instrument_id="ETH/USDT.SIM",
            bar_count=300,
            starting_equity=Decimal("100000"),
            risk=_limits(),
            robot=RobotName.PAIRS,
            seed=5,
            source=BarOrigin.SYNTHETIC,
        ),
    )
    assert report.fills >= 0
    assert "pairs" in report.notes


@pytest.mark.integration
def test_empty_catalog_load_fails_closed(tmp_path: Path) -> None:
    clear_singleton_instances(ParquetDataCatalog)
    store = NautilusParquetCatalog(tmp_path)
    with pytest.raises(CatalogEmptyError, match="lab ingest"):
        store.load(bar_type="ETH/USDT.SIM-1-HOUR-LAST-EXTERNAL")
