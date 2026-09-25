from __future__ import annotations

import io
import sys
import traceback
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, TextIO, cast

from nautilus_lab.api.catalog_service import resolve_catalog_path
from nautilus_lab.application.train_classifier import (
    describe_train_window,
    parse_optional_utc,
    require_exclusive_window,
)
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
    start: str | None = None
    end: str | None = None
    threshold: str = "0.55"


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


def _pct(value: Decimal | None) -> str:
    return "n/a" if value is None else f"{float(value) * 100:.2f}%"


def _flag(value: bool | None) -> str:
    return "n/a" if value is None else str(value).lower()


def execute_ml_train(job: MLTrainConfig) -> tuple[dict[str, Any], str]:
    buffer = io.StringIO()
    original = cast(TextIO, sys.stdout)
    sys.stdout = _Tee(original, buffer)
    cfg = settings()
    try:
        catalog_path = resolve_catalog_path(job.catalog_path)
        instrument = job.instrument_id or cfg.instrument_id
        interval = job.bar_interval or cfg.bar_interval
        store = NautilusParquetCatalog(catalog_path, fees=FeeSchedule.binance_spot_vip0())
        bar_type = nautilus_bar_type(instrument, interval)
        start = parse_optional_utc(job.start)
        end = parse_optional_utc(job.end)
        require_exclusive_window(start, end)
        window = describe_train_window(start=start, end=end)
        bars = store.load(bar_type=bar_type, start=start, end=end)

        if job.model_type == "formulaic":
            output = Path(job.output_path or "models/formulaic_lgbm.txt")
            dataset = build_formulaic_dataset(bars, horizon=job.horizon)
            report = train_formulaic_lightgbm(
                dataset,
                output,
                n_splits=job.folds,
                embargo=job.embargo,
                train_window=window,
            )
            accuracy = _pct(report.accuracy)
            majority = _pct(report.majority_rate)
            beats = _flag(report.beats_majority)
            print(
                f"saved={report.model_path} rows={report.rows} folds={report.folds} "
                f"purged_cv_accuracy={accuracy} majority_rate={majority} "
                f"beats_majority={beats} train_window={report.train_window}"
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
                "majority_rate": majority,
                "beats_majority": beats,
                "train_window": report.train_window,
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
                threshold=Decimal(job.threshold),
                train_window=window,
            )
            accuracy = _pct(meta_report.accuracy)
            tp_rate = _pct(meta_report.take_profit_rate)
            precision = _pct(meta_report.oof_precision)
            recall = _pct(meta_report.oof_recall)
            beats = _flag(meta_report.beats_always_take)
            print(
                f"saved={meta_report.model_path} rows={meta_report.rows} folds={meta_report.folds} "
                f"purged_cv_accuracy={accuracy} take_profit_rate={tp_rate} "
                f"oof_precision={precision} oof_recall={recall} beats_always_take={beats} "
                f"train_window={meta_report.train_window}"
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
                "oof_precision": precision,
                "oof_recall": recall,
                "beats_always_take": beats,
                "train_window": meta_report.train_window,
            }
            return result, buffer.getvalue()

        if job.model_type == "obi":
            from nautilus_lab.application.train_obi import (
                build_obi_dataset,
                train_obi_lightgbm,
            )
            from nautilus_lab.interfaces.composition import orderbook_catalog

            output = Path(job.output_path or "models/obi_lgbm.txt")
            store_books = orderbook_catalog(cfg, path=str(catalog_path))

            symbol = instrument.split(".")[0] if "." in instrument else instrument
            if "-" in symbol:
                symbol = symbol.replace("-", "")

            books = store_books.load(symbol=symbol, start=start, end=end)

            if not books:
                raise ValueError("No order books found in catalog for the requested window")

            obi_dataset = build_obi_dataset(
                books, horizon=job.horizon, threshold_bps=Decimal(job.threshold)
            )
            obi_report = train_obi_lightgbm(
                obi_dataset,
                output,
                n_splits=job.folds,
                embargo=job.embargo,
                train_window=window,
            )
            accuracy = _pct(obi_report.accuracy)
            majority = _pct(obi_report.majority_rate)
            beats = _flag(obi_report.beats_majority)
            print(
                f"saved={obi_report.model_path} rows={obi_report.rows} "
                f"folds={obi_report.folds} purged_cv_accuracy={accuracy} "
                f"majority_rate={majority} beats_majority={beats} "
                f"train_window={obi_report.train_window}"
            )
            result = {
                "is_finished": True,
                "is_error": False,
                "model_type": "obi",
                "model_path": obi_report.model_path,
                "rows": obi_report.rows,
                "folds": obi_report.folds,
                "accuracy": accuracy,
                "accuracy_raw": (
                    str(obi_report.accuracy) if obi_report.accuracy is not None else None
                ),
                "majority_rate": majority,
                "beats_majority": beats,
                "train_window": obi_report.train_window,
            }
            return result, buffer.getvalue()

        msg = f"unknown model_type: {job.model_type}"
        raise ValueError(msg)
    except Exception as exc:  # noqa: BLE001 — job boundary: the error goes into the result file
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
