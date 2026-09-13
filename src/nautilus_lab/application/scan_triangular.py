from __future__ import annotations

from decimal import Decimal

from nautilus_lab.domain.triangular_arb import FxEdge, TriangularOpportunity, find_negative_cycles


def scan_triangular_opportunities(
    rates: dict[tuple[str, str], Decimal],
    *,
    fee: Decimal = Decimal("0.001"),
) -> list[TriangularOpportunity]:
    """Research scanner: detect negative-weight FX cycles (no execution)."""
    edges = tuple(
        FxEdge(source=source, target=target, rate=rate, fee=fee)
        for (source, target), rate in rates.items()
        if rate > 0
    )
    return find_negative_cycles(edges)
