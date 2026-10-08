"""Run the in-sample grid's candidates side by side, one worker process each.

A walk-forward fold scores every grid point on the same in-sample bars (15 for `regime`),
and the runs do not depend on one another: each is its own `BacktestEngine` with its own
seeded fill model. The strategies are Python, so threads would share one GIL; processes
are the only way to put more than one core on a cell. `ParallelResearchBacktest` wraps the
ordinary engine adapter, delegates every single run to it unchanged, and adds `run_many`,
which `RunWalkForward` uses for the grid when the engine offers it.

What makes the result identical to the serial path:

* every candidate runs through the same `NautilusResearchBacktest.run`, with the request
  it would have had serially (same seed, same fees, same latency);
* reports come back in submission order, so the ranking and its tie-break do not change;
* runs that must write decisions (a `session_id` with a decision log attached) or a
  tearsheet stay in this process — a worker has neither the log nor the parent's paths.

The bars travel once per fold, not once per candidate: the parent pickles them to a temp
file and each worker loads that file the first time it sees it. Workers are started with
`spawn`, never `fork`: a forked copy of a process that already ran a Rust engine can hold
locks of threads that do not exist in the child.
"""

from __future__ import annotations

import logging
import multiprocessing
import os
import pickle
import shutil
import tempfile
import weakref
from collections import OrderedDict
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Any

from nautilus_lab.application.dtos import (
    BacktestReport,
    BacktestRequest,
    PaperSessionReport,
)
from nautilus_lab.application.timing import TIMINGS
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.funding import FundingSnapshot
from nautilus_lab.domain.order_book import OrderBookSnapshot
from nautilus_lab.domain.ticks import AggTrade
from nautilus_lab.infrastructure.nautilus.backtest_runner import NautilusResearchBacktest

_log = logging.getLogger(__name__)

#: More workers than this rarely pays: a regime grid has 15 candidates per fold.
MAX_IS_WORKERS = 8

_Payload = tuple[list[OhlcvBar], list[AggTrade] | None, list[OrderBookSnapshot] | None]


def resolve_is_workers(configured: int, *, cpu_count: int | None = None) -> int:
    """`BACKTEST_IS_WORKERS` as a process count: 0 = auto (all cores but one), capped."""
    if configured < 0:
        raise ValueError(f"BACKTEST_IS_WORKERS must be >= 0, got {configured}")
    if configured == 0:
        cores = cpu_count if cpu_count is not None else (os.cpu_count() or 1)
        configured = cores - 1
    return max(1, min(MAX_IS_WORKERS, configured))


