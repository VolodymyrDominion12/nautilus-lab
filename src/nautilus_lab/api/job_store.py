"""What the API knows about its jobs, kept across restarts (docs/27 E-2.2).

A job handle used to live only in the API process. After a restart (deploy, crash,
`--reload`) the dashboard said "idle" while an ingest was still writing the catalog, a
second ingest could be started on top of it, and a run that died with the API looked
like one that never started. One SQLite row per job kind fixes both: the new process
reads what was running, adopts a child that is still alive, and records a lost one as
lost instead of forgetting it.

SQLite, not a JSON file: several threads write (every background job reports its own
start and end), and a half-written file after a kill would lose exactly the record this
exists to keep.
"""

from __future__ import annotations

import contextlib
import os
import signal
import sqlite3
import subprocess
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path

RUNNING = "running"
FINISHED = "finished"
#: The API restarted and the process was gone: its result, if any, is only in the log.
LOST = "lost"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    name TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    pid INTEGER,
    command TEXT NOT NULL DEFAULT '',
    started_at TEXT,
    finished_at TEXT,
    returncode INTEGER
)
"""


@dataclass(frozen=True, slots=True)
class JobRecord:
    name: str
    status: str
    pid: int | None
    command: str
    started_at: str | None
    finished_at: str | None
    returncode: int | None


class JobStore:
    """One row per job kind: the last run, what it was, and how it ended."""

    def __init__(self, path: Path) -> None:
        self.path = path
        # Created on first use, not here: importing the app must not write to disk.
        self._ready = False

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        if not self._ready:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        # A connection per call: background jobs report from their own threads.
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            if not self._ready:
                db.execute(_SCHEMA)
                self._ready = True
            yield db

    def started(self, name: str, *, pid: int, command: list[str], started_at: str) -> None:
        with self._db() as db:
            db.execute(
                "INSERT INTO jobs (name, status, pid, command, started_at, finished_at, "
                "returncode) VALUES (?, ?, ?, ?, ?, NULL, NULL) "
                "ON CONFLICT(name) DO UPDATE SET status=excluded.status, pid=excluded.pid, "
                "command=excluded.command, started_at=excluded.started_at, "
                "finished_at=NULL, returncode=NULL",
                (name, RUNNING, pid, " ".join(command), started_at),
            )

    def finished(
        self, name: str, *, returncode: int | None, finished_at: str, status: str = FINISHED
    ) -> None:
        with self._db() as db:
            db.execute(
                "UPDATE jobs SET status=?, returncode=?, finished_at=? WHERE name=?",
                (status, returncode, finished_at, name),
            )

    def get(self, name: str) -> JobRecord | None:
        with self._db() as db:
            row = db.execute(
                "SELECT name, status, pid, command, started_at, finished_at, returncode "
                "FROM jobs WHERE name=?",
                (name,),
            ).fetchone()
        return None if row is None else JobRecord(*row)

    def running(self) -> list[JobRecord]:
        with self._db() as db:
            rows = db.execute(
                "SELECT name, status, pid, command, started_at, finished_at, returncode "
                "FROM jobs WHERE status=?",
                (RUNNING,),
            ).fetchall()
        return [JobRecord(*row) for row in rows]


def process_command(pid: int) -> str | None:
    """The live command line of `pid`, or None when it is gone (or a zombie)."""
    proc = Path("/proc") / str(pid)
    try:
        state = (proc / "stat").read_text(encoding="utf-8", errors="replace")
        # Field 3, after the parenthesised name (which may itself contain spaces).
        if state[state.rindex(")") + 2 :].startswith("Z"):
            return None
        raw = (proc / "cmdline").read_bytes()
    except (OSError, ValueError):
        return _command_without_proc(pid)
    return raw.replace(b"\0", b" ").decode("utf-8", errors="replace").strip()


def _command_without_proc(pid: int) -> str | None:
    """No /proc (macOS workstation): alive or not, but the command cannot be checked."""
    if Path("/proc/self").exists():
        return None  # /proc exists, so the pid is simply gone
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        return ""
    return ""


class AdoptedProcess:
    """A job child started by an earlier API process: not ours to `wait()` on.

    Enough of `subprocess.Popen` for `JobManager`: poll, terminate, kill, wait. The exit
    code of a process we did not start is not knowable, so a finished one reports -1.
    """

    UNKNOWN_EXIT = -1

    def __init__(self, pid: int, command: str) -> None:
        self.pid = pid
        self.command = command
        self.returncode: int | None = None

    def poll(self) -> int | None:
        if self.returncode is None and not self._same_process():
            self.returncode = self.UNKNOWN_EXIT
        return self.returncode

    def _same_process(self) -> bool:
        live = process_command(self.pid)
        # "" = alive where the command cannot be read (no /proc): trust the pid.
        return live is not None and (live == "" or live == self.command)

    def terminate(self) -> None:
        self._signal(signal.SIGTERM)

    def kill(self) -> None:
        self._signal(signal.SIGKILL)

    def _signal(self, sig: int) -> None:
        # Only signal the process we recorded: a reused pid belongs to someone else.
        if self._same_process():
            with contextlib.suppress(ProcessLookupError):
                os.kill(self.pid, sig)

    def wait(self, timeout: float | None = None) -> int:
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.poll() is None:
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(self.command, timeout or 0)
            time.sleep(0.05)
        return self.UNKNOWN_EXIT if self.returncode is None else self.returncode
