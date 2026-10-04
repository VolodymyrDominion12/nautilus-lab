from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.data_quality import QualityStatus, check_bars
from nautilus_lab.domain.universe import (
    base_of,
    candidate_symbols,
    is_tradeable_base,
    top_by_dollar_volume,
)

_T0 = datetime(2021, 1, 1, 23, 59, 59, tzinfo=UTC)
_DAY = timedelta(days=1)


def _bar(day: int, close: str = "100", volume: str = "10", symbol: str = "X") -> OhlcvBar:
    price = Decimal(close)
    return OhlcvBar(
        instrument_id=symbol,
        ts_utc=_T0 + day * _DAY,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=Decimal(volume),
    )


# --- universe ---------------------------------------------------------------------


def test_candidates_drop_stablecoins_fiat_and_leveraged_tokens() -> None:
    symbols = [
        "BTCUSDT",
        "USDCUSDT",
        "FDUSDUSDT",
        "EURUSDT",
        "BTCUPUSDT",
        "ETHDOWNUSDT",
        "JUPUSDT",
        "WAVESUSDT",
        "ETHBTC",
        "BNBUSDT",
        "btcusdt",
    ]
    assert candidate_symbols(symbols) == ["BNBUSDT", "BTCUSDT", "JUPUSDT", "WAVESUSDT"]


def test_base_and_tradeability_helpers() -> None:
    assert base_of("SOLUSDT-PERP") == "SOL"
    assert base_of("USDT") is None
    assert base_of("ETHBTC") is None
    assert is_tradeable_base("UP") is True  # a bare "UP" is a coin, not a suffix
    assert is_tradeable_base("XRPBULL") is False


def test_top_by_dollar_volume_is_point_in_time() -> None:
    series = {
        # Large in the window, then gone: must still be picked on the window's date.
        "DEADUSDT": [_bar(day, close="10", volume="1000") for day in range(30)],
        "BTCUSDT": [_bar(day, close="100", volume="50") for day in range(60)],
        # Listed after the date: invisible on it.
        "NEWUSDT": [_bar(day, close="100", volume="1000000") for day in range(40, 60)],
    }
    as_of = _T0 + 29 * _DAY
    assert top_by_dollar_volume(series, as_of=as_of, n=2) == ["DEADUSDT", "BTCUSDT"]
    later = _T0 + 59 * _DAY
    assert top_by_dollar_volume(series, as_of=later, n=1, min_bars=10) == ["NEWUSDT"]


def test_top_by_dollar_volume_needs_enough_history() -> None:
    series = {"AUSDT": [_bar(day) for day in range(5)]}
    assert top_by_dollar_volume(series, as_of=_T0 + 4 * _DAY) == []
    with pytest.raises(ValueError, match="n must be"):
        top_by_dollar_volume(series, as_of=_T0, n=0)


# --- data quality -------------------------------------------------------------------


def test_a_clean_series_is_ok() -> None:
    report = check_bars([_bar(day) for day in range(10)], interval=_DAY)
    assert report.status() is QualityStatus.OK
    assert report.expected_bars == 10
    assert report.missing_bars == 0


def test_gaps_are_listed_and_a_large_share_fails() -> None:
    bars = [_bar(day) for day in range(100) if not 10 <= day < 15]
    report = check_bars(bars, interval=_DAY)
    (gap,) = report.gaps
    assert gap.missing_bars == 5
    assert gap.after == _T0 + 9 * _DAY
    assert report.status() is QualityStatus.FAIL  # 5% missing > 1%


def test_a_single_missing_bar_is_a_warning() -> None:
    bars = [_bar(day) for day in range(200) if day != 50]
    assert check_bars(bars, interval=_DAY).status() is QualityStatus.WARN


def test_a_jump_after_a_gap_is_a_relisting_suspect() -> None:
    # LUNAUSDT: the old coin stops, the ticker comes back later at a new price level.
    bars = [_bar(day, close="80") for day in range(10)]
    bars += [_bar(day, close="5") for day in range(30, 40)]
    report = check_bars(bars, interval=_DAY)
    assert len(report.relisting_suspects) == 1
    assert report.status() is QualityStatus.FAIL


def test_extreme_moves_zero_volume_and_partials_warn() -> None:
    bars = [_bar(0, close="100"), _bar(1, close="160"), _bar(2, close="160", volume="0")]
    bars += [_bar(day, close="160") for day in range(3, 200)]
    report = check_bars(bars, interval=_DAY, partial_dropped=1)
    assert len(report.extreme_moves) == 1
    assert report.zero_volume == 1
    assert report.partial_dropped == 1
    assert report.status() is QualityStatus.WARN


def test_an_empty_series_fails() -> None:
    assert check_bars([], interval=_DAY).status() is QualityStatus.FAIL
