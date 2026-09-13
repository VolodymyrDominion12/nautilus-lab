import pytest

from nautilus_lab.infrastructure.nautilus.synthetic_bars import synthetic_ohlcv


def test_synthetic_bars_are_validated_and_deterministic() -> None:
    first = synthetic_ohlcv(instrument_id="ETH/USDT.SIM", count=30, seed=1)
    second = synthetic_ohlcv(instrument_id="ETH/USDT.SIM", count=30, seed=1)

    assert len(first) == 30
    assert first[0].close == second[0].close
    assert first[-1].ts_utc > first[0].ts_utc


def test_synthetic_bars_reject_empty() -> None:
    with pytest.raises(ValueError, match="count"):
        synthetic_ohlcv(instrument_id="ETH/USDT.SIM", count=0, seed=1)


def test_negative_volume_is_rejected_by_generator_contract() -> None:
    bars = synthetic_ohlcv(instrument_id="ETH/USDT.SIM", count=5, seed=3)
    assert all(bar.volume >= 0 for bar in bars)
    assert all(bar.high >= max(bar.open, bar.close) for bar in bars)
