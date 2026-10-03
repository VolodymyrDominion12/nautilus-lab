from __future__ import annotations

from pathlib import Path

import pytest

from nautilus_lab.api.catalog_service import (
    describe_catalog,
    discover_catalog_paths,
    list_catalogs,
)
from nautilus_lab.infrastructure.settings import Settings


def test_discover_catalog_paths_finds_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "catalog_alpha" / "data").mkdir(parents=True)
    (tmp_path / "catalog_beta" / "data").mkdir(parents=True)
    (tmp_path / "other_dir").mkdir()

    import nautilus_lab.api.catalog_service as cs

    monkeypatch.setattr(cs, "repo_root", lambda: tmp_path)

    cfg = Settings(catalog_path="catalog_alpha")
    paths = discover_catalog_paths(cfg)
    assert "catalog_alpha" in paths
    assert "catalog_beta" in paths
    assert "other_dir" not in paths


def test_describe_catalog_missing_returns_proper_summary(tmp_path: Path) -> None:
    missing = tmp_path / "non_existent_catalog"
    desc = describe_catalog(str(missing))
    assert desc["exists"] is False
    assert desc["total_instruments"] == 0
    assert desc["total_bars"] == 0
    assert desc["market_type"] == "unknown"


def test_list_catalogs_includes_metadata_and_symbols() -> None:
    payload = list_catalogs()
    assert "default" in payload
    assert "catalogs" in payload
    assert "all_symbols" in payload
    assert isinstance(payload["catalogs"], list)
    assert len(payload["catalogs"]) >= 1

    first = payload["catalogs"][0]
    assert "name" in first
    assert "market_type" in first
    assert "total_bars" in first
    assert "has_funding" in first
