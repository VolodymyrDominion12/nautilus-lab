import json
import logging
import re
import threading
import time
from collections.abc import Collection, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from nautilus_lab.application.decision_trace_codec import record_to_dict, upgrade_row
from nautilus_lab.domain.decision_log import DecisionRecord
from nautilus_lab.domain.ports import DecisionLogPort
from nautilus_lab.infrastructure.settings import Settings

logger = logging.getLogger(__name__)

#: `<key>_YYYY-MM-DD.jsonl` — the date is the bar's, which is not when the file was written.
_LOG_NAME_RE = re.compile(r"^(?P<key>.+)_(?P<date>\d{4}-\d{2}-\d{2})\.jsonl$")
_UNSAFE_KEY_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_key(raw: str) -> str:
    """A file-name-safe key that cannot escape the log directory.

    Session ids are `f"{name}-{uuid}"` and the name comes from an API caller, so it is
    untrusted text: separators, `..`, spaces and unicode all become `_`.
    """
    key = _UNSAFE_KEY_RE.sub("_", raw).strip("._-")
    return key or "unknown"


def _row_ts(row: dict[str, Any]) -> datetime | None:
    raw = row.get("ts")
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


class DecimalEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:  # noqa: ANN401
        if isinstance(o, Decimal):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        return super().default(o)


