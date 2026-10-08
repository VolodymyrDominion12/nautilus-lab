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
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
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
    decisions_dir,
    read_json,
    request_from_dict,
    resume_batch_dir,
    write_json,
)
from nautilus_lab.application.batch_plan import BatchCell, research_job_config

#: A cell that runs longer than this is stopped (a 1h regime walk-forward takes ~15 min).
CELL_TIMEOUT_SECONDS = 4 * 3600


class BatchRun:
    def __init__(self, batch_path: Path, *, python: str = sys.executable) -> None:
        self.path = batch_path
        self.python = python
        self._lock = threading.Lock()
        self._children: dict[str, subprocess.Popen[str]] = {}
        self._cancelled = threading.Event()

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
        self._update(status=RUNNING, pid=os.getpid(), started_at=_now())
        cells = [_cell_from_dict(cell) for cell in batch["cells"] if cell.get("status") == QUEUED]
        with ThreadPoolExecutor(max_workers=request.parallel) as pool:
            list(pool.map(lambda cell: self._run_cell(request, cell), cells))
        final = CANCELLED if self._cancelled.is_set() else OK
        self._update(status=final, finished_at=_now(), pid=None)
        return 0

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
                    child.kill()
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
        )

    def cancel(self, *_: object) -> None:
        self._cancelled.set()
        with self._lock:
            children = list(self._children.values())
        for child in children:
            if child.poll() is None:
                child.terminate()


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
    args = parser.parse_args(argv)
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
    runner = BatchRun(path)

    def on_signal(_signum: int, _frame: FrameType | None) -> None:
        runner.cancel()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    return runner.run()


if __name__ == "__main__":
    raise SystemExit(main())
