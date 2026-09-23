from decimal import Decimal

from nautilus_lab.domain.marking import (
    OpenLot,
    lot_unrealized_pnl,
    marked_equity,
    unrealized_pnl,
)


def test_short_under_water_reduces_equity() -> None:
    """The ema paper session: short 26.463 @ 1897.59 marked at 2612.14."""
    lot = OpenLot(
        instrument_id="ETH/USDT.SIM",
        signed_qty=Decimal("-26.463"),
        avg_price=Decimal("1897.59"),
    )
    pnl = lot_unrealized_pnl(lot, Decimal("2612.14"))
    assert pnl == Decimal("-18909.13665")
    assert (
        marked_equity(Decimal("94136.26"), [lot], {"ETH/USDT.SIM": Decimal("2612.14")})
        == Decimal("94136.26") + pnl
    )


def test_long_gain_and_sum_over_instruments() -> None:
    lots = [
        OpenLot(instrument_id="A", signed_qty=Decimal("2"), avg_price=Decimal("100")),
        OpenLot(instrument_id="B", signed_qty=Decimal("-1"), avg_price=Decimal("50")),
    ]
    marks = {"A": Decimal("110"), "B": Decimal("40")}
    assert unrealized_pnl(lots, marks) == Decimal("20") + Decimal("10")


def test_lot_without_mark_is_valued_at_entry() -> None:
    lots = [OpenLot(instrument_id="A", signed_qty=Decimal("2"), avg_price=Decimal("100"))]
    assert unrealized_pnl(lots, {}) == Decimal("0")
    assert marked_equity(Decimal("1000"), lots, {}) == Decimal("1000")


def test_no_lots_is_the_balance() -> None:
    assert marked_equity(Decimal("1000"), [], {"A": Decimal("1")}) == Decimal("1000")
