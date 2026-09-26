import json
import logging
import re
import threading
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

#: `<key>_YYYY-MM-DD.jsonl` — the trailing date drives the retention policy.
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


class JsonlDecisionLogWriter(DecisionLogPort):
    """
    Writes DecisionRecords to JSONL files.

    Files are segmented by **session** id and date (`<session-id>_YYYY-MM-DD.jsonl`), so one
    session's decisions never mix with another session's — two sessions of the same robot on
    different symbols (hold-btc and hold-eth) would otherwise share one file. Records written
    without a session id (backtests, the CLI, tests) fall back to the robot name as the key,
    which is how files written before the session keying keep being readable.

    Implements a basic retention policy.
    """

    def __init__(self, settings: Settings, root: Path | None = None) -> None:
        self._enabled = settings.decision_log_enabled

        base_dir = Path(settings.decision_log_dir)
        if root is not None and not base_dir.is_absolute():
            self._dir = root / base_dir
        else:
            self._dir = base_dir

        self._retention_days = settings.decision_log_retention_days
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

    def _prune_old_logs(self) -> None:
        if self._retention_days <= 0:
            return

        now = datetime.now(UTC)
        for log_file in self._dir.glob("*.jsonl"):
            if not log_file.is_file():
                continue

            try:
                # Name format: <session-id>_YYYY-MM-DD.jsonl
                match = _LOG_NAME_RE.match(log_file.name)
                if match is None:
                    continue
                file_date = datetime.strptime(match.group("date"), "%Y-%m-%d").replace(tzinfo=UTC)
                age_days = (now - file_date).days
                if age_days > self._retention_days:
                    log_file.unlink()
                    logger.info(f"Pruned old decision log: {log_file.name}")
            except Exception as e:
                logger.warning(f"Failed to check/prune log file {log_file.name}: {e}")

    @staticmethod
    def _record_key(record: DecisionRecord) -> str:
        """Decision logs belong to a session; a record without one falls back to its robot."""
        return record.session_id or record.robot

    def log(self, record: DecisionRecord) -> None:
        if not self._enabled:
            return

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
    ) -> list[dict[str, Any]]:
        """Most recent records of one session (or robot), oldest first, optionally filtered.

        Rows written before `decision_trace/1` are upgraded on read (`outcome` =
        `UNKNOWN_V0`), so one reader serves old and new files.
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