def prune_decision_logs(
    log_dir: Path,
    *,
    retention_days: int = 7,
    max_mb: int = 500,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Prune decision logs by age and total size quota.

    Args:
        log_dir: Directory containing *.jsonl decision files.
        retention_days: Files older than this (by mtime / write time) are deleted. 0 = keep forever.
        max_mb: Maximum total directory size in megabytes. 0 = unlimited.
        dry_run: If True, do not unlink files, only calculate what would be deleted.

    Returns:
        tuple[pruned_files_count, pruned_bytes]
    """
    if not log_dir.is_dir():
        return 0, 0

    pruned_files = 0
    pruned_bytes = 0

    remaining: list[tuple[float, int, Path]] = []
    cutoff = datetime.now(UTC).timestamp() - retention_days * 86400 if retention_days > 0 else None

    # Phase 1: Prune by age (based on physical write time / st_mtime)
    for log_file in log_dir.glob("*.jsonl"):
        if not log_file.is_file():
            continue
        try:
            stat = log_file.stat()
            if cutoff is not None and stat.st_mtime <= cutoff:
                pruned_files += 1
                pruned_bytes += stat.st_size
                if not dry_run:
                    log_file.unlink()
                logger.info(
                    "Pruned old decision log (age > %dd): %s (%d bytes)",
                    retention_days,
                    log_file.name,
                    stat.st_size,
                )
            else:
                remaining.append((stat.st_mtime, stat.st_size, log_file))
        except OSError as e:
            logger.warning("Failed to check/prune log file %s: %s", log_file.name, e)

    # Phase 2: Prune by size quota (LRU: oldest files deleted first)
    if max_mb > 0:
        max_bytes = max_mb * 1024 * 1024
        total_bytes = sum(size for _, size, _ in remaining)
        if total_bytes > max_bytes:
            remaining.sort(key=lambda item: item[0])
            for _, size, log_file in remaining:
                if total_bytes <= max_bytes:
                    break
                try:
                    if not dry_run:
                        log_file.unlink()
                    total_bytes -= size
                    pruned_files += 1
                    pruned_bytes += size
                    logger.info(
                        "Pruned decision log to free space (quota %d MB): %s (%d bytes)",
                        max_mb,
                        log_file.name,
                        size,
                    )
                except OSError as e:
                    logger.warning("Failed to prune log file %s: %s", log_file.name, e)

    return pruned_files, pruned_bytes


class JsonlDecisionLogWriter(DecisionLogPort):
    """
    Writes DecisionRecords to JSONL files.

    Files are segmented by **session** id and date (`<session-id>_YYYY-MM-DD.jsonl`), so one
    session's decisions never mix with another session's — two sessions of the same robot on
    different symbols (hold-btc and hold-eth) would otherwise share one file. Records written
    without a session id (backtests, the CLI, tests) fall back to the robot name as the key,
    which is how files written before the session keying keep being readable.

    Implements a dual-threshold retention policy: files older than `DECISION_LOG_RETENTION_DAYS`
    are deleted, and if directory exceeds `DECISION_LOG_MAX_MB`, oldest files are pruned (LRU).
    Pruning runs on initialization and periodically in runtime during long-running sessions.
    """

    def __init__(self, settings: Settings, root: Path | None = None) -> None:
        self._enabled = settings.decision_log_enabled

        base_dir = Path(settings.decision_log_dir)
        if root is not None and not base_dir.is_absolute():
            self._dir = root / base_dir
        else:
            self._dir = base_dir

        self._retention_days = settings.decision_log_retention_days
        self._max_mb = settings.decision_log_max_mb
        self._prune_interval_seconds = settings.decision_log_prune_interval_seconds
        self._last_prune_time = time.monotonic()
        self._lock = threading.Lock()

        if self._enabled:
            try:
                self._dir.mkdir(parents=True, exist_ok=True)
                self._prune_old_logs()
            except OSError as err:
                fallback_base = Path("data/paper/decisions")
                fallback_dir = (
                    root / fallback_base
                    if (root is not None and not fallback_base.is_absolute())
                    else fallback_base
                )
                if self._dir != fallback_dir:
                    logger.warning(
                        "Decision log directory %s is not writable (%s). "
                        "Falling back to %s (data/ volume).",
                        self._dir,
                        err,
                        fallback_dir,
                    )
                    try:
                        self._dir = fallback_dir
                        self._dir.mkdir(parents=True, exist_ok=True)
                        self._prune_old_logs()
                    except OSError as fallback_err:
                        logger.error(
                            "Failed to initialize decision log fallback directory %s: %s. "
                            "Disabling decision logging.",
                            fallback_dir,
                            fallback_err,
                        )
                        self._enabled = False
                else:
                    logger.error(
                        "Failed to initialize decision log directory %s: %s. "
                        "Disabling decision logging.",
                        self._dir,
                        err,
                    )
                    self._enabled = False

    def _get_log_file_path(self, key: str, ts_utc: datetime) -> Path:
        date_str = ts_utc.strftime("%Y-%m-%d")
        return self._dir / f"{_safe_key(key)}_{date_str}.jsonl"

    def prune(self) -> tuple[int, int]:
        """Trigger retention sweep manually. Returns (pruned_files_count, pruned_bytes)."""
        with self._lock:
            return self._prune_old_logs()

    def _prune_old_logs(self) -> tuple[int, int]:
        """Delete logs nobody may want any more, aged by when they were **written**,

        and prune oldest files if total directory size exceeds max_mb quota.
        """
        return prune_decision_logs(
            self._dir,
            retention_days=self._retention_days,
            max_mb=self._max_mb,
            dry_run=False,
        )

    @staticmethod
    def _record_key(record: DecisionRecord) -> str:
        """Decision logs belong to a session; a record without one falls back to its robot."""
        return record.session_id or record.robot

    def log(self, record: DecisionRecord) -> None:
        if not self._enabled:
            return

        now = time.monotonic()
        if (
            self._prune_interval_seconds > 0
            and (now - self._last_prune_time) >= self._prune_interval_seconds
        ):
            with self._lock:
                if (now - self._last_prune_time) >= self._prune_interval_seconds:
                    self._last_prune_time = now
                    self._prune_old_logs()

        path = self._get_log_file_path(self._record_key(record), record.bar_end_utc)
        data = record_to_dict(record)

        try:
            with self._lock, path.open("a", encoding="utf-8") as f:
                line = json.dumps(data, cls=DecimalEncoder, ensure_ascii=False)
                f.write(line + "\n")
        except Exception as e:
            logger.error(f"Failed to write decision log to {path}: {e}")

    def get_recent_logs(
        self,
        session_id: str,
        lines: int = 100,
        *,
        outcomes: Collection[str] | None = None,
        kind: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        regime: str | None = None,
        signal: str | None = None,
    ) -> list[dict[str, Any]]:
        """Most recent records of one session (or robot), oldest first, optionally filtered.

        Rows written before `decision_trace/1` are upgraded on read (`outcome` =
        `UNKNOWN_V0`), so one reader serves old and new files. `regime`/`signal` are
        top-level fields of `bar_decision` rows; `intrabar` rows carry neither, so a
        regime or signal filter drops them (they are not a match, not an error).
        """
        if not self._enabled:
            return []
        wanted = {item.upper() for item in outcomes} if outcomes else None
        results: list[dict[str, Any]] = []
        for row in self._iter_newest_first(session_id, since=since):
            if wanted is not None and str(row.get("outcome", "")).upper() not in wanted:
                continue
            if kind is not None and row.get("kind") != kind:
                continue
            if regime is not None and str(row.get("regime", "")).lower() != regime.lower():
                continue
            if signal is not None and str(row.get("signal", "")).lower() != signal.lower():
                continue
            ts = _row_ts(row)
            if since is not None and (ts is None or ts < since):
                continue
            if until is not None and (ts is None or ts > until):
                continue
            results.append(row)
            if len(results) >= lines:
                break
        results.reverse()
        return results

    def read_range(
        self,
        session_id: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 20000,
    ) -> list[dict[str, Any]]:
        """Every record of a session in [since, until], oldest first (for digests)."""
        return self.get_recent_logs(session_id, lines=limit, since=since, until=until)

    def _iter_newest_first(
        self, session_id: str, *, since: datetime | None = None
    ) -> Iterator[dict[str, Any]]:
        log_files = sorted(self._dir.glob(f"{_safe_key(session_id)}_*.jsonl"), reverse=True)
        for log_file in log_files:
            match = _LOG_NAME_RE.match(log_file.name)
            if since is not None and match is not None:
                file_day = datetime.strptime(match.group("date"), "%Y-%m-%d").replace(tzinfo=UTC)
                if file_day.date() < since.astimezone(UTC).date():
                    return
            try:
                file_lines = log_file.read_text(encoding="utf-8").splitlines()
            except OSError as e:
                logger.warning(f"Failed to read decision log {log_file}: {e}")
                continue
            for line in reversed(file_lines):
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(raw, dict):
                    yield upgrade_row(raw)

    def append(self, record: DecisionRecord) -> None:
        self.log(record)


class NullDecisionLogWriter(DecisionLogPort):
    def log(self, record: DecisionRecord) -> None:
        pass

    def append(self, record: DecisionRecord) -> None:
        pass

    def prune(self) -> tuple[int, int]:
        return 0, 0
