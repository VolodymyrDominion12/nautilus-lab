#!/usr/bin/env python3
"""run_matrix.py — запускає матрицю бектестів з чистої ревізії.

Вимоги (хвиля 4, план після провалу валідації):
  * Відмовляє на брудному git-дереві (+dirty).  Матриця, що бігла на кількох
    різних ревізіях, дає непорівнювані числа: порівнювати їх — p-hacking.
  * Логує кожен прогін у reports/matrix/ з іменем у форматі
    <tier>_<robot>_<symbol>_<interval>.log
  * Пишіть нову матрицю як набір конфігурацій нижче, НЕ редагуючи цей скрипт
    у середині прогону.

Використання:
    uv run python scripts/run_matrix.py [--tier A] [--dry-run]

  --tier A      запустити лише тір A (за замовчуванням — усі)
  --dry-run     показати команди без виконання
  --register    лише преєструвати умови (`lab research --register <hypothesis>`) для
                прогонів, у яких задано `hypothesis`; бектести не біжать. Запускати
                ДО справжнього прогону того самого тіру (docs/33 §3).
  --force-dirty дозволити брудне дерево (ТІЛЬКИ для локальної налагодження,
                ніколи не для реальної матриці)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


# ── Конфігурація матриці ──────────────────────────────────────────────────────
@dataclass(frozen=True)
class MatrixRun:
    tier: str
    robot: str
    symbol: str  # Binance symbol, напр. BTCUSDT
    interval: str  # 1h / 4h / 1d
    extra_args: tuple[str, ...] = ()
    env_vars: tuple[tuple[str, str], ...] = ()
    #: Short name of the variant when one tier runs several configs of the same cell.
    variant: str = ""
    #: Text for `lab research --register`; empty = this run is not pre-registered.
    hypothesis: str = ""

    @property
    def label(self) -> str:
        base = f"{self.tier}_{self.robot}_{self.symbol}_{self.interval}"
        return f"{base}_{self.variant}" if self.variant else base


# ── Тір C (docs/33): підтвердження H0/H3 на монетах, яких аналіз не бачив ──────
# H0 = regime лише з трендовими ногами; H3 = H0 + HTF-нахил + розширення волатильності.
# Обидва фільтри знайдено на OOS BTC/ETH 1h (батчі 20261001, 20261002), тож чесна
# перевірка — інші монети. На 4h вікна фільтрів перераховано на той самий календарний
# проміжок: EMA200x1h ~ EMA50x4h, нахил 24h = 6 барів, ATR 24/300 x1h = 6/75 x4h.
_C_COINS = ("SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT")
_C_TREND_LEGS = (("REGIME_LEGS", "uptrend,downtrend"),)
_C_FILTERS_1H = (
    ("ENTRY_FILTER_HTF_TREND", "true"),
    ("ENTRY_FILTER_HTF_EMA_PERIOD", "200"),
    ("ENTRY_FILTER_HTF_SLOPE_LOOKBACK", "24"),
    ("ENTRY_FILTER_VOL_EXPANSION", "true"),
    ("ENTRY_FILTER_VOL_FAST_PERIOD", "24"),
    ("ENTRY_FILTER_VOL_SLOW_PERIOD", "300"),
    ("ENTRY_FILTER_MIN_VOL_RATIO", "1"),
)
_C_FILTERS_4H = (
    ("ENTRY_FILTER_HTF_TREND", "true"),
    ("ENTRY_FILTER_HTF_EMA_PERIOD", "50"),
    ("ENTRY_FILTER_HTF_SLOPE_LOOKBACK", "6"),
    ("ENTRY_FILTER_VOL_EXPANSION", "true"),
    ("ENTRY_FILTER_VOL_FAST_PERIOD", "6"),
    ("ENTRY_FILTER_VOL_SLOW_PERIOD", "75"),
    ("ENTRY_FILTER_MIN_VOL_RATIO", "1"),
)
_C_HYPOTHESIS = {
    "H0": "H0 regime trend legs only (no range leg) beats vol-matched buy&hold",
    "H3": (
        "H3 regime trend legs + slow-EMA slope gate + vol-expansion gate beats vol-matched buy&hold"
    ),
}


def _tier_c() -> tuple[MatrixRun, ...]:
    runs: list[MatrixRun] = []
    for interval, catalog, filters in (
        ("1h", "catalog", _C_FILTERS_1H),
        ("4h", "catalog_2019_4h", _C_FILTERS_4H),
    ):
        for coin in _C_COINS:
            for variant, env in (("H0", _C_TREND_LEGS), ("H3", _C_TREND_LEGS + filters)):
                runs.append(
                    MatrixRun(
                        "C",
                        "regime",
                        coin,
                        interval,
                        ("--folds", "6", "--days", "1000", "--catalog", catalog),
                        env,
                        variant=variant,
                        hypothesis=f"{_C_HYPOTHESIS[variant]} [{coin} {interval}]",
                    )
                )
    return tuple(runs)


# ── Тір G (2026-10-09): глобальний тренд — не входити проти денної SMA200 ─────────
# G0 = regime як є (усі ноги, без фільтрів) — контроль; G1 = те саме + ворота
# ENTRY_FILTER_GLOBAL_TREND (SMA200 денних закриттів, смуга ±2%, warmup=allow).
# Змінено лише вхід: виходи, стопи, перемикання режимів — без змін.
# 4h `catalog_2019_4h` без --days = уся історія з 2019 (бичі й ведмежі фази, розвороти
# 2021/2022/2023) — головна перевірка. 1h --days 1000 — додаткова, коротша.
# Монети тіру C: аналіз, з якого виросла ідея, бачив лише BTC/ETH.
_G_COINS = _C_COINS
_G_GLOBAL_TREND = (
    ("ENTRY_FILTER_GLOBAL_TREND", "true"),
    ("ENTRY_FILTER_GLOBAL_TREND_TIMEFRAME", "1d"),
    ("ENTRY_FILTER_GLOBAL_TREND_PERIOD", "200"),
    ("ENTRY_FILTER_GLOBAL_TREND_MA", "sma"),
    ("ENTRY_FILTER_GLOBAL_TREND_BAND_PCT", "0.02"),
    ("ENTRY_FILTER_GLOBAL_TREND_WARMUP", "allow"),
)
_G_HYPOTHESIS = {
    "G0": "G0 regime baseline (all legs, no gates) — control for G1",
    "G1": (
        "G1 regime + global-trend gate (no entry against daily SMA200, band 2%) beats G0 "
        "on OOS net return and max drawdown, and beats vol-matched buy&hold"
    ),
}


def _tier_g() -> tuple[MatrixRun, ...]:
    runs: list[MatrixRun] = []
    for interval, extra in (
        ("4h", ("--folds", "6", "--catalog", "catalog_2019_4h")),
        ("1h", ("--folds", "6", "--days", "1000", "--catalog", "catalog")),
    ):
        for coin in _G_COINS:
            # G0 вимикає ворота явно: змінна середовища б'є значення з .env.
            for variant, env in (
                ("G0", (("ENTRY_FILTER_GLOBAL_TREND", "false"),)),
                ("G1", _G_GLOBAL_TREND),
            ):
                runs.append(
                    MatrixRun(
                        "G",
                        "regime",
                        coin,
                        interval,
                        extra,
                        env,
                        variant=variant,
                        hypothesis=f"{_G_HYPOTHESIS[variant]} [{coin} {interval}]",
                    )
                )
    return tuple(runs)


MATRIX: tuple[MatrixRun, ...] = (
    # Phase 4.1 - EMA with vol_scaling on 10 coins, 1d (6 folds)
    MatrixRun(
        "4_1",
        "ema",
        "BTCUSDT",
        "1d",
        ("--folds", "6", "--catalog", "catalog_2019_1d"),
        (("USE_VOL_SCALING", "true"),),
    ),
    MatrixRun(
        "4_1",
        "ema",
        "ETHUSDT",
        "1d",
        ("--folds", "6", "--catalog", "catalog_2019_1d"),
        (("USE_VOL_SCALING", "true"),),
    ),
    MatrixRun(
        "4_1",
        "ema",
        "BNBUSDT",
        "1d",
        ("--folds", "6", "--catalog", "catalog_2019_1d"),
        (("USE_VOL_SCALING", "true"),),
    ),
    MatrixRun(
        "4_1",
        "ema",
        "SOLUSDT",
        "1d",
        ("--folds", "6", "--catalog", "catalog_2019_1d"),
        (("USE_VOL_SCALING", "true"),),
    ),
    MatrixRun(
        "4_1",
        "ema",
        "XRPUSDT",
        "1d",
        ("--folds", "6", "--catalog", "catalog_2019_1d"),
        (("USE_VOL_SCALING", "true"),),
    ),
    MatrixRun(
        "4_1",
        "ema",
        "ADAUSDT",
        "1d",
        ("--folds", "6", "--catalog", "catalog_2019_1d"),
        (("USE_VOL_SCALING", "true"),),
    ),
    MatrixRun(
        "4_1",
        "ema",
        "DOTUSDT",
        "1d",
        ("--folds", "6", "--catalog", "catalog_2019_1d"),
        (("USE_VOL_SCALING", "true"),),
    ),
    MatrixRun(
        "4_1",
        "ema",
        "AVAXUSDT",
        "1d",
        ("--folds", "6", "--catalog", "catalog_2019_1d"),
        (("USE_VOL_SCALING", "true"),),
    ),
    MatrixRun(
        "4_1",
        "ema",
        "MATICUSDT",
        "1d",
        ("--folds", "6", "--catalog", "catalog_2019_1d"),
        (("USE_VOL_SCALING", "true"),),
    ),
    MatrixRun(
        "4_1",
        "ema",
        "LINKUSDT",
        "1d",
        ("--folds", "6", "--catalog", "catalog_2019_1d"),
        (("USE_VOL_SCALING", "true"),),
    ),
    # Phase 4.1 PBO for promising candidates
    MatrixRun(
        "4_1_PBO",
        "ema",
        "SOLUSDT",
        "1d",
        ("--folds", "6", "--pbo", "--catalog", "catalog_2019_1d"),
        (("USE_VOL_SCALING", "true"),),
    ),
    MatrixRun(
        "4_1_PBO",
        "ema",
        "MATICUSDT",
        "1d",
        ("--folds", "6", "--pbo", "--catalog", "catalog_2019_1d"),
        (("USE_VOL_SCALING", "true"),),
    ),
    # Phase 4.2 - Regime router 6-fold validation on major pairs
    MatrixRun("4_2", "regime", "BTCUSDT", "4h", ("--folds", "6", "--catalog", "catalog_2019_4h")),
    MatrixRun("4_2", "regime", "ETHUSDT", "4h", ("--folds", "6", "--catalog", "catalog_2019_4h")),
    MatrixRun("4_2", "regime", "SOLUSDT", "4h", ("--folds", "6", "--catalog", "catalog_2019_4h")),
    MatrixRun("4_2", "regime", "BNBUSDT", "4h", ("--folds", "6", "--catalog", "catalog_2019_4h")),
    # Phase 4.2 PBO audits for the same pairs
    MatrixRun(
        "4_2_PBO",
        "regime",
        "BTCUSDT",
        "4h",
        ("--folds", "6", "--pbo", "--catalog", "catalog_2019_4h"),
    ),
    MatrixRun(
        "4_2_PBO",
        "regime",
        "ETHUSDT",
        "4h",
        ("--folds", "6", "--pbo", "--catalog", "catalog_2019_4h"),
    ),
    MatrixRun(
        "4_2_PBO",
        "regime",
        "SOLUSDT",
        "4h",
        ("--folds", "6", "--pbo", "--catalog", "catalog_2019_4h"),
    ),
    MatrixRun(
        "4_2_PBO",
        "regime",
        "BNBUSDT",
        "4h",
        ("--folds", "6", "--pbo", "--catalog", "catalog_2019_4h"),
    ),
    # Phase 4.3 - Funding carry 4h
    MatrixRun(
        "4_3",
        "funding",
        "BTCUSDT",
        "4h",
        ("--folds", "6", "--catalog", "catalog_2019_4h"),
        (
            ("FUNDING_SPOT_ID", "BTC/USDT.SIM"),
            ("FUNDING_PERP_ID", "BTCUSDT-PERP.SIM"),
        ),
    ),
    MatrixRun(
        "4_3",
        "funding",
        "ETHUSDT",
        "4h",
        ("--folds", "6", "--catalog", "catalog_2019_4h"),
        (
            ("FUNDING_SPOT_ID", "ETH/USDT.SIM"),
            ("FUNDING_PERP_ID", "ETHUSDT-PERP.SIM"),
        ),
    ),
    *_tier_c(),
    *_tier_g(),
)
# ─────────────────────────────────────────────────────────────────────────────


def _git_is_dirty(repo_root: Path) -> bool:
    """True якщо робоче дерево має незакомічені зміни."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def _git_revision(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or "unknown"


