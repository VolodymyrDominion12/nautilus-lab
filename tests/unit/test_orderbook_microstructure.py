import polars as pl
import pytest

from nautilus_lab.infrastructure.orderbook_microstructure import (
    compute_micro_price,
    compute_microstructure_dataframe,
    compute_order_book_imbalance,
)


def test_compute_order_book_imbalance_scalar() -> None:
    assert compute_order_book_imbalance(10.0, 10.0) == pytest.approx(0.0)
    assert compute_order_book_imbalance(20.0, 0.0) == pytest.approx(1.0)
    assert compute_order_book_imbalance(0.0, 20.0) == pytest.approx(-1.0)
    assert compute_order_book_imbalance(15.0, 5.0) == pytest.approx(0.5)
    assert compute_order_book_imbalance(0.0, 0.0) == pytest.approx(0.0)


def test_compute_order_book_imbalance_list() -> None:
    bids = [10.0, 5.0]
    asks = [5.0, 5.0]
    assert compute_order_book_imbalance(bids, asks) == pytest.approx(0.2)


def test_compute_micro_price() -> None:
    # Balanced
    assert compute_micro_price(100.0, 10.0, 102.0, 10.0) == pytest.approx(101.0)
    # Skewed towards ask (more volume on bid pulls micro price towards ask)
    micro = compute_micro_price(100.0, 30.0, 102.0, 10.0)
    assert micro > 101.0
    assert micro == pytest.approx((100.0 * 10.0 + 102.0 * 30.0) / 40.0)
    # Zero volume fallback
    assert compute_micro_price(100.0, 0.0, 102.0, 0.0) == pytest.approx(101.0)


def test_compute_microstructure_dataframe() -> None:
    df = pl.DataFrame(
        {
            "bid_price": [100.0, 200.0],
            "bid_volume": [10.0, 30.0],
            "ask_price": [101.0, 202.0],
            "ask_volume": [10.0, 10.0],
        }
    )
    res = compute_microstructure_dataframe(df)

    assert "spread" in res.columns
    assert "spread_bps" in res.columns
    assert "obi" in res.columns
    assert "micro_price" in res.columns

    assert res["spread"].to_list() == [1.0, 2.0]
    assert res["obi"].to_list()[0] == pytest.approx(0.0)
    assert res["obi"].to_list()[1] == pytest.approx(0.5)
    assert res["micro_price"].to_list()[0] == pytest.approx(100.5)
