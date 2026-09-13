from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import log


@dataclass(frozen=True, slots=True)
class FxEdge:
    source: str
    target: str
    rate: Decimal
    fee: Decimal


@dataclass(frozen=True, slots=True)
class TriangularOpportunity:
    cycle: tuple[str, ...]
    profit_log: Decimal


def find_negative_cycles(edges: tuple[FxEdge, ...]) -> list[TriangularOpportunity]:
    """Bellman-Ford style negative cycle detection on -log(rate*(1-fee))."""
    nodes = sorted({edge.source for edge in edges} | {edge.target for edge in edges})
    weight: dict[tuple[str, str], Decimal] = {}
    for edge in edges:
        if edge.rate <= 0:
            continue
        w = Decimal(str(-log(float(edge.rate * (Decimal("1") - edge.fee)))))
        weight[(edge.source, edge.target)] = w

    opportunities: list[TriangularOpportunity] = []
    for start in nodes:
        dist = {node: Decimal("0") if node == start else Decimal("Infinity") for node in nodes}
        predecessor: dict[str, str | None] = {node: None for node in nodes}
        for _ in range(len(nodes) - 1):
            updated = False
            for (src, dst), w in weight.items():
                if dist[src] + w < dist[dst]:
                    dist[dst] = dist[src] + w
                    predecessor[dst] = src
                    updated = True
            if not updated:
                break
        for (src, dst), w in weight.items():
            if dist[src] + w < dist[dst]:
                cycle = _reconstruct_cycle(dst, predecessor)
                if cycle:
                    profit = -sum(
                        weight.get((cycle[index], cycle[index + 1]), Decimal("0"))
                        for index in range(len(cycle) - 1)
                    )
                    opportunities.append(
                        TriangularOpportunity(cycle=cycle, profit_log=Decimal(str(profit)))
                    )
    return opportunities


def _reconstruct_cycle(node: str, predecessor: dict[str, str | None]) -> tuple[str, ...] | None:
    visited: set[str] = set()
    current: str | None = node
    for _ in range(len(predecessor) + 1):
        if current is None:
            return None
        if current in visited:
            break
        visited.add(current)
        current = predecessor.get(current)
    if current is None:
        return None
    cycle_nodes: list[str] = [current]
    walker: str | None = predecessor.get(current)
    while walker is not None and walker != current:
        cycle_nodes.append(walker)
        walker = predecessor.get(walker)
    cycle_nodes.append(current)
    cycle_nodes.reverse()
    return tuple(cycle_nodes)
