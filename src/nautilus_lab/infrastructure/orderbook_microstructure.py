from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import polars as pl


def compute_order_book_imbalance(
    bid_volume: float | list[float],
    ask_volume: float | list[float],
) -> float:
    """Calculates single-level Order Book Imbalance (OBI). Range: [-1.0, 1.0]."""
    b_vol = sum(bid_volume) if isinstance(bid_volume, list) else float(bid_volume)
    a_vol = sum(ask_volume) if isinstance(ask_volume, list) else float(ask_volume)

    total = b_vol + a_vol
    if total <= 0.0:
        return 0.0
    return (b_vol - a_vol) / total


def compute_micro_price(
    bid_price: float,
    bid_volume: float,
    ask_price: float,
    ask_volume: float,
) -> float:
    """Calculates volume-weighted micro-price: (P_bid * V_ask + P_ask * V_bid) / (V_bid + V_ask)."""
    total = bid_volume + ask_volume
    if total <= 0.0:
        return (bid_price + ask_price) / 2.0
    return (bid_price * ask_volume + ask_price * bid_volume) / total


def compute_microstructure_dataframe(df: pl.DataFrame) -> pl.DataFrame:
    """Enriches an order book snapshot DataFrame using vectorized Polars operations.

    Expected input columns:
    - bid_price, bid_volume
    - ask_price, ask_volume
    Optional columns:
    - bid_volume_l2, ask_volume_l2 (level 2 depth)

    Adds columns:
    - spread (ask_price - bid_price)
    - spread_bps (spread / mid_price * 10000)
    - mid_price ((bid_price + ask_price) / 2)
    - obi ((bid_volume - ask_volume) / (bid_volume + ask_volume))
    - micro_price
    """
    import polars as pl

    total_vol = pl.col("bid_volume") + pl.col("ask_volume")
    mid_price = (pl.col("bid_price") + pl.col("ask_price")) / 2.0
    spread = pl.col("ask_price") - pl.col("bid_price")
    vol_diff = pl.col("bid_volume") - pl.col("ask_volume")
    val_bid = pl.col("bid_price") * pl.col("ask_volume")
    val_ask = pl.col("ask_price") * pl.col("bid_volume")
    micro_val = (val_bid + val_ask) / total_vol

    return df.with_columns(
        spread=spread,
        mid_price=mid_price,
        spread_bps=pl.when(mid_price > 0).then((spread / mid_price) * 10000.0).otherwise(0.0),
        obi=pl.when(total_vol > 0).then(vol_diff / total_vol).otherwise(0.0),
        micro_price=pl.when(total_vol > 0).then(micro_val).otherwise(mid_price),
    )
