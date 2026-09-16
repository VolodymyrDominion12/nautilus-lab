from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from nautilus_lab.application.catalog_queries import (
    bar_interval_to_timedelta,
    incremental_ingest_start,
)
from nautilus_lab.application.run_alpha_proposal import ProposeJobConfig, execute_propose
from nautilus_lab.infrastructure.settings import Settings


def test_bar_interval_to_timedelta_maps_1h() -> None:
    assert bar_interval_to_timedelta("1h") == timedelta(hours=1)


def test_incremental_ingest_start_empty_catalog_uses_default(tmp_path: Path) -> None:
    missing = tmp_path / "missing-catalog"
    cfg = Settings(catalog_path=str(missing))
    default_start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 6, 1, tzinfo=UTC)
    start = incremental_ingest_start(
        cfg,
        catalog_path=cfg.catalog_path,
        symbol="ETHUSDT",
        default_start=default_start,
        end=end,
    )
    assert start == default_start


def test_execute_propose_dry_run() -> None:
    result = execute_propose(ProposeJobConfig(count=2, dry_run=True))
    assert result["status"] == "dry_run"
    assert "prompt" in result


def test_settings_all_catalog_paths_deduplicates() -> None:
    cfg = Settings(catalog_path="catalog", catalog_paths="catalog,catalog-1h")
    paths = cfg.all_catalog_paths()
    assert paths == ["catalog", "catalog-1h"]
