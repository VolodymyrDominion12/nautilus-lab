from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from nautilus_lab.application.alpha.panel import Panel
from nautilus_lab.infrastructure.alpha_panel_store import (
    bar_type_for,
    interval_minutes,
    load_panel,
    save_panel,
)


def test_bar_type_matches_the_catalog_folders() -> None:
    assert bar_type_for("BTCUSDT", "1h", perp=True) == "BTCUSDT-PERP.SIM-1-HOUR-LAST-EXTERNAL"
    assert bar_type_for("ETHUSDT-PERP", "4h", perp=True) == "ETHUSDT-PERP.SIM-4-HOUR-LAST-EXTERNAL"
    assert bar_type_for("ETHUSDT", "1d", perp=False) == "ETHUSDT.SIM-1-DAY-LAST-EXTERNAL"
    assert interval_minutes("4h") == 240


def test_panel_cache_round_trips_nan_exactly(tmp_path: Path) -> None:
    close = np.array([[1.0, np.nan], [2.0, 3.0]])
    fields = {name: close.copy() for name in ("close", "high", "low", "volume")}
    fields["funding_last"] = np.array([[np.nan, 0.0001], [0.0002, np.nan]])
    panel = Panel(np.array([60, 120], dtype=np.int64), ("BTCUSDT", "ETHUSDT"), fields, 60)
    path = tmp_path / "panels" / "perp_1h.npz"
    save_panel(panel, path, source={"bar_catalog": "catalog_perp_1h"})
    loaded = load_panel(path)
    assert loaded.symbols == panel.symbols
    assert loaded.bar_minutes == 60
    np.testing.assert_array_equal(loaded.ts_min, panel.ts_min)
    for name, values in panel.fields.items():
        np.testing.assert_array_equal(loaded.get(name), values)
    assert not list(path.parent.glob("*.tmp*"))


def test_stale_cache_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "old.npz"
    np.savez_compressed(path, ts_min=np.array([1]), meta=np.array('{"version": 0}'))
    with pytest.raises(ValueError, match="rebuild"):
        load_panel(path)


def test_build_panel_aligns_every_series(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from dataclasses import dataclass
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    from nautilus_lab.infrastructure import alpha_panel_store as store

    origin = datetime(2021, 1, 1, tzinfo=UTC)

    def close_at(hour: int) -> datetime:
        return origin + timedelta(hours=hour) - timedelta(microseconds=1)

    @dataclass
    class Bar:
        ts_utc: datetime
        close: Decimal
        high: Decimal
        low: Decimal
        volume: Decimal

    @dataclass
    class Funding:
        ts_utc: datetime
        funding_rate: Decimal

    @dataclass
    class Premium:
        ts_utc: datetime
        close: Decimal

    hours = {"BTCUSDT": range(1, 11), "ETHUSDT": range(3, 11)}  # ETH lists later

    class Bars:
        def __init__(self, path: Path, **_: object) -> None:
            self.path = path

        def load(self, *, bar_type: str) -> list[Bar]:
            base = bar_type.split("-PERP")[0]
            return [
                Bar(close_at(h), Decimal(h), Decimal(h + 1), Decimal(h - 1), Decimal(10))
                for h in hours[base]
            ]

    class Taker:
        def __init__(self, path: Path) -> None:
            self.path = path

        def load(self, *, symbol: str, interval: str) -> dict[datetime, Decimal]:
            assert symbol.endswith("-PERP")
            assert interval == "1h"
            return {close_at(5): Decimal(7)}

    class Prem:
        def __init__(self, path: Path) -> None:
            self.path = path

        def load(self, *, symbol: str, interval: str) -> list[Premium]:
            return [Premium(close_at(h), Decimal("0.001")) for h in hours[symbol]]

    class Fund:
        def __init__(self, path: Path) -> None:
            self.path = path

        def load(self, *, symbol: str) -> list[Funding]:
            return [Funding(origin + timedelta(hours=8), Decimal("0.0001"))]

    monkeypatch.setattr(store, "NautilusParquetCatalog", Bars)
    monkeypatch.setattr(store, "ParquetTakerFlowCatalog", Taker)
    monkeypatch.setattr(store, "ParquetPremiumIndexCatalog", Prem)
    monkeypatch.setattr(store, "ParquetFundingCatalog", Fund)
    monkeypatch.setattr(
        store, "datetime_to_nanos", lambda ts: int(ts.timestamp()) * 10**9 + ts.microsecond * 1000
    )

    panel = store.build_panel(
        bar_catalog=tmp_path,
        symbols=["BTCUSDT", "ETHUSDT-PERP"],
        interval="1h",
        funding_catalog=tmp_path,
    )
    assert panel.symbols == ("BTCUSDT", "ETHUSDT")
    assert panel.shape == (10, 2)
    close = panel.get("close")
    assert close[0, 0] == 1.0
    assert np.isnan(close[0, 1])
    assert close[2, 1] == 3.0
    taker = panel.get("taker_buy")
    assert taker[4, 0] == 7.0
    assert np.isnan(taker[3, 0])
    paid = panel.get("funding_paid")
    row_8h = 7  # bar closing at 08:00 is the 8th hour (index 7)
    assert paid[row_8h, 0] == pytest.approx(0.0001)
    assert paid[row_8h + 1, 0] == 0.0
    assert np.isnan(paid[row_8h - 1, 0])
    assert panel.get("funding_last")[-1, 1] == pytest.approx(0.0001)
