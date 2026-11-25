"""Databento DBN ingest adapter for CME/COMEX gold futures (Phase G3, Track B).

Critical invariants:
1. `bars_timestamp_on_close=True` is mandatory whenever decoding DBN OHLCV bars so open-stamped
   Databento records cannot introduce look-ahead bias inside Nautilus `BacktestEngine`.
2. Quality checks use `trading_calendar_for_instrument(instrument_id)` (CME Globex 23x5 vs
   CME 1OZ 24/7) and isolate declared or detected contract roll boundaries in continuous series.
3. Optional online downloads require `DATABENTO_API_KEY` from `.env` and never log the secret.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from nautilus_trader.adapters.databento.loaders import DatabentoDataLoader
from nautilus_trader.model.data import Bar
from nautilus_trader.model.identifiers import InstrumentId

from nautilus_lab.application.ingest_archive import INTERVALS
from nautilus_lab.application.risk import require_simulated_mode
from nautilus_lab.domain.bars import OhlcvBar, validate_bar
from nautilus_lab.domain.calendar import trading_calendar_for_instrument
from nautilus_lab.domain.data_quality import QualityReport, QualityStatus, RollBoundary, check_bars
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.infrastructure.archive_source import JsonQualityStore
from nautilus_lab.infrastructure.nautilus.instrument import resolve_instrument
from nautilus_lab.infrastructure.nautilus.parquet_catalog import NautilusParquetCatalog
from nautilus_lab.infrastructure.timeframe import interval_from_bar_type, nautilus_bar_type

SCHEMA_TO_INTERVAL: dict[str, str] = {
    "ohlcv-1m": "1m",
    "ohlcv-5m": "5m",
    "ohlcv-15m": "15m",
    "ohlcv-1h": "1h",
    "ohlcv-4h": "4h",
    "ohlcv-1d": "1d",
}

_ONE_DIGIT_YEAR_RE = re.compile(r"^(MGC|GC|1OZ)([FGHJKMNQUVXZ])(\d)\.(XCEC|GLBX)$")


class DbnLoader(Protocol):
    """Subset of `DatabentoDataLoader` used by `load_dbn_bars` (injectable for tests)."""

    def from_dbn_file(
        self,
        path: os.PathLike[str] | str,
        instrument_id: InstrumentId | None = None,
        price_precision: int | None = None,
        as_legacy_cython: bool = True,
        include_trades: bool = False,
        use_exchange_as_venue: bool = False,
        bars_timestamp_on_close: bool = True,
        skip_on_error: bool = False,
        expiration_overrides: dict[str, dict[str, str]] | None = None,
    ) -> list[Any]: ...


@dataclass(frozen=True, slots=True)
class DatabentoIngestReport:
    instrument_id: str
    bar_type: str
    interval: str
    rows_written: int
    first_ts: datetime | None
    last_ts: datetime | None
    quality: QualityStatus
    roll_dates: tuple[RollBoundary, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)

    def summary_line(self) -> str:
        first = self.first_ts.isoformat() if self.first_ts else "-"
        last = self.last_ts.isoformat() if self.last_ts else "-"
        parts = [
            f"instrument={self.instrument_id}",
            f"interval={self.interval}",
            f"rows={self.rows_written}",
            f"rolls={len(self.roll_dates)}",
            f"first={first}",
            f"last={last}",
            f"quality={self.quality.value}",
        ]
        return " ".join(parts)


class JsonRollStore:
    """`<catalog>/roll_dates.json`: roll boundary table keyed by `bar_type`."""

    _lock = threading.Lock()

    def __init__(self, catalog_path: Path) -> None:
        self._path = catalog_path.expanduser().resolve() / "roll_dates.json"

    @property
    def path(self) -> Path:
        return self._path

    def write(self, key: str, rolls: Sequence[RollBoundary]) -> None:
        with self._lock:
            current: dict[str, object] = {}
            if self._path.exists():
                loaded = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    current = loaded
            current[key] = [
                {
                    "ts_utc": roll.ts_utc.isoformat(),
                    "from_contract": roll.from_contract,
                    "to_contract": roll.to_contract,
                    "price_jump_pct": str(roll.price_jump_pct),
                    "source": roll.source,
                }
                for roll in rolls
            ]
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._path.with_name(self._path.name + ".tmp")
            temporary.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")
            os.replace(temporary, self._path)

    def load(self) -> dict[str, list[RollBoundary]]:
        if not self._path.exists():
            return {}
        loaded = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            return {}
        result: dict[str, list[RollBoundary]] = {}
        for key, items in loaded.items():
            if not isinstance(items, list):
                continue
            entries: list[RollBoundary] = []
            for item in items:
                if not isinstance(item, dict) or "ts_utc" not in item:
                    continue
                ts = datetime.fromisoformat(str(item["ts_utc"]))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                entries.append(
                    RollBoundary(
                        ts_utc=ts.astimezone(UTC),
                        from_contract=(
                            None
                            if item.get("from_contract") is None
                            else str(item["from_contract"])
                        ),
                        to_contract=(
                            None if item.get("to_contract") is None else str(item["to_contract"])
                        ),
                        price_jump_pct=Decimal(str(item.get("price_jump_pct", "0"))),
                        source=str(item.get("source", "contract_switch")),
                    )
                )
            result[str(key)] = entries
        return result

    def timestamps_for(self, key: str) -> frozenset[datetime]:
        return frozenset(entry.ts_utc for entry in self.load().get(key, ()))


def _nanos_to_utc(ts_ns: int) -> datetime:
    sec, rem_ns = divmod(ts_ns, 1_000_000_000)
    return datetime.fromtimestamp(sec, tz=UTC).replace(microsecond=rem_ns // 1_000)


def normalize_databento_instrument_id(
    raw_id: str,
    *,
    use_exchange_as_venue: bool = True,
    futures_year_digits: int = 2,
    reference_year: int | None = None,
) -> str:
    """Normalize a COMEX/Databento symbol into a supported `FuturesContract` instrument ID."""
    cleaned = raw_id.strip().upper()
    if "." not in cleaned:
        venue = "XCEC" if use_exchange_as_venue else "GLBX"
        cleaned = f"{cleaned}.{venue}"
    else:
        head, tail = cleaned.rsplit(".", 1)
        if tail in {"GLBX", "XCEC"}:
            cleaned = f"{head}.{tail}"
        elif tail in {"V", "C", "N"} or tail.isdigit():
            # Continuous symbology like GC.v.0 -> GLBX
            cleaned = f"{cleaned}.GLBX"
    # Normalize upper/lower continuous qualifier (`.v.`, `.c.`, `.n.`).
    for tag in (".V.", ".C.", ".N."):
        cleaned = cleaned.replace(tag, tag.lower())

    if futures_year_digits == 2 and reference_year is not None:
        match = _ONE_DIGIT_YEAR_RE.match(cleaned)
        if match is not None:
            root, month, digit, venue = match.groups()
            decade = (reference_year // 10) * 10
            candidate_year = decade + int(digit)
            if candidate_year < reference_year - 2:
                candidate_year += 10
            yy = candidate_year % 100
            cleaned = f"{root}{month}{yy:02d}.{venue}"

    resolve_instrument(cleaned)
    return cleaned


def detect_contract_rolls(
    labeled_bars: Sequence[tuple[str, OhlcvBar]],
) -> tuple[RollBoundary, ...]:
    """Identify timestamps where the underlying outright contract changes in sorted bars."""
    if len(labeled_bars) < 2:
        return ()
    rolls: list[RollBoundary] = []
    prev_contract, prev_bar = labeled_bars[0]
    for curr_contract, curr_bar in labeled_bars[1:]:
        if curr_contract != prev_contract:
            jump_pct = (
                abs(curr_bar.close / prev_bar.close - Decimal("1"))
                if prev_bar.close > 0
                else Decimal("0")
            )
            rolls.append(
                RollBoundary(
                    ts_utc=curr_bar.ts_utc,
                    from_contract=prev_contract,
                    to_contract=curr_contract,
                    price_jump_pct=jump_pct.quantize(Decimal("0.000001")),
                    source="contract_switch",
                )
            )
        prev_contract, prev_bar = curr_contract, curr_bar
    return tuple(rolls)


def _infer_interval(bars: Sequence[Bar], explicit_interval: str | None) -> str:
    if explicit_interval is not None:
        if explicit_interval not in INTERVALS:
            allowed = ", ".join(sorted(INTERVALS))
            raise ValueError(f"unsupported interval {explicit_interval!r}; use one of: {allowed}")
        return explicit_interval
    for item in bars:
        try:
            return interval_from_bar_type(str(item.bar_type))
        except ValueError:
            continue
    raise ValueError("cannot infer bar interval from DBN records; pass --interval explicitly")


def load_dbn_bars(
    path: str | Path,
    *,
    instrument_id: str | None = None,
    interval: str | None = None,
    price_precision: int | None = None,
    use_exchange_as_venue: bool = True,
    bars_timestamp_on_close: bool = True,
    futures_year_digits: int = 2,
    loader_factory: Callable[[], DbnLoader] | None = None,
) -> tuple[list[OhlcvBar], str, str, tuple[RollBoundary, ...]]:
    """Decode a Databento `.dbn` / `.dbn.zst` file into validated close-stamped `OhlcvBar`s."""
    if not bars_timestamp_on_close:
        raise ValueError(
            "bars_timestamp_on_close must remain True to prevent look-ahead bias on Databento bars"
        )
    dbn_path = Path(path).expanduser().resolve()
    if not dbn_path.exists():
        raise FileNotFoundError(f"DBN file not found: {dbn_path}")

    resolved_override: str | None = None
    if instrument_id is not None:
        resolved_override = normalize_databento_instrument_id(
            instrument_id,
            use_exchange_as_venue=use_exchange_as_venue,
            futures_year_digits=futures_year_digits,
        )

    loader = loader_factory() if loader_factory is not None else DatabentoDataLoader()
    # Preserve raw contract symbols on continuous targets so contract switches are detected.
    is_continuous_target = bool(
        resolved_override and any(tag in resolved_override for tag in (".v.", ".c.", ".n."))
    )
    nautilus_override = (
        None
        if is_continuous_target or resolved_override is None
        else InstrumentId.from_str(resolved_override)
    )
    raw_items = loader.from_dbn_file(
        path=dbn_path,
        instrument_id=nautilus_override,
        price_precision=price_precision,
        as_legacy_cython=True,
        include_trades=False,
        use_exchange_as_venue=use_exchange_as_venue,
        bars_timestamp_on_close=True,
    )
    nautilus_bars = [item for item in raw_items if isinstance(item, Bar)]
    if not nautilus_bars:
        raise ValueError(f"no OHLCV Bar records decoded from {dbn_path}")

    resolved_interval = _infer_interval(nautilus_bars, interval)
    first_ts = _nanos_to_utc(int(nautilus_bars[0].ts_event))
    target_instrument_id = resolved_override or normalize_databento_instrument_id(
        str(nautilus_bars[0].bar_type.instrument_id),
        use_exchange_as_venue=use_exchange_as_venue,
        futures_year_digits=futures_year_digits,
        reference_year=first_ts.year,
    )

    by_ts: dict[datetime, tuple[str, OhlcvBar]] = {}
    for raw_bar in nautilus_bars:
        ts_utc = _nanos_to_utc(int(raw_bar.ts_event))
        raw_contract = str(raw_bar.bar_type.instrument_id)
        domain_bar = OhlcvBar(
            instrument_id=target_instrument_id,
            ts_utc=ts_utc,
            open=raw_bar.open.as_decimal(),
            high=raw_bar.high.as_decimal(),
            low=raw_bar.low.as_decimal(),
            close=raw_bar.close.as_decimal(),
            volume=raw_bar.volume.as_decimal(),
        )
        validate_bar(domain_bar, now=ts_utc)
        by_ts[ts_utc] = (raw_contract, domain_bar)

    ordered_labeled = [by_ts[ts] for ts in sorted(by_ts)]
    prev_ts: datetime | None = None
    ordered_bars: list[OhlcvBar] = []
    for _, bar in ordered_labeled:
        validate_bar(bar, previous_ts=prev_ts, now=bar.ts_utc)
        prev_ts = bar.ts_utc
        ordered_bars.append(bar)

    rolls = detect_contract_rolls(ordered_labeled)
    return ordered_bars, target_instrument_id, resolved_interval, rolls


def download_databento_dbn(
    *,
    dataset: str,
    symbols: str | Sequence[str],
    schema: str,
    start: datetime,
    end: datetime,
    output_path: str | Path,
    api_key: str,
    stype_in: str = "continuous",
) -> Path:
    """Download Databento DBN data via optional `databento` package (no secret logging)."""
    if not api_key or not api_key.strip():
        raise ValueError(
            "DATABENTO_API_KEY is required for online Databento download; "
            "pass --dbn-file for offline DBN import"
        )
    try:
        import databento as db  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "databento package is not installed; install with `uv sync --extra databento` "
            "or pass --dbn-file for offline DBN import"
        ) from exc

    target = Path(output_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    symbol_list = [symbols] if isinstance(symbols, str) else list(symbols)
    try:
        client = db.Historical(key=api_key.strip())
        data = client.timeseries.get_range(
            dataset=dataset,
            symbols=symbol_list,
            schema=schema,
            start=start.isoformat(),
            end=end.isoformat(),
            stype_in=stype_in,
        )
        data.to_file(str(target))
    except Exception as exc:  # noqa: BLE001 — mask any exception detail that might echo credentials
        raise RuntimeError(f"Databento download failed ({type(exc).__name__})") from None
    return target


def ingest_databento_dbn(
    *,
    dbn_path: str | Path,
    catalog_path: str | Path,
    mode: TradingMode,
    instrument_id: str | None = None,
    interval: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    price_precision: int | None = None,
    use_exchange_as_venue: bool = True,
    roll_dates: Sequence[datetime] = (),
    loader_factory: Callable[[], DbnLoader] | None = None,
) -> DatabentoIngestReport:
    """Decode DBN file -> isolate roll dates -> run calendar QC -> write Parquet catalog."""
    require_simulated_mode(mode)
    bars, target_id, resolved_interval, detected_rolls = load_dbn_bars(
        dbn_path,
        instrument_id=instrument_id,
        interval=interval,
        price_precision=price_precision,
        use_exchange_as_venue=use_exchange_as_venue,
        bars_timestamp_on_close=True,
        loader_factory=loader_factory,
    )
    if start is not None:
        bars = [bar for bar in bars if bar.ts_utc >= start]
    if end is not None:
        bars = [bar for bar in bars if bar.ts_utc < end]

    explicit_rolls = [
        RollBoundary(
            ts_utc=ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC),
            source="declared_roll",
        )
        for ts in roll_dates
    ]
    by_roll_ts: dict[datetime, RollBoundary] = {item.ts_utc: item for item in explicit_rolls}
    for detected in detected_rolls:
        by_roll_ts[detected.ts_utc] = detected
    all_rolls = tuple(by_roll_ts[ts] for ts in sorted(by_roll_ts))

    bar_type = nautilus_bar_type(target_id, resolved_interval)
    step: timedelta = INTERVALS[resolved_interval]
    roll_ts_set = frozenset(item.ts_utc for item in all_rolls)
    report: QualityReport = check_bars(
        bars,
        interval=step,
        calendar=trading_calendar_for_instrument(target_id),
        roll_timestamps=roll_ts_set,
    )

    root = Path(catalog_path).expanduser().resolve()
    JsonQualityStore(root).write(bar_type, report)
    if all_rolls:
        JsonRollStore(root).write(bar_type, all_rolls)

    written = 0
    if bars:
        written = NautilusParquetCatalog(root).write(
            bars,
            bar_type=bar_type,
            instrument_id=target_id,
        )

    return DatabentoIngestReport(
        instrument_id=target_id,
        bar_type=bar_type,
        interval=resolved_interval,
        rows_written=written,
        first_ts=bars[0].ts_utc if bars else None,
        last_ts=bars[-1].ts_utc if bars else None,
        quality=report.status(),
        roll_dates=all_rolls,
        notes=report.notes,
    )
