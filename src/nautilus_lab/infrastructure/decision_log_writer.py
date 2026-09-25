import json
import logging
import threading
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from nautilus_lab.domain.decision_log import DecisionRecord
from nautilus_lab.domain.ports import DecisionLogPort
from nautilus_lab.infrastructure.settings import Settings

logger = logging.getLogger(__name__)

class DecimalEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, Decimal):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        return super().default(o)


class JsonlDecisionLogWriter(DecisionLogPort):
    """
    Writes DecisionRecords to JSONL files.
    Files are segmented by robot name and date.
    Implements a basic retention policy.
    """

    def __init__(self, settings: Settings, root: Path | None = None):
        self._enabled = settings.decision_log_enabled
        
        base_dir = Path(settings.decision_log_dir)
        if root is not None and not base_dir.is_absolute():
            self._dir = root / base_dir
        else:
            self._dir = base_dir
            
        self._retention_days = settings.decision_log_retention_days
        self._lock = threading.Lock()
        
        if self._enabled:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._prune_old_logs()

    def _get_log_file_path(self, robot_name: str, ts_utc: datetime) -> Path:
        date_str = ts_utc.strftime("%Y-%m-%d")
        safe_robot_name = robot_name.replace("/", "_")
        filename = f"{safe_robot_name}_{date_str}.jsonl"
        return self._dir / filename

    def _prune_old_logs(self) -> None:
        if self._retention_days <= 0:
            return
            
        now = datetime.now(timezone.utc)
        for log_file in self._dir.glob("*.jsonl"):
            if not log_file.is_file():
                continue
            
            try:
                # Name format: robot_name_YYYY-MM-DD.jsonl
                stem = log_file.stem
                parts = stem.split("_")
                if len(parts) >= 2:
                    date_str = parts[-1]
                    file_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    age_days = (now - file_date).days
                    if age_days > self._retention_days:
                        log_file.unlink()
                        logger.info(f"Pruned old decision log: {log_file.name}")
            except Exception as e:
                logger.warning(f"Failed to check/prune log file {log_file.name}: {e}")

    def log(self, record: DecisionRecord) -> None:
        if not self._enabled:
            return
            
        path = self._get_log_file_path(record.robot, record.bar_end_utc)
        
        data = {
            "ts": record.bar_end_utc.isoformat(),
            "robot": record.robot,
            "instrument": record.instrument_id,
            "close": record.close_price,
            "regime": record.regime,
            "signal": record.signal,
            "signal_reason": record.signal_reason,
            "indicators": record.indicators,
            "states": record.states,
        }
        
        try:
            with self._lock:
                with path.open("a", encoding="utf-8") as f:
                    line = json.dumps(data, cls=DecimalEncoder)
                    f.write(line + "\n")
        except Exception as e:
            logger.error(f"Failed to write decision log to {path}: {e}")

class NullDecisionLogWriter(DecisionLogPort):
    def log(self, record: DecisionRecord) -> None:
        pass
