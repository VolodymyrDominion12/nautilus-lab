"""The dashboard's background jobs: one slot per kind, one child process each.

This used to be four module globals in `api/app.py` (`CURRENT_*_PROCESS`), a set of
reserved names and a lock, reachable from any endpoint and patched by tests. Holding it
in one object gives the app a single thing to own and a test a single thing to build
(docs/27 E-2.1/E-2.2).

Rules kept from the globals, each learned the hard way:

* A slot is claimed inside the request (`reserve`), not later by the background task.
  The "already running?" check used to look only at the process handle, which the task
  sets AFTER the response is sent: two quick clicks both passed, spawned two processes
  and truncated each other's log and result, and a poll right after launch saw
  "not running".
* A slot is released only when the work finished, whatever way it finished.
* `cancel` touches a process that exists and is alive; anything else is "idle".
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
import tempfile
import threading
from collections.abc import Callable
from datetime import UTC
from pathlib import Path
from typing import Any

from starlette.background import BackgroundTasks

JOB_LABELS: dict[str, str] = {
    "research": "Walk-forward / backtest",
    "ingest": "Binance klines ingest",
    "ml_train": "ML training",
    "paper": "Paper order log",
}

#: Runs a finished-when-it-returns thunk somewhere other than the request.
Schedule = Callable[[Callable[[], None]], None]


class JobManager:
    """Slots, process handles and start times of the jobs the dashboard launches."""

    def __init__(
        self,
        *,
        reports_dir: Path,
        python: str,
        schedule: Schedule | None = None,
        clock: Callable[[], datetime.datetime] = lambda: datetime.datetime.now(UTC),
    ) -> None:
        self.reports_dir = reports_dir
        self.python = python
        #: None = FastAPI background tasks (after the response). Tests pass a list's
        #: `append` to see what would run without spawning anything.
        self._schedule = schedule
        self._clock = clock
        self._lock = threading.Lock()
        self._processes: dict[str, subprocess.Popen[str] | None] = dict.fromkeys(JOB_LABELS)
        self._started: dict[str, datetime.datetime] = {}
        self._starting: set[str] = set()

    # ---- slots ----------------------------------------------------------------------
    def process(self, name: str) -> subprocess.Popen[str] | None:
        return self._processes[name]

    def active(self, name: str) -> bool:
        """Accepted and not finished: reserved, or its process is still alive."""
        process = self._processes[name]
        return name in self._starting or (process is not None and process.poll() is None)

    def reserve(self, name: str) -> bool:
        """Claim the slot atomically. False = another run of this job is active."""
        with self._lock:
            if self.active(name):
                return False
            self._starting.add(name)
            return True

    def release(self, name: str) -> None:
        with self._lock:
            self._starting.discard(name)

    @property
    def starting(self) -> frozenset[str]:
        return frozenset(self._starting)

    def submit(self, background: BackgroundTasks, name: str, work: Callable[[], None]) -> None:
        """Run `work` after the response; the reserved slot is released when it returns."""

        def run() -> None:
            try:
                work()
            finally:
                self.release(name)

        self._started[name] = self._clock()
        if self._schedule is not None:
            self._schedule(run)
        else:
            background.add_task(run)

    # ---- state for the dashboard ------------------------------------------------------
    def payload(self, name: str) -> dict[str, Any]:
        """One job's live state: running, when it started, and how long it has run."""
        running = self.active(name)
        started = self._started.get(name)
        elapsed = None
        if running and started is not None:
            elapsed = round((self._clock() - started).total_seconds(), 1)
        return {
            "running": running,
            "label": JOB_LABELS.get(name, name),
            "started_at": started.isoformat() if running and started else None,
            "elapsed_seconds": elapsed,
        }

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {name: self.payload(name) for name in JOB_LABELS}

    # ---- processes --------------------------------------------------------------------
    def cancel(self, name: str) -> bool:
        """Terminate (then kill) a live process. False = nothing was running."""
        process = self._processes[name]
        if process is None or process.poll() is not None:
            return False
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        return True

    def run_module(
        self,
        name: str,
        module: str,
        config: dict[str, Any],
        *,
        log_name: str,
        json_name: str,
        clear_outputs: bool = True,
    ) -> None:
        """`python -m <module> --config-json <tmp> --reports-dir <reports>`, output to the log.

        `clear_outputs=False` when the endpoint already cleared them inside the request,
        so a poll straight after launch never shows the previous run's result.
        """
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as handle:
            json.dump(config, handle)
            config_path = handle.name

        cmd = [
            self.python,
            "-m",
            module,
            "--config-json",
            config_path,
            "--reports-dir",
            str(self.reports_dir),
        ]
        log_path = self.reports_dir / log_name
        if clear_outputs:
            log_path.write_text("", encoding="utf-8")
            (self.reports_dir / json_name).unlink(missing_ok=True)

        try:
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            self._processes[name] = process
            assert process.stdout is not None
            extra_log = process.stdout.read()
            if extra_log.strip():
                with log_path.open("a", encoding="utf-8") as log_file:
                    log_file.write(extra_log)
            process.wait()
        finally:
            os.unlink(config_path)
            self._processes[name] = None

    def run_to_log(self, name: str, cmd: list[str], log_path: Path) -> int | None:
        """Run `cmd` with its output in `log_path`. Return code, or None if it never ran."""
        with log_path.open("w", encoding="utf-8") as log_file:
            log_file.write(f"Command: {' '.join(cmd)}\n")
            log_file.write(
                f"Started at: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            )
            log_file.flush()
            try:
                process = subprocess.Popen(
                    cmd, stdout=log_file, stderr=subprocess.STDOUT, text=True
                )
                self._processes[name] = process
                process.wait()
            except Exception as exc:
                log_file.write(f"\nException occurred: {exc!s}\n")
                return None
            log_file.write(f"\nProcess finished with code {process.returncode}\n")
            return process.returncode


def load_json_report(path: Path) -> dict[str, Any] | None:
    """A job's result file, or None when the job has not written one (yet)."""
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else None


def read_log(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""
