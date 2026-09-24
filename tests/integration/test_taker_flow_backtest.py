"""End-to-end: the ingested taker split must reach `BarVpin` inside the engine.

A unit test can prove the parser reads field 9 and that the feed joins it onto bars, but
only a real run proves nothing in between drops it again — the engine round-trip through
`nautilus_trader.model.data.Bar` is exactly where the field would vanish, since that class
has no column for it.

The probe is deliberately blunt: bars rise one unit per hour, so the tick-rule proxy calls
every bar fully one-sided (VPIN = 1, toxic) and the robot trades. The real split says half
the volume was bought and half sold, which is VPIN = 0 — never toxic, so the same robot on
the same bars must not trade at all. If the join were lost anywhere, both runs would be
identical.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.persistence.catalog.singleton import clear_singleton_instances

from nautilus_lab.application.dtos import BacktestReport, BacktestRequest
from nautilus_lab.application.run_research_backtest import RunResearchBacktest
from nautilus_lab.domain.bars import BarOrigin, OhlcvBar
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.infrastructure.nautilus.backtest_runner import NautilusResearchBacktest
from nautilus_lab.infrastructure.nautilus.bar_feed import ResearchBarFeed
from nautilus_lab.infrastructure.nautilus.parquet_catalog import NautilusParquetCatalog
from nautilus_lab.infrastructure.taker_flow_catalog import ParquetTakerFlowCatalog

_ORIGIN = datetime(2024, 1, 1, tzinfo=UTC)
_BAR_TYPE = "ETH/USDT.SIM-1-HOUR-LAST-EXTERNAL"
_BARS = 300


def _rising_bars(*, taker_buy: str | None) -> list[OhlcvBar]:
    bars: list[OhlcvBar] = []
    for index in range(_BARS):
        price = Decimal("2200") + Decimal(index)
        bars.append(
            OhlcvBar(
                instrument_id="ETH/USDT.SIM",
                ts_utc=_ORIGIN + timedelta(hours=index),
                open=price,
                high=price + Decimal("5"),
                low=price - Decimal("5"),
                close=price,
                volume=Decimal("100"),
                taker_buy_base_volume=None if taker_buy is None else Decimal(taker_buy),
            )
        )
    return bars


def _run(catalog: NautilusParquetCatalog, flow: ParquetTakerFlowCatalog | None) -> BacktestReport:
    use_case = RunResearchBacktest(
        NautilusResearchBacktest(), ResearchBarFeed(catalog, taker_flow=flow)
    )
    return use_case.execute(
        BacktestRequest(
            mode=TradingMode.RESEARCH,
            instrument_id="ETH/USDT.SIM",
            bar_count=_BARS,
            starting_equity=Decimal("100000"),
            risk=RiskLimits(
                risk_per_trade=Decimal("0.005"),
                stop_pct=Decimal("0.01"),
                max_daily_loss=Decimal("0.02"),
                max_drawdown=Decimal("0.06"),
            ),
            robot=RobotName.VPIN_MOMENTUM,
            source=BarOrigin.CATALOG,
            bar_type=_BAR_TYPE,
            # One bucket per bar, so the toxicity verdict is decided inside this series
            # rather than smeared over a warm-up nobody can see.
            vpin_bucket_volume=Decimal("100"),
        )
    )


@pytest.mark.integration
def test_real_taker_split_reaches_the_robot_and_changes_its_verdict(tmp_path: Path) -> None:
    clear_singleton_instances(ParquetDataCatalog)
    catalog = NautilusParquetCatalog(tmp_path)
    catalog.write(_rising_bars(taker_buy=None), bar_type=_BAR_TYPE)
    flow = ParquetTakerFlowCatalog(tmp_path)
    flow.write(_rising_bars(taker_buy="50"), symbol="ETHUSDT", interval="1h")

    clear_singleton_instances(ParquetDataCatalog)
    on_the_proxy = _run(catalog, None)
    clear_singleton_instances(ParquetDataCatalog)
    on_the_real_split = _run(catalog, flow)

    assert on_the_proxy.fills > 0, "the tick-rule proxy calls this series toxic and trades"
    assert on_the_real_split.fills == 0, (
        "with the real 50/50 split the same bars are never toxic, so the robot must stand"
        " aside; a fill here means the taker flow was lost on the way to BarVpin"
    )
