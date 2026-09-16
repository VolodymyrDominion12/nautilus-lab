from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.model.data import BarType
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
from nautilus_lab.infrastructure.nautilus.bar_convert import to_engine_bars
from nautilus_lab.infrastructure.nautilus.bar_feed import ResearchBarFeed
from nautilus_lab.infrastructure.nautilus.instrument import resolve_instrument
from nautilus_lab.infrastructure.nautilus.parquet_catalog import NautilusParquetCatalog
from nautilus_lab.infrastructure.nautilus.synthetic_bars import synthetic_regime_ohlcv


def _limits() -> RiskLimits:
    return RiskLimits(
        risk_per_trade=Decimal("0.005"),
        stop_pct=Decimal("0.01"),
        max_daily_loss=Decimal("0.02"),
        max_drawdown=Decimal("0.06"),
    )


class _UnusedCatalog:
    """A catalog that fails loudly: a synthetic run must never touch it."""

    def write(
        self,
        bars: Sequence[OhlcvBar],
        *,
        bar_type: str,
        instrument_id: str = "",
    ) -> int:
        raise AssertionError("synthetic path must not touch catalog")

    def load(self, *args: object, **kwargs: object) -> list[OhlcvBar]:
        raise AssertionError("synthetic path must not load catalog")

    def load_multi(self, request: BacktestRequest) -> dict[str, list[OhlcvBar]]:
        raise AssertionError("synthetic path must not load catalog")


@pytest.mark.integration
def test_research_backtest_runs_locally_without_network() -> None:
    use_case = RunResearchBacktest(NautilusResearchBacktest(), ResearchBarFeed(_UnusedCatalog()))
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
def test_engine_money_after_the_run_is_measured() -> None:
    """Fees, two-sided notional and breakeven must be real numbers after a run.

    `specs/components/backtest-engine.yaml` lists "fee accounting in P&L" as an
    invariant without a test: the existing assertions only look at the `notes` string,
    which would survive the fee model being removed. This closes that gap for the
    numbers a reader actually uses, and pins the breakeven wiring end-to-end.
    """
    use_case = RunResearchBacktest(NautilusResearchBacktest(), ResearchBarFeed(_UnusedCatalog()))
    report = use_case.execute(
        BacktestRequest(
            mode=TradingMode.RESEARCH,
            instrument_id="ETH/USDT.SIM",
            bar_count=900,
            starting_equity=Decimal("100000"),
            risk=_limits(),
            robot=RobotName.EMA,
            seed=3,
            source=BarOrigin.SYNTHETIC,
        ),
    )

    metrics = report.metrics
    assert metrics is not None
    assert report.fills > 0, "an EMA robot on 900 synthetic bars must trade at all"
    assert report.ending_balance is not None
    assert metrics.fees_paid > 0, "fills without fees mean the fee model is gone"
    assert metrics.traded_notional > 0, "two-sided notional must come from the fills report"
    # `turnover` counts entry notional only, so it can never exceed the two-sided total.
    assert metrics.turnover <= metrics.traded_notional
    net_pnl = report.ending_balance - Decimal("100000")
    assert metrics.breakeven_cost == (net_pnl + metrics.fees_paid) / metrics.traded_notional
    assert metrics.paid_cost_rate == metrics.fees_paid / metrics.traded_notional


@pytest.mark.integration
def test_pairs_synthetic_backtest_runs() -> None:
    use_case = RunResearchBacktest(NautilusResearchBacktest(), ResearchBarFeed(_UnusedCatalog()))
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
def test_reingesting_an_overlapping_window_replaces_instead_of_duplicating(
    tmp_path: Path,
) -> None:
    """A second ingest over an overlapping window must not break the catalog.

    `write_data` runs with `skip_disjoint_check=True`, so appending produced two
    files covering the same timestamps. `bars()` merges every matching file, so the
    next load raised "bar timestamps must be strictly increasing" — a message that
    says nothing about the real cause.
    """
    clear_singleton_instances(ParquetDataCatalog)
    bar_type = "ETH/USDT.SIM-1-HOUR-LAST-EXTERNAL"
    bars = synthetic_regime_ohlcv(instrument_id="ETH/USDT.SIM", count=400, seed=11)
    store = NautilusParquetCatalog(tmp_path)
    store.write(bars, bar_type=bar_type)

    clear_singleton_instances(ParquetDataCatalog)
    store.write(list(bars[100:]), bar_type=bar_type)

    clear_singleton_instances(ParquetDataCatalog)
    loaded = store.load(bar_type=bar_type)
    assert [bar.ts_utc for bar in loaded] == [bar.ts_utc for bar in bars]


@pytest.mark.integration
def test_load_deduplicates_a_catalog_with_overlapping_files(tmp_path: Path) -> None:
    """Catalogs written before the fix must still be readable."""
    clear_singleton_instances(ParquetDataCatalog)
    bar_type = "ETH/USDT.SIM-1-HOUR-LAST-EXTERNAL"
    bars = synthetic_regime_ohlcv(instrument_id="ETH/USDT.SIM", count=400, seed=11)
    store = NautilusParquetCatalog(tmp_path)
    store.write(bars, bar_type=bar_type)

    clear_singleton_instances(ParquetDataCatalog)
    ParquetDataCatalog(str(tmp_path)).write_data(
        to_engine_bars(
            list(bars[100:]),
            bar_type=BarType.from_str(bar_type),
            instrument=resolve_instrument("ETH/USDT.SIM"),
        ),
        skip_disjoint_check=True,
    )

    clear_singleton_instances(ParquetDataCatalog)
    loaded = store.load(bar_type=bar_type)
    timestamps = [bar.ts_utc for bar in loaded]
    assert timestamps == sorted({bar.ts_utc for bar in bars})
    assert len(timestamps) == len(set(timestamps))


@pytest.mark.integration
def test_empty_catalog_load_fails_closed(tmp_path: Path) -> None:
    clear_singleton_instances(ParquetDataCatalog)
    store = NautilusParquetCatalog(tmp_path)
    with pytest.raises(CatalogEmptyError, match="lab ingest"):
        store.load(bar_type="ETH/USDT.SIM-1-HOUR-LAST-EXTERNAL")
