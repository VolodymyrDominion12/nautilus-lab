"""The research feed checks the QC verdict before it reads a catalog series."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

import pytest

from nautilus_lab.domain.bars import BarOrigin, OhlcvBar
from nautilus_lab.domain.errors import DataQualityError
from nautilus_lab.infrastructure.nautilus.bar_feed import ResearchBarFeed
from nautilus_lab.interfaces.composition import research_request, settings


class _Catalog:
    def __init__(self) -> None:
        self.loaded: list[str] = []

    def write(self, *args: Any, **kwargs: Any) -> int:
        return 0

    def load(
        self, *, bar_type: str, start: datetime | None = None, end: datetime | None = None
    ) -> list[OhlcvBar]:
        self.loaded.append(bar_type)
        return []


def _refuse(bar_type: str) -> str:
    raise DataQualityError(f"{bar_type} failed")


def test_a_failed_series_is_never_read() -> None:
    catalog = _Catalog()
    request = research_request(settings(), bar_count=100)
    feed = ResearchBarFeed(catalog, quality_gate=_refuse)
    with pytest.raises(DataQualityError):
        feed.load(replace(request, source=BarOrigin.CATALOG))
    assert catalog.loaded == []


def test_synthetic_bars_skip_the_gate() -> None:
    request = research_request(settings(), bar_count=50, source=BarOrigin.SYNTHETIC)
    bars = ResearchBarFeed(_Catalog(), quality_gate=_refuse).load(request)
    assert len(bars) == 50
