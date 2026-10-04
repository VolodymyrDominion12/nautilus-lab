"""Nightly data refresh: what to re-ingest, and what to tell a human afterwards.

The refresh itself is a sequence of archive ingests (`lab refresh-data` runs them).
This module holds the two decisions around it, so they are testable without I/O:

* **plan** — which catalogs exist (`catalog_<spot|perp>_<interval>`) and which symbols
  they hold, so the nightly run refreshes exactly what research reads;
* **summary** — after the run: how many series are ok/warn/fail, which are stale, and
  one message that says so. A refresh that silently left half the universe stale is
  the failure this exists to surface (docs/34, P2).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta

_CATALOG_NAME = re.compile(r"^catalog_(spot|perp)_(1m|5m|15m|1h|4h|1d)$")


@dataclass(frozen=True, slots=True)
class RefreshTarget:
    catalog: str
    market: str  # "spot" | "um"
    interval: str
    symbols: tuple[str, ...]


def plan_targets(catalogs: Mapping[str, Iterable[str]]) -> list[RefreshTarget]:
    """Catalog name -> instrument ids, turned into archive refresh targets.

    Only catalogs named by the archive convention take part: a hand-made catalog
    (`catalog`, `catalog_2019_4h`) is not refreshed behind its owner's back.
    """
    targets: list[RefreshTarget] = []
    for name, instrument_ids in sorted(catalogs.items()):
        match = _CATALOG_NAME.match(name)
        if match is None:
            continue
        kind, interval = match.groups()
        symbols = sorted({symbol_of(item) for item in instrument_ids} - {""})
        if symbols:
            targets.append(
                RefreshTarget(
                    catalog=name,
                    market="spot" if kind == "spot" else "um",
                    interval=interval,
                    symbols=tuple(symbols),
                )
            )
    return targets


def symbol_of(instrument_id: str) -> str:
    """`BTC/USDT.SIM` and `BTCUSDT-PERP.SIM` -> `BTCUSDT`."""
    return instrument_id.removesuffix(".SIM").removesuffix("-PERP").replace("/", "")


@dataclass(frozen=True, slots=True)
class SeriesState:
    catalog: str
    bar_type: str
    status: str
    last: datetime | None


@dataclass(frozen=True, slots=True)
class RefreshSummary:
    total: int
    ok: int
    warn: int
    fail: tuple[SeriesState, ...]
    #: Series whose last bar is older than the staleness limit but younger than the
    #: delisting horizon: they *should* have moved and did not.
    stale: tuple[SeriesState, ...]
    ingest_failures: int = 0
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def healthy(self) -> bool:
        return not self.fail and not self.stale and self.ingest_failures == 0

    def message(self, *, max_listed: int = 8) -> str:
        head = (
            f"data refresh: {self.total} series, ok {self.ok}, warn {self.warn}, "
            f"fail {len(self.fail)}, stale {len(self.stale)}, "
            f"ingest failures {self.ingest_failures}"
        )
        lines = [head]
        for title, items in (("FAIL", self.fail), ("STALE", self.stale)):
            for item in items[:max_listed]:
                last = item.last.date().isoformat() if item.last else "?"
                lines.append(f"{title} {item.catalog}/{item.bar_type} last={last}")
            if len(items) > max_listed:
                lines.append(f"... and {len(items) - max_listed} more {title.lower()}")
        lines.extend(self.notes)
        return "\n".join(lines)


def summarize(
    reports: Mapping[str, Mapping[str, Mapping[str, object]]],
    *,
    now: datetime,
    stale_after: timedelta = timedelta(days=3),
    delisted_after: timedelta = timedelta(days=60),
    ingest_failures: int = 0,
) -> RefreshSummary:
    """`{catalog: {bar_type: quality report}}` -> one verdict for the whole refresh.

    A series last seen more than `delisted_after` ago is a delisted coin, kept for the
    survivorship-free history and expected never to move again — not stale.
    """
    ok = warn = 0
    failed: list[SeriesState] = []
    stale: list[SeriesState] = []
    total = 0
    for catalog, by_bar_type in sorted(reports.items()):
        for bar_type, report in sorted(by_bar_type.items()):
            total += 1
            status = str(report.get("status") or "unknown")
            last = _parse_ts(report.get("last"))
            state = SeriesState(catalog=catalog, bar_type=bar_type, status=status, last=last)
            if status == "fail":
                failed.append(state)
            elif status == "warn":
                warn += 1
            elif status == "ok":
                ok += 1
            if last is not None and stale_after < now - last <= delisted_after:
                stale.append(state)
    return RefreshSummary(
        total=total,
        ok=ok,
        warn=warn,
        fail=tuple(failed),
        stale=tuple(stale),
        ingest_failures=ingest_failures,
    )


def _parse_ts(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None
