from __future__ import annotations

import io
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime
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
from nautilus_lab.domain.model_card import ModelCard
from nautilus_lab.domain.triple_barrier import TripleBarrierConfig
from nautilus_lab.infrastructure.model_card_store import (
    JsonModelCardSource,
    file_sha256,
    write_model_card,
)
from nautilus_lab.infrastructure.nautilus.parquet_catalog import NautilusParquetCatalog
from nautilus_lab.infrastructure.settings import Settings
from nautilus_lab.infrastructure.timeframe import nautilus_bar_type
from nautilus_lab.interfaces.composition import settings


@dataclass(frozen=True, slots=True)
class MLTrainConfig:
    model_type: str = "formulaic"
    model_types: tuple[str, ...] | None = None
    catalog_path: str | None = None
    instrument_id: str | None = None
    instruments: tuple[str, ...] | None = None
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


def _write_card(
    model_path: str,
    *,
    robot: str,
    instrument_id: str,
    bar_type: str | None,
    first_ts: datetime,
    last_ts: datetime,
    horizon: int,
    rows: int,
) -> str:
    """Record what the booster saw, so research runs can refuse a leaking model (A1/A2)."""
    sha = file_sha256(model_path)
    if sha is None:
        raise FileNotFoundError(f"trained model was not written: {model_path}")
    card = ModelCard(
        robot=robot,
        instrument_id=instrument_id,
        bar_type=bar_type,
        train_first_ts=first_ts,
        train_last_ts=last_ts,
        horizon=horizon,
        rows=rows,
        model_sha256=sha,
    )
    return str(write_model_card(model_path, card))


