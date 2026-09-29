#!/usr/bin/env python3
"""run_decision_sweep.py — бектест-свіп усіх роботів на ETH/BTC + журнали рішень.

Мета (запит дослідника): прогнати **усі** стратегії — включно з `rejected` і
`blocked` — на ETHUSDT і BTCUSDT з щонайменше двома роками історії і зібрати
журнали прийняття рішень (`decision_trace/1`), щоб було видно *чому* робот
торгував або не торгував, а не лише скільки він заробив.

Два проходи на кожен (робот × інструмент)::

    A. числа      `lab research --robot R --folds 4`        DECISION_LOG_ENABLED=false
    B. рішення    `lab research --robot R --folds 1 \\        DECISION_LOG_ENABLED=true
                     --is-start … --is-end …               DECISION_LOG_DIR=<raw>/<key>
                     --oos-start … --oos-end …`

Прохід B бере **вікно останнього фолда** проходу A (те саме вікно, яке вже
надруковане в звіті `fold i OOS=[…]`), тож журнал рішень належить саме тому
out-of-sample вікну, за яке звітує прохід A. Вікна рахує `plan_multi` з
`application/run_walk_forward.py` — те саме джерело, що й `execute_multi`, тому
числа обох проходів мусять збігтися (це перевіряється, див. `_cross_check`).

Чому журнал рішень не можна вмикати на весь walk-forward: сітка параметрів
прогоняється на in-sample барах, і кожен прогін сітки пише по запису на бар.
Для `regime` на 1h це ~100 тис. записів (~150 МБ) на один робота, з яких
змістовні — лише out-of-sample. Тому прохід B фільтрує записи по вікну
`[oos_start, oos_end)` і зберігає лише їх (сирі файли видаляються), а прохід A
пише числа без журналу взагалі.

Використання::

    .venv/bin/python scripts/run_decision_sweep.py --dry-run
    .venv/bin/python scripts/run_decision_sweep.py --only ema_ETH
    .venv/bin/python scripts/run_decision_sweep.py --parallel 3

Артефакти в `reports/decision-sweep/`:

    logs/<key>.numbers.log     повний stdout проходу A (числа)
    logs/<key>.trace.log       повний stdout проходу B (журнал рішень)
    decisions/<key>.jsonl      рішення OOS-вікна (лише вони, очищені)
    digests/<key>.md           дайджест рішень (людською мовою)
    status.json                стан кожного прогону + розібрані числа
    summary.md                 зведення (генерується окремо / цим же скриптом)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "reports" / "decision-sweep"
LAB = REPO / ".venv" / "bin" / "lab"

#: Фолди беруться ті самі, що в попередніх матрицях (reports/matrix/*_f4.log).
FOLDS = 4
#: Частка історії на підбір параметрів; OOS дістає решту після embargo.
IS_FRACTION = "0.7"
#: Таймаут на один прохід (секунди). 1h-сітка на 24 тис. барів іде хвилини.
PASS_TIMEOUT = 3600


@dataclass(frozen=True, slots=True)
class Entry:
    """Один прогін матриці: робот × інструмент × каталог."""

    key: str
    robot: str
    symbol: str
    catalog: str
    interval: str
    env: tuple[tuple[str, str], ...] = ()
    note: str = ""
    #: Роботи без адаптера в рушії: не «запустились погано», а не запускаються взагалі.
    expected_fail: bool = False


# ── Матриця ───────────────────────────────────────────────────────────────────
#
# Основний каталог — `catalog` (1h, 2024-01-01 → 2026-09-28, ~23.9 тис. барів
# ≈ 2.7 роки): у ньому є spot-серії ETH/BTC, taker-flow (для `vpin_momentum`),
# funding і orderbook-знімки. ML-моделі в `models/clean/*_preoos.txt` навчені
# строго до першого OOS-бару цього вікна (2025-11-29) і мають model card — без
# них ворота `require_clean_model` відмовляють (fail closed).
#
# `funding` живе окремо: йому потрібні spot І perp **бари** + серія funding.
# У `catalog` perp-барів немає взагалі, тому він іде на `catalog_2019_4h`
# (4h, PERP-серії ETH і BTC з 2024-01-01 — перетин зі spot дає ті самі 2.7 роки).
MATRIX: tuple[Entry, ...] = (
    Entry("regime_ETH", "regime", "ETHUSDT", "catalog", "1h"),
    Entry("regime_BTC", "regime", "BTCUSDT", "catalog", "1h"),
    Entry("ema_ETH", "ema", "ETHUSDT", "catalog", "1h"),
    Entry("ema_BTC", "ema", "BTCUSDT", "catalog", "1h"),
    Entry("adaptive_ema_ETH", "adaptive_ema", "ETHUSDT", "catalog", "1h"),
    Entry("adaptive_ema_BTC", "adaptive_ema", "BTCUSDT", "catalog", "1h"),
    Entry("vpin_momentum_ETH", "vpin_momentum", "ETHUSDT", "catalog", "1h"),
    Entry("vpin_momentum_BTC", "vpin_momentum", "BTCUSDT", "catalog", "1h"),
    Entry(
        "formulaic_lgbm_ETH",
        "formulaic_lgbm",
        "ETHUSDT",
        "catalog",
        "1h",
        (("FORMULAIC_MODEL_PATH", "models/clean/formulaic_ETH_preoos.txt"),),
    ),
    Entry(
        "formulaic_lgbm_BTC",
        "formulaic_lgbm",
        "BTCUSDT",
        "catalog",
        "1h",
        (("FORMULAIC_MODEL_PATH", "models/clean/formulaic_BTC_preoos.txt"),),
    ),
    Entry(
        "meta_label_ETH",
        "meta_label",
        "ETHUSDT",
        "catalog",
        "1h",
        (("META_LABEL_MODEL_PATH", "models/clean/meta_label_ETH_preoos.txt"),),
    ),
    Entry(
        "meta_label_BTC",
        "meta_label",
        "BTCUSDT",
        "catalog",
        "1h",
        (("META_LABEL_MODEL_PATH", "models/clean/meta_label_BTC_preoos.txt"),),
    ),
    # ml_obi: `ML_OBI_MODEL_PATH` порожній (у .env теж), і єдиний orderbook-знімок
    # у каталозі — один день на символ. Прогін робимо, щоб зафіксувати *реальний*
    # текст відмови, а не припущення про неї.
    Entry("ml_obi_ETH", "ml_obi", "ETHUSDT", "catalog", "1h"),
    Entry("ml_obi_BTC", "ml_obi", "BTCUSDT", "catalog", "1h"),
    # pairs: дві ноги ETH+BTB фіксовані в PairsParams, тому це один прогін, не два.
    Entry("pairs_ETHBTC", "pairs", "ETHUSDT", "catalog", "1h"),
    Entry(
        "funding_ETH",
        "funding",
        "ETHUSDT",
        "catalog_2019_4h",
        "4h",
        (
            ("FUNDING_SPOT_ID", "ETH/USDT.SIM"),
            ("FUNDING_PERP_ID", "ETHUSDT-PERP.SIM"),
        ),
    ),
    Entry(
        "funding_BTC",
        "funding",
        "BTCUSDT",
        "catalog_2019_4h",
        "4h",
        (
            ("FUNDING_SPOT_ID", "BTC/USDT.SIM"),
            ("FUNDING_PERP_ID", "BTCUSDT-PERP.SIM"),
        ),
    ),
    # Не підключені до рушія (BACKTEST_WIRED_ROBOTS): кожен мусить упасти fail
    # closed. Запускаємо, щоб у звіті був справжній текст відмови.
    Entry("glft_ETH", "glft", "ETHUSDT", "catalog", "1h", expected_fail=True),
    Entry("tri_scan_ETH", "tri_scan", "ETHUSDT", "catalog", "1h", expected_fail=True),
)


@dataclass
class EntryResult:
    key: str
    robot: str
    symbol: str
    catalog: str
    interval: str
    status: str = "pending"
    error: str = ""
    window: dict[str, str] = field(default_factory=dict)
    fold_windows: list[dict[str, str]] = field(default_factory=list)
    numbers: dict[str, Any] = field(default_factory=dict)
    trace: dict[str, Any] = field(default_factory=dict)
    journal: dict[str, Any] = field(default_factory=dict)
    starting_equity: str = ""
    decisions: int = 0
    decisions_bytes: int = 0
    digest: str = ""


# ── Середовище прогону ────────────────────────────────────────────────────────


def base_env(entry: Entry, *, out_dir: Path) -> dict[str, str]:
    """Env підпроцесу `lab`: інструмент, каталог, інтервал + ізоляція артефактів.

    `TRIALS_LEDGER_PATH` навмисно виводиться з-під трекованого
    `research/trials.jsonl`: свіп — розвідка, і він не мусить переписувати
    журнал тріалів, за яким рахують DSR. Розмір сітки й фолди друкуються в
    звіті, тож облік тріалів лишається прозорим.
    """
    base = entry.symbol.replace("USDT", "")
    instrument_id = f"{base}/USDT.SIM"
    spec = {"1h": "1-HOUR", "4h": "4-HOUR", "1d": "1-DAY"}[entry.interval]
    env = dict(os.environ)
    env.update(
        {
            "INSTRUMENT_ID": instrument_id,
            "BAR_INTERVAL": entry.interval,
            "BAR_TYPE": f"{instrument_id}-{spec}-LAST-EXTERNAL",
            "CATALOG_PATH": entry.catalog,
            "CATALOG_PATHS": "",
            "JOURNAL_ENABLED": "false",
            "TRIALS_LEDGER_PATH": str(out_dir / "trials" / f"{entry.key}.jsonl"),
        }
    )
    env.update(dict(entry.env))
    return env


def plan_windows(entry: Entry, env: dict[str, str]) -> tuple[list[dict[str, str]], str]:
    """Вікна фолдів — тим самим кодом, що й `execute_multi` (`RunWalkForward.plan_multi`).

    Викликається в процесі-оркестраторі (не в підпроцесі `lab`), тому env
    підмінюється на час побудови `Settings`. Друге значення — стартовий капітал:
    без нього перехресна перевірка A↔B не може відтворити відсоток доходності.
    """
    saved = dict(os.environ)
    os.environ.update(env)
    try:
        from nautilus_lab.application.run_walk_forward import RunWalkForward
        from nautilus_lab.domain.regime import RobotName
        from nautilus_lab.infrastructure.settings import Settings
        from nautilus_lab.interfaces.composition import research_feed, walk_forward_request

        cfg = Settings(_env_file=str(REPO / ".env"))
        request = walk_forward_request(
            cfg,
            robot=RobotName(entry.robot),
            folds=FOLDS,
            in_sample_fraction=Decimal(IS_FRACTION),
        )
        planner = RunWalkForward(_NullEngine(), research_feed(cfg))
        windows = planner.plan_multi(request)
        equity = str(cfg.starting_equity)
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return [
        {
            "in_sample_start": w.in_sample_start.isoformat(),
            "in_sample_end": w.in_sample_end.isoformat(),
            "out_of_sample_start": w.out_of_sample_start.isoformat(),
            "out_of_sample_end": w.out_of_sample_end.isoformat(),
        }
        for w in windows
    ], equity


class _NullEngine:
    """Заглушка: `plan_multi` рахує вікна й не запускає жодного бектесту."""

    def run(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError("plan_multi must not run a backtest")

    def run_spread(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError("plan_multi must not run a backtest")


# ── Проходи ───────────────────────────────────────────────────────────────────

_FOLD_RE = re.compile(
    r"^fold (?P<index>\d+) OOS=\[(?P<oos_start>[^,]+), (?P<oos_end>[^)]+)\) "
    r"fills=(?P<fills>\d+) return=(?P<return>\S+) buy_hold=(?P<buy_hold>\S+) "
    r"selected=(?P<selected>.*)$"
)
_AGG_RE = re.compile(
    r"^out-of-sample aggregate profitable=(?P<profitable>\d+)/(?P<folds>\d+) "
    r"mean_gross=(?P<mean_gross>\S+) mean=(?P<mean>\S+) median=(?P<median>\S+) "
    r"worst=(?P<worst>\S+) best=(?P<best>\S+)$"
)
_BASE_RE = re.compile(r"^baseline buy&hold mean=(?P<buy_hold>\S+) oos_fills=(?P<oos_fills>\d+)$")
_GATE_RE = re.compile(r"^promotion_gate=(?P<label>\S+) \((?P<checks>.*)\)$")
_MANIFEST_RE = re.compile(r"^manifest (?P<manifest>.*)$")
#: Прохід B — це single-split walk-forward, тож його OOS друкується окремим рядком
#: (`_print_walk_forward`), а не рядком `fold i OOS=…` багатовіконного звіту.
_OOS_LINE_RE = re.compile(
    r"^out-of-sample \(report this\) fills=(?P<fills>\d+) ending=(?P<ending>\S+)$"
)


def _run_lab(cmd: list[str], env: dict[str, str], log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as handle:
        handle.write(f"# cmd={' '.join(cmd)}\n")
        handle.write(
            "# env: "
            + " ".join(
                f"{name}={env[name]}"
                for name in (
                    "INSTRUMENT_ID",
                    "BAR_INTERVAL",
                    "CATALOG_PATH",
                    "DECISION_LOG_ENABLED",
                    "DECISION_LOG_DIR",
                    "FORMULAIC_MODEL_PATH",
                    "META_LABEL_MODEL_PATH",
                    "ML_OBI_MODEL_PATH",
                    "FUNDING_SPOT_ID",
                    "FUNDING_PERP_ID",
                )
                if name in env
            )
        )
        handle.write("\n\n")
        handle.flush()
        proc = subprocess.run(
            cmd,
            cwd=REPO,
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            timeout=PASS_TIMEOUT,
            check=False,
        )
    return proc.returncode


def _parse_numbers(text: str) -> dict[str, Any]:
    numbers: dict[str, Any] = {"folds": []}
    for line in text.splitlines():
        match = _FOLD_RE.match(line.strip())
        if match:
            numbers["folds"].append(match.groupdict())
            continue
        match = _AGG_RE.match(line.strip())
        if match:
            numbers["aggregate"] = match.groupdict()
            continue
        match = _BASE_RE.match(line.strip())
        if match:
            numbers["baseline"] = match.groupdict()
            continue
        match = _GATE_RE.match(line.strip())
        if match:
            numbers["gate"] = match.groupdict()
            continue
        match = _MANIFEST_RE.match(line.strip())
        if match:
            numbers["manifest"] = match.group("manifest")
            continue
        match = _OOS_LINE_RE.match(line.strip())
        if match:
            numbers["oos"] = match.groupdict()
    return numbers


def run_numbers_pass(entry: Entry, out_dir: Path) -> tuple[int, dict[str, Any], str]:
    """Прохід A: числа walk-forward. Журнал рішень вимкнено — сітка IS не потрібна."""
    env = base_env(entry, out_dir=out_dir)
    env["DECISION_LOG_ENABLED"] = "false"
    env["DECISION_LOG_DIR"] = str(out_dir / "raw-disabled" / entry.key)
    cmd = [
        str(LAB),
        "research",
        "--robot",
        entry.robot,
        "--folds",
        str(FOLDS),
        "--catalog",
        entry.catalog,
    ]
    log_path = out_dir / "logs" / f"{entry.key}.numbers.log"
    code = _run_lab(cmd, env, log_path)
    text = log_path.read_text(encoding="utf-8", errors="replace")
    return code, _parse_numbers(text), text


def run_trace_pass(entry: Entry, out_dir: Path, window: dict[str, str]) -> tuple[int, str]:
    """Прохід B: той самий walk-forward, але на вікні останнього фолда + журнал рішень."""
    env = base_env(entry, out_dir=out_dir)
    raw_dir = out_dir / "raw" / entry.key
    env["DECISION_LOG_ENABLED"] = "true"
    env["DECISION_LOG_DIR"] = str(raw_dir)
    cmd = [
        str(LAB),
        "research",
        "--robot",
        entry.robot,
        "--folds",
        "1",
        "--catalog",
        entry.catalog,
        "--is-start",
        window["in_sample_start"],
        "--is-end",
        window["in_sample_end"],
        "--oos-start",
        window["out_of_sample_start"],
        "--oos-end",
        window["out_of_sample_end"],
    ]
    log_path = out_dir / "logs" / f"{entry.key}.trace.log"
    code = _run_lab(cmd, env, log_path)
    return code, log_path.read_text(encoding="utf-8", errors="replace")


# ── Журнал рішень: фільтр вікна + дайджест ────────────────────────────────────


def _ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def collect_oos_decisions(
    entry: Entry,
    out_dir: Path,
    window: dict[str, str],
) -> tuple[dict[str, Any], str]:
    """Лишити рішення OOS-вікна, видалити сирі файли, зібрати дайджест.

    Фільтр по `ts` — точний, а не наближений: і `split_by_window`, і запис
    журналу користуються тим самим полем `bar.ts_utc` (інтервал напіввідкритий).

    Повертає факти про журнал (кількість записів, пропуски `bar_seq`, розподіл
    `outcome`) і Markdown-дайджест. Факти потрібні, щоб **перевірити повноту**:
    журнал, який тихо загубив частину барів, виглядав би як «робот не торгував».
    """
    from nautilus_lab.application.decision_digest import build_digest, digest_markdown

    start = _ts(window["out_of_sample_start"])
    end = _ts(window["out_of_sample_end"])
    raw_dir = out_dir / "raw" / entry.key

    rows: list[dict[str, Any]] = []
    if raw_dir.exists():
        for path in sorted(raw_dir.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = row.get("ts")
                if not isinstance(ts, str):
                    continue
                if start <= _ts(ts) < end:
                    rows.append(row)
    rows.sort(key=lambda r: (str(r.get("ts")), 0 if r.get("kind") == "intrabar" else 1))

    decisions_path = out_dir / "decisions" / f"{entry.key}.jsonl"
    decisions_path.parent.mkdir(parents=True, exist_ok=True)
    with decisions_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    digest_path = out_dir / "digests" / f"{entry.key}.md"
    digest_path.parent.mkdir(parents=True, exist_ok=True)
    facts: dict[str, Any] = {"decisions": len(rows)}
    if rows:
        digest = build_digest(rows, max_narratives=40, no_signal_samples=6)
        markdown = digest_markdown(digest)
        facts.update(
            {
                "bar_seq_gaps": digest.bar_seq_gaps,
                "first_ts": digest.first_ts,
                "last_ts": digest.last_ts,
                "outcomes": dict(digest.outcomes),
                "blocked_by": dict(digest.blocked_by),
                "regime_share_pct": dict(digest.regime_share_pct),
                "signals": dict(digest.signals),
                "intrabar": dict(digest.intrabar),
                "near_misses": digest.near_misses,
                "config_hashes": list(digest.config_hashes),
            }
        )
    else:
        markdown = f"# Дайджест рішень: {entry.key}\n\nЗаписів у OOS-вікні немає.\n"
    digest_path.write_text(markdown, encoding="utf-8")

    kinds = Counter(str(row.get("kind", "bar_decision")) for row in rows)
    facts["kinds"] = dict(kinds)

    # Сирі файли містять ще й прогін сітки на in-sample; тримати їх нема сенсу.
    if raw_dir.exists():
        for path in raw_dir.glob("*.jsonl"):
            path.unlink()
        raw_dir.rmdir()

    return facts, markdown


_WRITE_FAIL_RE = re.compile(
    r"^Failed to write decision log to (?P<path>\S+)_(?P<date>\d{4}-\d{2}-\d{2})\.jsonl: "
    r"(?P<reason>.*)$"
)


def _write_failures(text: str, window: dict[str, str]) -> dict[str, Any]:
    """Скільки записів журналу не доїхало на диск — і скільки з них у OOS-вікні.

    Письменник ковтає помилку серіалізації (`decision_log_writer.log` ловить усе й
    лише логує), тож «нуль угод» у дайджесті може означати «нуль записаних угод».
    Ця перевірка робить різницю видимою.
    """
    start = _ts(window["out_of_sample_start"]).date()
    end = _ts(window["out_of_sample_end"]).date()
    total = 0
    in_oos = 0
    reasons: Counter[str] = Counter()
    for line in text.splitlines():
        match = _WRITE_FAIL_RE.match(line.strip())
        if not match:
            continue
        total += 1
        reasons[match.group("reason")] += 1
        day = date.fromisoformat(match.group("date"))
        if start <= day <= end:
            in_oos += 1
    return {
        "failed_writes_total": total,
        "failed_writes_in_oos_dates": in_oos,
        "failed_write_reasons": dict(reasons),
    }


def _drop_raw(raw_dir: Path) -> None:
    """Прибрати сирі журнали, якщо прогону не судилося дійти до фільтра."""
    if not raw_dir.exists():
        return
    for path in raw_dir.glob("*.jsonl"):
        path.unlink()
    raw_dir.rmdir()


# ── Оркестрація ───────────────────────────────────────────────────────────────


def run_entry(entry: Entry, out_dir: Path, *, keep_raw: bool = False) -> EntryResult:
    result = EntryResult(
        key=entry.key,
        robot=entry.robot,
        symbol=entry.symbol,
        catalog=entry.catalog,
        interval=entry.interval,
    )
    if entry.expected_fail:
        env = base_env(entry, out_dir=out_dir)
        env["DECISION_LOG_ENABLED"] = "false"
        env["DECISION_LOG_DIR"] = str(out_dir / "raw-disabled" / entry.key)
        log_path = out_dir / "logs" / f"{entry.key}.numbers.log"
        code = _run_lab(
            [
                str(LAB),
                "research",
                "--robot",
                entry.robot,
                "--folds",
                str(FOLDS),
                "--catalog",
                entry.catalog,
            ],
            env,
            log_path,
        )
        text = log_path.read_text(encoding="utf-8", errors="replace")
        result.status = "fail_closed" if code != 0 else "unexpectedly_ran"
        result.error = _last_error_line(text)
        return result

    try:
        windows, starting_equity = plan_windows(entry, base_env(entry, out_dir=out_dir))
    except Exception as exc:  # noqa: BLE001 — свіп мусить доїхати до кінця
        result.status = "plan_failed"
        result.error = f"{type(exc).__name__}: {exc}"
        return result

    result.fold_windows = windows
    result.starting_equity = starting_equity
    if not windows:
        result.status = "no_windows"
        result.error = "plan_multi returned no folds"
        return result

    last = windows[-1]
    result.window = dict(last)

    code_a, numbers, text_a = run_numbers_pass(entry, out_dir)
    result.numbers = numbers
    if code_a != 0:
        result.status = "numbers_failed"
        result.error = _last_error_line(text_a)
        return result

    code_b, text_b = run_trace_pass(entry, out_dir, last)
    if code_b != 0:
        result.status = "trace_failed"
        result.error = _last_error_line(text_b)
        _drop_raw(out_dir / "raw" / entry.key)
        return result

    result.trace = _parse_numbers(text_b)
    result.status = "ok"

    try:
        facts, markdown = collect_oos_decisions(entry, out_dir, last)
        result.journal = facts
        result.digest = markdown
        result.decisions = int(facts.get("decisions", 0))
        result.decisions_bytes = (out_dir / "decisions" / f"{entry.key}.jsonl").stat().st_size
    except Exception as exc:  # noqa: BLE001
        result.status = "digest_failed"
        result.error = f"{type(exc).__name__}: {exc}"

    return result


def _last_error_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in reversed(lines):
        if line.startswith(("Error", "ERROR", "Traceback")) or "Error:" in line or "error:" in line:
            return line
    return lines[-1] if lines else ""


def _cross_check(result: EntryResult) -> str:
    """Прохід B мусить відтворити числа останнього фолда проходу A.

    Це не формальність: якщо вони розійдуться, журнал рішень описує не той прогін,
    за який звітує таблиця, і читати його як «ось чому цей робот так торгував» не
    можна. Порівнюються `fills` і дохідність OOS (з `ending` проходу B і
    `STARTING_EQUITY`), а не сам текст рядків.
    """
    folds = result.numbers.get("folds") or []
    oos = result.trace.get("oos")
    if not folds or not oos or not result.starting_equity:
        return "not_checked"
    a = folds[-1]
    equity = Decimal(result.starting_equity)
    ending = Decimal(oos.get("ending", "0"))
    if equity <= 0:
        return "not_checked"
    percent = f"{(ending - equity) / equity * 100:+.2f}%"
    same = a.get("fills") == oos.get("fills") and a.get("return") == percent
    return "match" if same else "MISMATCH"


def _dump_status(results: list[EntryResult], out_dir: Path) -> None:
    payload = [
        {
            "key": result.key,
            "robot": result.robot,
            "symbol": result.symbol,
            "catalog": result.catalog,
            "interval": result.interval,
            "status": result.status,
            "error": result.error,
            "window": result.window,
            "fold_windows": result.fold_windows,
            "numbers": result.numbers,
            "trace": result.trace,
            "journal": result.journal,
            "write_failures": _write_failures(
                (out_dir / "logs" / f"{result.key}.trace.log").read_text(
                    encoding="utf-8", errors="replace"
                )
                if (out_dir / "logs" / f"{result.key}.trace.log").exists()
                else "",
                result.window,
            )
            if result.window
            else {},
            "trace_matches_last_fold": _cross_check(result),
            "starting_equity": result.starting_equity,
            "decisions": result.decisions,
            "decisions_bytes": result.decisions_bytes,
        }
        for result in results
    ]
    (out_dir / "status.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _select(entries: tuple[Entry, ...], only: str | None) -> list[Entry]:
    if not only:
        return list(entries)
    wanted = {item.strip() for item in only.split(",") if item.strip()}
    known = {entry.key for entry in entries}
    unknown = wanted - known
    if unknown:
        raise SystemExit(f"unknown keys: {sorted(unknown)}; known: {sorted(known)}")
    return [entry for entry in entries if entry.key in wanted]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--only", help="Лише ці ключі (через кому), напр. ema_ETH")
    parser.add_argument("--parallel", type=int, default=1, help="Скільки прогонів одночасно")
    parser.add_argument("--dry-run", action="store_true", help="Показати команди без запуску")
    parser.add_argument("--keep-raw", action="store_true", help="Не видаляти сирі журнали")
    args = parser.parse_args(argv)

    if not LAB.exists():
        raise SystemExit(f"missing {LAB}; run from a synced checkout")
    out_dir = OUT
    out_dir.mkdir(parents=True, exist_ok=True)

    entries = _select(MATRIX, args.only)
    env_note = f"folds={FOLDS} is_fraction={IS_FRACTION} parallel={args.parallel}"
    print(f"decision sweep: {len(entries)} runs, {env_note}, out={out_dir}")

    if args.dry_run:
        for entry in entries:
            base = entry.symbol.replace("USDT", "")
            print(
                f"  {entry.key:22s} robot={entry.robot:15s} instrument={base}/USDT.SIM "
                f"interval={entry.interval} catalog={entry.catalog}"
                + ("  [expected fail closed]" if entry.expected_fail else "")
            )
        return 0

    results: list[EntryResult] = []

    def _settle(entry: Entry) -> EntryResult:
        """Один прогін не має права покласти весь свіп: збій стає рядком у status.json."""
        try:
            return run_entry(entry, out_dir)
        except Exception as exc:  # noqa: BLE001
            broken = EntryResult(
                key=entry.key,
                robot=entry.robot,
                symbol=entry.symbol,
                catalog=entry.catalog,
                interval=entry.interval,
                status="crashed",
                error=f"{type(exc).__name__}: {exc}",
            )
            return broken

    if args.parallel > 1:
        with ThreadPoolExecutor(max_workers=args.parallel) as pool:
            futures = [pool.submit(_settle, entry) for entry in entries]
            for future in futures:
                result = future.result()
                results.append(result)
                print(f"  {result.key:22s} {result.status:14s} {result.error[:70]}", flush=True)
                _dump_status(results, out_dir)
    else:
        for entry in entries:
            print(f"  {entry.key} …", end="  ", flush=True)
            result = _settle(entry)
            results.append(result)
            print(f"{result.status} {result.error[:70]}", flush=True)
            _dump_status(results, out_dir)

    _dump_status(results, out_dir)
    failed = [r.key for r in results if r.status not in ("ok", "fail_closed")]
    print(f"\ndone: {len(results) - len(failed)}/{len(results)} ok", end="")
    if failed:
        print(f"  FAILED: {', '.join(failed)}")
        return 1
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
