"""Where a research run spends its time, by phase.

One process-wide accumulator (`TIMINGS`), the way `logging` is process-wide: the phases
are measured deep inside the walk-forward and the engine adapter, and threading a timer
object through every constructor would touch a dozen signatures for an instrument that
changes no result. `run_research_job` resets it, the run fills it, and the job writes it
next to `last_run.json` as `timings.json`; the batch runner aggregates the cells.

Phases nest (`is_search` contains every `engine_run` of the grid), so the seconds of
different phases are not meant to add up to the total. A phase measured in a worker
process comes back with the worker's result and is merged (`merge`), so the totals count
CPU seconds spent in that phase across processes, while `is_search` stays wall time.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any


class PhaseTimer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seconds: dict[str, float] = {}
        self._counts: dict[str, int] = {}
        self._started = time.perf_counter()

    def reset(self) -> None:
        with self._lock:
            self._seconds.clear()
            self._counts.clear()
            self._started = time.perf_counter()

    def add(self, name: str, seconds: float, count: int = 1) -> None:
        with self._lock:
            self._seconds[name] = self._seconds.get(name, 0.0) + seconds
            self._counts[name] = self._counts.get(name, 0) + count

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self.add(name, time.perf_counter() - started)

    def merge(self, phases: Mapping[str, Mapping[str, Any]]) -> None:
        """Add phases measured elsewhere (a worker process), in `snapshot()` shape."""
        for name, entry in phases.items():
            self.add(name, float(entry.get("seconds", 0.0)), int(entry.get("count", 0)))

    def snapshot(self) -> dict[str, dict[str, float | int]]:
        with self._lock:
            return {
                name: {"seconds": round(self._seconds[name], 4), "count": self._counts[name]}
                for name in sorted(self._seconds, key=lambda key: -self._seconds[key])
            }

    def elapsed(self) -> float:
        return time.perf_counter() - self._started


#: The process's timer. Reset at the start of a job (`run_research_job.main`).
TIMINGS = PhaseTimer()


def merge_phase_totals(
    snapshots: list[Mapping[str, Mapping[str, Any]]],
) -> dict[str, dict[str, float | int]]:
    """Sum several `snapshot()`s (one per batch cell) into one, slowest phase first."""
    total = PhaseTimer()
    for snapshot in snapshots:
        total.merge(snapshot)
    return total.snapshot()


def format_phase_table(phases: Mapping[str, Mapping[str, Any]], *, total: float | None) -> str:
    """A small fixed-width table for logs: phase, seconds, share of the total, count."""
    lines = [f"{'phase':<22} {'seconds':>10} {'% wall':>7} {'count':>7}"]
    for name, entry in phases.items():
        seconds = float(entry.get("seconds", 0.0))
        share = f"{seconds / total * 100:6.1f}%" if total else "     -"
        lines.append(f"{name:<22} {seconds:>10.2f} {share:>7} {int(entry.get('count', 0)):>7}")
    if total is not None:
        lines.append(f"{'total (wall)':<22} {total:>10.2f}")
    return "\n".join(lines)
