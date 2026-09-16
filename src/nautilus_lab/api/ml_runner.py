from __future__ import annotations

import io
import sys
import traceback
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, TextIO, cast

from nautilus_lab.application.train_formulaic import (
    build_formulaic_dataset,
    train_formulaic_lightgbm,
)
from nautilus_lab.application.train_meta_label import (
    build_meta_label_dataset,
    train_meta_label_lightgbm,
)
from nautilus_lab.domain.fees import FeeSchedule
from nautilus_lab.domain.triple_barrier import TripleBarrierConfig
from nautilus_lab.infrastructure.nautilus.parquet_catalog import NautilusParquetCatalog
from nautilus_lab.infrastructure.timeframe import nautilus_bar_type
from nautilus_lab.interfaces.composition import settings


@dataclass(frozen=True, slots=True)
class MLTrainConfig:
    model_type: str = "formulaic"
    catalog_path: str | None = None
    instrument_id: str | None = None
    bar_interval: str | None = None
    output_path: str | None = None
    folds: int = 5
    embargo: int = 10
    horizon: int = 5
    profit_multiple: str = "2"
    stop_multiple: str = "1"
    vol_window: int = 20


class _Tee(io.TextIOBase):
    def __init__(self, original: TextIO, buffer: io.StringIO) -> None:
        self._original = original
        self._buffer = buffer

    def write(self, text: str) -> int:
        self._original.write(text)
        self._buffer.write(text)
        return len(text)

    def flush(self) -> None:
        self._original.flush()


def execute_ml_train(job: MLTrainConfig) -> tuple[dict[str, Any], str]:
    buffer = io.StringIO()
    original = cast(TextIO, sys.stdout)
    sys.stdout = _Tee(original, buffer)
    cfg = settings()
    try:
        catalog_path = Path(job.catalog_path or cfg.catalog_path)
        instrument = job.instrument_id or cfg.instrument_id
        interval = job.bar_interval or cfg.bar_interval
        store = NautilusParquetCatalog(catalog_path, fees=FeeSchedule.binance_spot_vip0())
        bar_type = nautilus_bar_type(instrument, interval)
        bars = store.load(bar_type=bar_type)

        if job.model_type == "formulaic":
            output = Path(job.output_path or "models/formulaic_lgbm.txt")
            dataset = build_formulaic_dataset(bars, horizon=job.horizon)
            report = train_formulaic_lightgbm(
                dataset,
                output,
                n_splits=job.folds,
                embargo=job.embargo,
            )
            accuracy = "n/a" if report.accuracy is None else f"{float(report.accuracy) * 100:.2f}%"
            print(
                f"saved={report.model_path} rows={report.rows} folds={report.folds} "
                f"purged_cv_accuracy={accuracy}"
            )
            result = {
                "is_finished": True,
                "is_error": False,
                "model_type": "formulaic",
                "model_path": report.model_path,
                "rows": report.rows,
                "folds": report.folds,
                "accuracy": accuracy,
                "accuracy_raw": str(report.accuracy) if report.accuracy is not None else None,
            }
            return result, buffer.getvalue()

        if job.model_type == "meta_label":
            output = Path(job.output_path or "models/meta_label.txt")
            barrier = TripleBarrierConfig(
                profit_multiple=Decimal(job.profit_multiple),
                stop_multiple=Decimal(job.stop_multiple),
                horizon=job.horizon,
            )
            meta_dataset = build_meta_label_dataset(
                bars,
                instrument_id=instrument,
                barrier=barrier,
                volatility_window=job.vol_window,
            )
            meta_report = train_meta_label_lightgbm(
                meta_dataset,
                output,
                n_splits=job.folds,
                embargo=job.embargo,
            )
            accuracy = (
                "n/a"
                if meta_report.accuracy is None
                else f"{float(meta_report.accuracy) * 100:.2f}%"
            )
            tp_rate = (
                "n/a"
                if meta_report.take_profit_rate is None
                else f"{float(meta_report.take_profit_rate) * 100:.2f}%"
            )
            print(
                f"saved={meta_report.model_path} rows={meta_report.rows} folds={meta_report.folds} "
                f"purged_cv_accuracy={accuracy} take_profit_rate={tp_rate}"
            )
            result = {
                "is_finished": True,
                "is_error": False,
                "model_type": "meta_label",
                "model_path": meta_report.model_path,
                "rows": meta_report.rows,
                "folds": meta_report.folds,
                "accuracy": accuracy,
                "take_profit_rate": tp_rate,
            }
            return result, buffer.getvalue()

        msg = f"unknown model_type: {job.model_type}"
        raise ValueError(msg)
    except Exception as exc:
        traceback.print_exc()
        return (
            {
                "is_finished": True,
                "is_error": True,
                "model_type": job.model_type,
                "error_message": str(exc),
            },
            buffer.getvalue(),
        )
    finally:
        sys.stdout = original


def list_models(models_dir: Path | None = None) -> list[dict[str, Any]]:
    root = models_dir or Path("models")
    if not root.exists():
        return []
    models: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.txt"), key=lambda item: item.stat().st_mtime, reverse=True):
        stat = path.stat()
        models.append(
            {
                "filename": path.name,
                "path": str(path),
                "size_kb": round(stat.st_size / 1024, 1),
                "modified": stat.st_mtime,
            }
        )
    return models