def _train_single(
    job: MLTrainConfig,
    instrument: str,
    model_type: str,
    output_path: Path,
    cfg: Settings,
    catalog_path: Path,
    start: datetime | None,
    end: datetime | None,
    window: str,
) -> dict[str, Any]:
    store = NautilusParquetCatalog(catalog_path, spot_fees=FeeSchedule.binance_spot_vip0())
    interval = job.bar_interval or cfg.bar_interval
    bar_type = nautilus_bar_type(instrument, interval)
    bars = store.load(bar_type=bar_type, start=start, end=end)
    if model_type != "obi" and not bars:
        raise ValueError(f"no bars in catalog for {bar_type} in the requested window")

    if model_type == "formulaic":
        dataset = build_formulaic_dataset(bars, horizon=job.horizon)
        report = train_formulaic_lightgbm(
            dataset,
            output_path,
            n_splits=job.folds,
            embargo=job.embargo,
            train_window=window,
        )
        card = _write_card(
            report.model_path,
            robot="formulaic_lgbm",
            instrument_id=instrument,
            bar_type=bar_type,
            first_ts=bars[0].ts_utc,
            last_ts=bars[-1].ts_utc,
            horizon=job.horizon,
            rows=report.rows,
        )
        accuracy = _pct(report.accuracy)
        majority = _pct(report.majority_rate)
        beats = _flag(report.beats_majority)
        print(
            f"saved={report.model_path} card={card} rows={report.rows} folds={report.folds} "
            f"purged_cv_accuracy={accuracy} majority_rate={majority} "
            f"beats_majority={beats} train_window={report.train_window}"
        )
        return {
            "is_finished": True,
            "is_error": False,
            "model_type": "formulaic",
            "instrument": instrument,
            "model_path": report.model_path,
            "rows": report.rows,
            "folds": report.folds,
            "accuracy": accuracy,
            "accuracy_raw": str(report.accuracy) if report.accuracy is not None else None,
            "majority_rate": majority,
            "beats_majority": beats,
            "train_window": report.train_window,
        }

    if model_type == "meta_label":
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
            output_path,
            n_splits=job.folds,
            embargo=job.embargo,
            threshold=Decimal(job.threshold),
            train_window=window,
        )
        card = _write_card(
            meta_report.model_path,
            robot="meta_label",
            instrument_id=instrument,
            bar_type=bar_type,
            first_ts=bars[0].ts_utc,
            last_ts=bars[-1].ts_utc,
            horizon=job.horizon,
            rows=meta_report.rows,
        )
        print(f"card={card}")
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
        return {
            "is_finished": True,
            "is_error": False,
            "model_type": "meta_label",
            "instrument": instrument,
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

    if model_type == "obi":
        from nautilus_lab.application.train_obi import (
            build_obi_dataset,
            obi_book_symbol,
            train_obi_lightgbm,
        )
        from nautilus_lab.interfaces.composition import orderbook_catalog

        store_books = orderbook_catalog(cfg, path=str(catalog_path))
        symbol = obi_book_symbol(instrument)
        books = store_books.load(symbol=symbol, start=start, end=end)
        if not books:
            msg = f"No order books found in catalog for {symbol} in the requested window"
            raise ValueError(msg)

        obi_dataset = build_obi_dataset(
            books, horizon=job.horizon, threshold_bps=Decimal(job.threshold)
        )
        obi_report = train_obi_lightgbm(
            obi_dataset,
            output_path,
            n_splits=job.folds,
            embargo=job.embargo,
            train_window=window,
        )
        card = _write_card(
            obi_report.model_path,
            robot="ml_obi",
            instrument_id=instrument,
            bar_type=None,
            first_ts=min(book.ts_utc for book in books),
            last_ts=max(book.ts_utc for book in books),
            horizon=job.horizon,
            rows=obi_report.rows,
        )
        print(f"card={card}")
        accuracy = _pct(obi_report.accuracy)
        majority = _pct(obi_report.majority_rate)
        beats = _flag(obi_report.beats_majority)
        print(
            f"saved={obi_report.model_path} rows={obi_report.rows} "
            f"folds={obi_report.folds} purged_cv_accuracy={accuracy} "
            f"majority_rate={majority} beats_majority={beats} "
            f"train_window={obi_report.train_window}"
        )
        return {
            "is_finished": True,
            "is_error": False,
            "model_type": "obi",
            "instrument": instrument,
            "model_path": obi_report.model_path,
            "rows": obi_report.rows,
            "folds": obi_report.folds,
            "accuracy": accuracy,
            "accuracy_raw": (str(obi_report.accuracy) if obi_report.accuracy is not None else None),
            "majority_rate": majority,
            "beats_majority": beats,
            "train_window": obi_report.train_window,
        }

    msg = f"unknown model_type: {model_type}"
    raise ValueError(msg)


def execute_ml_train(job: MLTrainConfig) -> tuple[dict[str, Any], str]:
    buffer = io.StringIO()
    original = cast(TextIO, sys.stdout)
    sys.stdout = _Tee(original, buffer)
    cfg = settings()
    try:
        catalog_path = resolve_catalog_path(job.catalog_path)
        start = parse_optional_utc(job.start)
        end = parse_optional_utc(job.end)
        require_exclusive_window(start, end)
        window = describe_train_window(start=start, end=end)

        model_list = list(job.model_types) if job.model_types else [job.model_type]
        instruments_list = (
            list(job.instruments) if job.instruments else [job.instrument_id or cfg.instrument_id]
        )

        total_tasks = len(model_list) * len(instruments_list)
        is_batch = total_tasks > 1

        if not is_batch:
            m = model_list[0]
            inst = instruments_list[0]
            if m == "obi":
                default_name = "obi_lgbm"
            elif m == "meta_label":
                default_name = "meta_label"
            else:
                default_name = "formulaic_lgbm"
            out_file = Path(job.output_path or f"models/{default_name}.txt")
            result = _train_single(
                job,
                instrument=inst,
                model_type=m,
                output_path=out_file,
                cfg=cfg,
                catalog_path=catalog_path,
                start=start,
                end=end,
                window=window,
            )
            return result, buffer.getvalue()

        # Batch execution
        print(
            f"=== Starting ML Batch Training: {len(model_list)} model(s) x "
            f"{len(instruments_list)} instrument(s) ({total_tasks} total tasks) ==="
        )
        runs: list[dict[str, Any]] = []
        task_idx = 1
        succeeded = 0

        for m in model_list:
            for inst in instruments_list:
                clean_sym = (
                    inst.replace("/", "")
                    .replace(".SIM", "")
                    .replace(".BINANCE", "")
                    .replace("-", "_")
                )
                sub_out = Path(f"models/{m}_{clean_sym}.txt")
                print(f"\n[{task_idx}/{total_tasks}] Training {m} on {inst} -> {sub_out} ...")
                try:
                    res = _train_single(
                        job,
                        instrument=inst,
                        model_type=m,
                        output_path=sub_out,
                        cfg=cfg,
                        catalog_path=catalog_path,
                        start=start,
                        end=end,
                        window=window,
                    )
                    runs.append(res)
                    succeeded += 1
                except Exception as exc:  # noqa: BLE001
                    print(f"[{task_idx}/{total_tasks}] ERROR training {m} on {inst}: {exc}")
                    runs.append(
                        {
                            "is_finished": True,
                            "is_error": True,
                            "model_type": m,
                            "instrument": inst,
                            "error_message": str(exc),
                        }
                    )
                task_idx += 1

        print(f"\n=== Batch ML Training Completed: {succeeded}/{total_tasks} successful ===")
        result = {
            "is_finished": True,
            "is_error": succeeded == 0 and total_tasks > 0,
            "model_type": "batch",
            "total_tasks": total_tasks,
            "succeeded": succeeded,
            "accuracy": f"{succeeded}/{total_tasks} ok",
            "runs": runs,
            "rows": sum(int(r.get("rows") or 0) for r in runs if not r.get("is_error")),
        }
        return result, buffer.getvalue()

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
    card_source = JsonModelCardSource()
    seen: set[str] = set()

    for path in sorted(root.rglob("*.txt"), key=lambda item: item.stat().st_mtime, reverse=True):
        rel = str(path)
        if rel in seen:
            continue
        seen.add(rel)
        stat = path.stat()
        item: dict[str, Any] = {
            "filename": path.name,
            "path": rel,
            "size_kb": round(stat.st_size / 1024, 1),
            "modified": stat.st_mtime,
        }
        card = card_source.card_for(rel)
        if card:
            item["instrument_id"] = card.instrument_id
            item["robot"] = card.robot
            item["bar_type"] = card.bar_type
            item["rows"] = card.rows
            item["horizon"] = card.horizon
            item["train_first_ts"] = card.train_first_ts.isoformat()
            item["train_last_ts"] = card.train_last_ts.isoformat()
        models.append(item)
    return models
