"""Run one batch backtest: every runnable cell as its own `run_research_job` child.

`python -m nautilus_lab.api.run_batch_job --batch-dir reports/batches/<id>`

Each cell is a separate process with its own settings (instrument, catalog, interval,
models) passed as environment overrides — the same mechanism the 2026-09-29 sweep used,
so one cell's settings can never leak into another's. What differs from the sweep:

* one pass per cell, not two: `DECISION_LOG_SCOPE=oos` makes the walk-forward log only
  each fold's out-of-sample run, under `<session>-f<fold>` (`run_walk_forward.py`);
* the result is the Research tab's structured `last_run.json`, not parsed stdout;
* the trial ledger and the journal go into the batch directory, so exploratory batches
  do not rewrite the tracked `research/` files (and do not make later runs `+dirty`).

SIGTERM (the dashboard's Cancel) stops the children and marks what did not finish.

`--resume` continues a batch that stopped half-way (its process died with the machine, or
it was cancelled): finished cells are kept, the rest run again (`batch_store.resume_batch_dir`).
The dashboard's Continue button does the same through `POST /api/batches/{id}/resume`.

Speed (2026-10-08):

* `--cpu-budget N` is how many cores the batch may keep busy. `parallel` cells run at once,
  and each cell spreads its in-sample grid over `N // parallel` worker processes
  (`BACKTEST_IS_WORKERS`, `parallel_backtest.py`). Default: all cores but one. A cell whose
  `env` sets `BACKTEST_IS_WORKERS` keeps its own value. Results do not depend on it.
* every cell writes `timings.json` (where its wall time went); the batch copies the compact
  form into `batch.json` per cell and sums them into `batch.json["timings"]` at the end.
* `--profile` adds `profile.pstats`/`profile.txt` per cell (cProfile) and runs each grid
  serially, so the profile sees the in-sample runs instead of a process waiting on workers.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import threading
import time
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import Any

from nautilus_lab.api.batch_store import (
    CANCELLED,
    FAILED,
    OK,
    QUEUED,
    RUNNING,
    cell_dir,
    cell_timings,
    decisions_dir,
    descendant_pids,
    read_json,
    request_from_dict,
    resume_batch_dir,
    write_json,
)
from nautilus_lab.application.batch_plan import BatchCell, research_job_config
from nautilus_lab.application.timing import format_phase_table, merge_phase_totals

#: A cell that runs longer than this is stopped (a 1h regime walk-forward takes ~15 min).
CELL_TIMEOUT_SECONDS = 4 * 3600
#: Upper bound on in-sample workers per cell, whatever the budget (`MAX_IS_WORKERS`).
MAX_IS_WORKERS_PER_CELL = 8
#: Settings that feed tick events through the engine: orders of magnitude more events
#: than bars, so a batch that turns them on is warned once.
_TICK_SETTINGS = ("USE_TICK_VPIN", "USE_HAWKES")


def default_cpu_budget() -> int:
    """`BATCH_CPU_BUDGET` if set, else all cores but one."""
    raw = os.environ.get("BATCH_CPU_BUDGET", "").strip()
    if raw:
        return max(1, int(raw))
    return max(1, (os.cpu_count() or 2) - 1)


def is_workers_per_cell(cpu_budget: int, parallel: int) -> int:
    """In-sample workers each running cell gets so the batch stays within its budget."""
    return max(1, min(MAX_IS_WORKERS_PER_CELL, cpu_budget // max(1, parallel)))


class BatchRun:
    def __init__(
        self,
        batch_path: Path,
        *,
        python: str = sys.executable,
        cpu_budget: int | None = None,
        profile: bool = False,
    ) -> None:
        self.path = batch_path
        self.python = python
        self.cpu_budget = cpu_budget
        self.profile = profile
        self._lock = threading.Lock()
        self._children: dict[str, subprocess.Popen[str]] = {}
        self._cancelled = threading.Event()
        self._is_workers = 1
        self._run_started = time.perf_counter()

    # --- batch.json, one writer --------------------------------------------------------
    def _load(self) -> dict[str, Any]:
        batch = read_json(self.path / "batch.json")
        if batch is None:
            raise FileNotFoundError(self.path / "batch.json")
        return batch

    def _update(self, cell_id: str | None = None, **fields: Any) -> None:  # noqa: ANN401
        with self._lock:
            batch = self._load()
            if cell_id is None:
                batch.update(fields)
            else:
                for cell in batch["cells"]:
                    if cell["cell_id"] == cell_id:
                        cell.update(fields)
            write_json(self.path / "batch.json", batch)

    # --- running -----------------------------------------------------------------------
    def run(self) -> int:
        batch = self._load()
        request = request_from_dict(batch["request"])
        self._run_started = time.perf_counter()
        cells = [_cell_from_dict(cell) for cell in batch["cells"] if cell.get("status") == QUEUED]
        budget = self.cpu_budget if self.cpu_budget is not None else default_cpu_budget()
        self._is_workers = 1 if self.profile else is_workers_per_cell(budget, request.parallel)
        self._update(
            status=RUNNING,
            pid=os.getpid(),
            started_at=_now(),
            cpu_budget=budget,
            is_workers=self._is_workers,
        )
        print(
            f"batch: {len(cells)} cell(s), parallel={request.parallel}, cpu_budget={budget}, "
            f"in-sample workers per cell={self._is_workers}"
            + (" (profiling: grid runs serially)" if self.profile else ""),
            flush=True,
        )
        _warn_tick_settings(cells)
        with ThreadPoolExecutor(max_workers=request.parallel) as pool:
            list(pool.map(lambda cell: self._run_cell(request, cell), cells))
        final = CANCELLED if self._cancelled.is_set() else OK
        timings = self._batch_timings()
        self._update(status=final, finished_at=_now(), pid=None, timings=timings)
        return 0

    def _batch_timings(self) -> dict[str, Any]:
        """Every cell's phases summed, plus the batch's own wall time; printed to the log."""
        batch = self._load()
        records = [cell.get("timings") for cell in batch["cells"] if cell.get("timings")]
        phases = merge_phase_totals([record.get("phases") or {} for record in records])
        cell_seconds = sum(float(record.get("total_seconds") or 0) for record in records)
        wall = time.perf_counter() - self._run_started
        summary = {
            "cells_timed": len(records),
            "wall_seconds": round(wall, 2),
            "cell_seconds": round(cell_seconds, 2),
            "import_seconds": round(
                sum(float(record.get("import_seconds") or 0) for record in records), 2
            ),
            "phases": phases,
        }
        if records:
            print(
                f"batch timings: {len(records)} cell(s), wall {wall:.1f} s, "
                f"cells {cell_seconds:.1f} s (phases summed over cells and workers)",
                flush=True,
            )
            print(format_phase_table(phases, total=cell_seconds or None), flush=True)
        return summary

    def _run_cell(self, request: Any, cell: BatchCell) -> None:  # noqa: ANN401
        if self._cancelled.is_set():
            self._update(cell.cell_id, status=CANCELLED)
            return
        path = cell_dir(self.path, cell.cell_id)
        decisions_dir(path).mkdir(parents=True, exist_ok=True)
        config_path = path / "config.json"
        write_json(config_path, research_job_config(request, cell))
        env = {
            **os.environ,
            **cell.env,
            "DECISION_LOG_ENABLED": "true",
            "DECISION_LOG_DIR": str(decisions_dir(path).resolve()),
            "DECISION_LOG_SCOPE": "oos",
            "DECISION_LOG_RETENTION_DAYS": "0",
            "TRIALS_LEDGER_PATH": str((self.path / "trials" / f"{cell.cell_id}.jsonl").resolve()),
            "JOURNAL_ENABLED": "false",
            "INSTRUMENT_ID": cell.instrument_id,
            "BAR_INTERVAL": cell.interval,
            "CATALOG_PATH": cell.catalog,
        }
        # The cell's own value wins (a batch `env` may pin it); otherwise the budget decides.
        if "BACKTEST_IS_WORKERS" not in cell.env or self.profile:
            env["BACKTEST_IS_WORKERS"] = str(self._is_workers)
        if self.profile:
            env["RESEARCH_PROFILE"] = "1"
        cmd = [
            self.python,
            "-m",
            "nautilus_lab.api.run_research_job",
            "--config-json",
            str(config_path),
            "--reports-dir",
            str(path),
        ]
        self._update(cell.cell_id, status=RUNNING, started_at=_now())
        log_path = path / "stdout.log"
        returncode: int | None = None
        error: str | None = None
        try:
            with log_path.open("w", encoding="utf-8") as log:
                child = subprocess.Popen(  # noqa: S603 — fixed argv, no shell
                    cmd, stdout=log, stderr=subprocess.STDOUT, text=True, env=env
                )
                with self._lock:
                    self._children[cell.cell_id] = child
                try:
                    returncode = child.wait(timeout=CELL_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired:
                    _signal_tree(child, signal.SIGKILL)
                    returncode = child.wait()
                    error = f"timed out after {CELL_TIMEOUT_SECONDS} s"
        except OSError as exc:
            error = f"could not start: {exc}"
        finally:
            with self._lock:
                self._children.pop(cell.cell_id, None)
        result = read_json(path / "last_run.json") or {}
        if self._cancelled.is_set() and returncode not in (0,):
            status = CANCELLED
        elif returncode == 0 and not result.get("is_error"):
            status = OK
        else:
            status = FAILED
            error = error or result.get("error_message") or f"exit code {returncode}"
        self._update(
            cell.cell_id,
            status=status,
            finished_at=_now(),
            returncode=returncode,
            error=error,
            timings=cell_timings(path),
        )

    def cancel(self, *_: object) -> None:
        self._cancelled.set()
        with self._lock:
            children = list(self._children.values())
        for child in children:
            if child.poll() is None:
                _signal_tree(child, signal.SIGTERM)


def _signal_tree(child: subprocess.Popen[str], signum: int) -> None:
    """Signal a cell and its in-sample workers (found before the cell can exit)."""
    workers = descendant_pids(child.pid)
    with contextlib.suppress(OSError):
        child.send_signal(signum)
    for pid in workers:
        with contextlib.suppress(OSError):
            os.kill(pid, signum)


def _warn_tick_settings(cells: list[BatchCell]) -> None:
    flagged = sorted(
        {
            key
            for cell in cells
            for key in _TICK_SETTINGS
            if cell.env.get(key, "").strip().lower() in {"1", "true", "yes", "on"}
        }
    )
    if flagged:
        print(
            f"note: {', '.join(flagged)} on: tick events are orders of magnitude more than "
            "bars, expect cells to take far longer than bar-only runs",
            flush=True,
        )


def _cell_from_dict(payload: dict[str, Any]) -> BatchCell:
    return BatchCell(
        cell_id=str(payload["cell_id"]),
        robot=str(payload["robot"]),
        symbol=str(payload["symbol"]),
        instrument_id=str(payload["instrument_id"]),
        catalog=str(payload["catalog"]),
        interval=str(payload["interval"]),
        env={str(k): str(v) for k, v in (payload.get("env") or {}).items()},
        blocked=payload.get("blocked"),
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(description="Run one nautilus-lab batch backtest.")
    parser.add_argument("--batch-dir", required=True)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="continue an interrupted batch: keep finished cells, re-run the rest",
    )
    parser.add_argument(
        "--cpu-budget",
        type=int,
        default=None,
        help="cores the batch may keep busy (default: BATCH_CPU_BUDGET or all cores but one); "
        "each running cell gets cpu_budget // parallel in-sample workers",
    )
    parser.add_argument(
        "--profile",
        action="store_true",
        help="cProfile every cell into profile.pstats / profile.txt (grid runs serially)",
    )
    args = parser.parse_args(argv)
    if args.cpu_budget is not None and args.cpu_budget < 1:
        parser.error("--cpu-budget must be >= 1")
    path = Path(args.batch_dir)
    if args.resume:
        try:
            requeued = resume_batch_dir(path)
        except RuntimeError as exc:
            print(f"cannot resume: {exc}", file=sys.stderr)
            return 1
        if not requeued:
            print("nothing to resume: every cell has finished", file=sys.stderr)
            return 0
        print(f"resuming {len(requeued)} cell(s): {', '.join(requeued)}", file=sys.stderr)
    runner = BatchRun(path, cpu_budget=args.cpu_budget, profile=args.profile)

    def on_signal(_signum: int, _frame: FrameType | None) -> None:
        runner.cancel()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    return runner.run()


if __name__ == "__main__":
    raise SystemExit(main())