class ParallelResearchBacktest:
    """`NautilusResearchBacktest` plus `run_many` over a process pool."""

    def __init__(self, inner: NautilusResearchBacktest, *, workers: int) -> None:
        self._inner = inner
        self._workers = max(1, workers)
        self._pool: ProcessPoolExecutor | None = None
        self._scratch: Path | None = None
        # The payload currently on disk and the objects it was written from. Holding the
        # objects keeps their ids from being reused by a different list while cached.
        self._payload_key: tuple[int, int, int, int] | None = None
        self._payload_refs: _Payload | None = None
        self._payload_path: Path | None = None
        self._finalizer = weakref.finalize(self, _shutdown, None, None)

    # --- the single-run port, unchanged ------------------------------------------------
    @property
    def decision_log(self) -> Any:  # noqa: ANN401 — the inner adapter's port, whatever it is
        return self._inner.decision_log

    @property
    def workers(self) -> int:
        return self._workers

    def run(
        self,
        request: BacktestRequest,
        bars: list[OhlcvBar],
        ticks: list[AggTrade] | None = None,
        books: list[OrderBookSnapshot] | None = None,
    ) -> BacktestReport:
        return self._inner.run(request, bars, ticks, books)

    def run_paper(
        self,
        request: BacktestRequest,
        bars: list[OhlcvBar],
        ticks: list[AggTrade] | None = None,
        books: list[OrderBookSnapshot] | None = None,
    ) -> PaperSessionReport:
        return self._inner.run_paper(request, bars, ticks, books)

    def run_spread(
        self,
        request: BacktestRequest,
        bars_by_instrument: dict[str, list[OhlcvBar]],
        funding: list[FundingSnapshot] | None = None,
    ) -> BacktestReport:
        return self._inner.run_spread(request, bars_by_instrument, funding)

    def run_paper_spread(
        self,
        request: BacktestRequest,
        bars_by_instrument: dict[str, list[OhlcvBar]],
        funding: list[FundingSnapshot] | None = None,
    ) -> PaperSessionReport:
        return self._inner.run_paper_spread(request, bars_by_instrument, funding)

    # --- the batch path ----------------------------------------------------------------
    def run_many(
        self,
        requests: Sequence[BacktestRequest],
        bars: list[OhlcvBar],
        ticks: list[AggTrade] | None = None,
        books: list[OrderBookSnapshot] | None = None,
    ) -> list[BacktestReport]:
        """One report per request, in the order given."""
        if self._workers <= 1 or len(requests) <= 1 or not self._parallel_safe(requests):
            return [self._inner.run(request, bars, ticks, books) for request in requests]
        try:
            pool = self._ensure_pool()
            payload = self._write_payload(bars, ticks, books)
            futures = [pool.submit(_run_in_worker, str(payload), request) for request in requests]
            results = [future.result() for future in futures]
        except (BrokenProcessPool, OSError, pickle.PicklingError) as exc:
            # A worker that died (out of memory, killed) must not lose the cell: the
            # serial path gives the same reports, only slower.
            _log.warning("parallel in-sample grid failed (%s); running it serially", exc)
            self.close()
            self._workers = 1
            return [self._inner.run(request, bars, ticks, books) for request in requests]
        reports: list[BacktestReport] = []
        for report, phases in results:
            TIMINGS.merge(phases)
            reports.append(report)
        return reports

    def close(self) -> None:
        """Stop the workers and remove the payload files. Safe to call twice."""
        self._finalizer.detach()
        _shutdown(self._pool, self._scratch)
        self._pool = None
        self._scratch = None
        self._payload_key = None
        self._payload_refs = None
        self._payload_path = None

    def _parallel_safe(self, requests: Sequence[BacktestRequest]) -> bool:
        if any(request.tearsheet_path for request in requests):
            return False
        has_log = self._inner.decision_log is not None
        return not (has_log and any(request.session_id for request in requests))

    def _ensure_pool(self) -> ProcessPoolExecutor:
        if self._pool is None:
            self._scratch = Path(tempfile.mkdtemp(prefix="nautilus-lab-is-"))
            self._pool = ProcessPoolExecutor(
                max_workers=self._workers,
                mp_context=multiprocessing.get_context("spawn"),
            )
            self._finalizer.detach()
            self._finalizer = weakref.finalize(self, _shutdown, self._pool, self._scratch)
        return self._pool

    def _write_payload(
        self,
        bars: list[OhlcvBar],
        ticks: list[AggTrade] | None,
        books: list[OrderBookSnapshot] | None,
    ) -> Path:
        key = (id(bars), id(ticks), id(books), len(bars))
        if key == self._payload_key and self._payload_path is not None:
            return self._payload_path
        assert self._scratch is not None  # noqa: S101 — set by _ensure_pool
        with TIMINGS.phase("is_payload_write"):
            if self._payload_path is not None:
                self._payload_path.unlink(missing_ok=True)
            fd, name = tempfile.mkstemp(dir=self._scratch, suffix=".pkl")
            with os.fdopen(fd, "wb") as handle:
                pickle.dump((bars, ticks, books), handle, protocol=pickle.HIGHEST_PROTOCOL)
        self._payload_key = key
        self._payload_refs = (bars, ticks, books)
        self._payload_path = Path(name)
        return self._payload_path


def _shutdown(pool: ProcessPoolExecutor | None, scratch: Path | None) -> None:
    if pool is not None:
        pool.shutdown(wait=True, cancel_futures=True)
    if scratch is not None:
        shutil.rmtree(scratch, ignore_errors=True)


# --- worker side ----------------------------------------------------------------------
_WORKER_ENGINE: NautilusResearchBacktest | None = None
_WORKER_PAYLOADS: OrderedDict[str, _Payload] = OrderedDict()


def _run_in_worker(
    payload_path: str, request: BacktestRequest
) -> tuple[BacktestReport, dict[str, dict[str, float | int]]]:
    """One in-sample run in a worker. Returns the report and the phases it spent time in."""
    global _WORKER_ENGINE
    TIMINGS.reset()
    payload = _WORKER_PAYLOADS.get(payload_path)
    if payload is None:
        with TIMINGS.phase("is_payload_load"), Path(payload_path).open("rb") as handle:
            payload = pickle.load(handle)  # noqa: S301 — written by our own parent
        _WORKER_PAYLOADS[payload_path] = payload
        while len(_WORKER_PAYLOADS) > 2:
            _WORKER_PAYLOADS.popitem(last=False)
    if _WORKER_ENGINE is None:
        # No decision log: the parent keeps every run that would write one.
        _WORKER_ENGINE = NautilusResearchBacktest(decision_log=None)
    bars, ticks, books = payload
    report = _WORKER_ENGINE.run(request, bars, ticks, books)
    return report, TIMINGS.snapshot()