def _build_command(run: MatrixRun, lab: str, *, register: bool = False) -> list[str]:
    """Побудувати команду `lab research` для одного прогону.

    `register=True` дописує `--register <hypothesis>`: ті самі умови й env, але замість
    бектесту лише запис термінів у research/preregistrations/.
    """
    cmd = [
        lab,
        "research",
        "--robot",
        run.robot,
    ]
    cmd.extend(run.extra_args)
    if register:
        if not run.hypothesis:
            raise ValueError(f"{run.label}: --register needs a hypothesis on the run")
        cmd.extend(("--register", run.hypothesis))
    return cmd


def _run_all(
    runs: list[MatrixRun],
    *,
    repo_root: Path,
    out_dir: Path,
    dry_run: bool,
    register: bool = False,
) -> int:
    lab = str(repo_root / ".venv" / "bin" / "lab")
    revision = _git_revision(repo_root)
    started_at = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")

    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"matrix revision={revision} runs={len(runs)} out={out_dir}")
    print(f"started_at={started_at}")
    print()

    failures: list[str] = []
    for run in runs:
        cmd = _build_command(run, lab, register=register)
        suffix = ".register.log" if register else ".log"
        log_path = out_dir / f"{run.label}{suffix}"
        print(f"  [{run.tier}] {run.label}", end="  ", flush=True)
        if dry_run:
            env_note = " ".join(f"{k}={v}" for k, v in run.env_vars)
            print(f"(dry-run) {' '.join(cmd)}" + (f"  [env: {env_note}]" if env_note else ""))
            continue
        try:
            env = dict(os.environ)
            # Map BTCUSDT -> BTC/USDT.SIM
            base = run.symbol.replace("USDT", "")
            instrument_id = f"{base}/USDT.SIM"
            env["INSTRUMENT_ID"] = instrument_id

            env["BAR_INTERVAL"] = run.interval
            env.update(run.env_vars)

            # Map interval 4h -> 4-HOUR, 1h -> 1-HOUR, 1d -> 1-DAY
            interval_str = run.interval.upper()
            if interval_str == "4H":
                interval_str = "4-HOUR"
            elif interval_str == "1H":
                interval_str = "1-HOUR"
            elif interval_str == "1D":
                interval_str = "1-DAY"

            env["BAR_TYPE"] = f"{instrument_id}-{interval_str}-LAST-EXTERNAL"

            with log_path.open("w") as log_fh:
                log_fh.write(f"# revision={revision} started={started_at}\n")
                log_fh.write(
                    f"# env: INSTRUMENT_ID={env['INSTRUMENT_ID']} "
                    f"BAR_INTERVAL={env['BAR_INTERVAL']} BAR_TYPE={env['BAR_TYPE']}\n"
                )
                log_fh.write(f"# cmd={' '.join(cmd)}\n\n")
                proc = subprocess.run(
                    cmd,
                    cwd=repo_root,
                    env=env,
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    timeout=3600,
                )
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            print("TIMEOUT")
            failures.append(run.label)
            continue
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: {exc}")
            failures.append(run.label)
            continue

        status = "OK" if exit_code == 0 else f"FAIL(exit={exit_code})"
        print(status)
        if exit_code != 0:
            failures.append(run.label)

        # Показати останні 5 рядків логу
        try:
            lines = log_path.read_text().splitlines()
            for line in lines[-5:]:
                print(f"    {line}")
        except OSError:
            pass
        print()

    print(f"\nDone: {len(runs) - len(failures)}/{len(runs)} OK", end="")
    if failures:
        print(f"  FAILED: {', '.join(failures)}")
        return 1
    print()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Запускає матрицю бектестів з обов'язковою перевіркою чистоти дерева."
    )
    parser.add_argument(
        "--tier",
        metavar="TIER",
        help="Запустити лише вказаний тір (наприклад, A або B). За замовчуванням — усі.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Показати команди без виконання.",
    )
    parser.add_argument(
        "--force-dirty",
        action="store_true",
        help=(
            "Дозволити брудне дерево. НЕБЕЗПЕЧНО: використовувати лише для "
            "локальної налагодження, ніколи для реальної матриці."
        ),
    )
    parser.add_argument(
        "--register",
        action="store_true",
        help=(
            "Лише преєструвати умови прогонів, у яких задано hypothesis "
            "(lab research --register). Запускати до справжнього прогону."
        ),
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent

    # ── Перевірка чистоти дерева (головний запобіжник) ──────────────────────
    if not args.dry_run and _git_is_dirty(repo_root):
        if args.force_dirty:
            print(
                "WARNING: дерево брудне (+dirty). Результати НЕПОРІВНЮВАНІ з "
                "іншими ревізіями. Продовжую через --force-dirty.",
                file=sys.stderr,
            )
        else:
            print(
                "ERROR: git-дерево брудне (+dirty). Матриця відмовляється стартувати.\n"
                "\n"
                "Причина: матриця, яка бігла на різних ревізіях, дає непорівнювані\n"
                "числа — саме це зробило попередню матрицю нечитаною.\n"
                "\n"
                "Що зробити:\n"
                "  git add -A && git commit -m 'wave-N: опис змін'\n"
                "  або\n"
                "  git stash  (якщо зміни тимчасові)\n"
                "\n"
                "Якщо ДІЙСНО потрібно запустити на брудному дереві (налагодження),\n"
                "додайте --force-dirty. Ніколи не використовуйте цей прапор для\n"
                "реальної матриці.",
                file=sys.stderr,
            )
            return 1

    # ── Фільтр за тіром ──────────────────────────────────────────────────────
    runs = list(MATRIX)
    if args.tier:
        tier = args.tier.upper()
        runs = [r for r in runs if r.tier == tier]
        if not runs:
            print(
                f"ERROR: тір {args.tier!r} не знайдено в матриці. "
                f"Доступні: {sorted({r.tier for r in MATRIX})}",
                file=sys.stderr,
            )
            return 1

    if args.register:
        runs = [r for r in runs if r.hypothesis]
        if not runs:
            print("ERROR: у вибраних прогонах немає hypothesis для --register", file=sys.stderr)
            return 1

    out_dir = repo_root / "reports" / "matrix"
    return _run_all(
        runs, repo_root=repo_root, out_dir=out_dir, dry_run=args.dry_run, register=args.register
    )


if __name__ == "__main__":
    sys.exit(main())
