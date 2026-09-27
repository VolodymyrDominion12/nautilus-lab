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

    @property
    def label(self) -> str:
        return f"{self.tier}_{self.robot}_{self.symbol}_{self.interval}"


MATRIX: tuple[MatrixRun, ...] = (
    # Phase 4.1 - EMA with vol_scaling on 10 coins, 1d (6 folds)
    MatrixRun("4_1", "ema", "BTCUSDT", "1d", ("--folds", "6", "--catalog", "catalog_2019_1d"), (("USE_VOL_SCALING", "true"),)),
    MatrixRun("4_1", "ema", "ETHUSDT", "1d", ("--folds", "6", "--catalog", "catalog_2019_1d"), (("USE_VOL_SCALING", "true"),)),
    MatrixRun("4_1", "ema", "BNBUSDT", "1d", ("--folds", "6", "--catalog", "catalog_2019_1d"), (("USE_VOL_SCALING", "true"),)),
    MatrixRun("4_1", "ema", "SOLUSDT", "1d", ("--folds", "6", "--catalog", "catalog_2019_1d"), (("USE_VOL_SCALING", "true"),)),
    MatrixRun("4_1", "ema", "XRPUSDT", "1d", ("--folds", "6", "--catalog", "catalog_2019_1d"), (("USE_VOL_SCALING", "true"),)),
    MatrixRun("4_1", "ema", "ADAUSDT", "1d", ("--folds", "6", "--catalog", "catalog_2019_1d"), (("USE_VOL_SCALING", "true"),)),
    MatrixRun("4_1", "ema", "DOTUSDT", "1d", ("--folds", "6", "--catalog", "catalog_2019_1d"), (("USE_VOL_SCALING", "true"),)),
    MatrixRun("4_1", "ema", "AVAXUSDT", "1d", ("--folds", "6", "--catalog", "catalog_2019_1d"), (("USE_VOL_SCALING", "true"),)),
    MatrixRun("4_1", "ema", "MATICUSDT", "1d", ("--folds", "6", "--catalog", "catalog_2019_1d"), (("USE_VOL_SCALING", "true"),)),
    MatrixRun("4_1", "ema", "LINKUSDT", "1d", ("--folds", "6", "--catalog", "catalog_2019_1d"), (("USE_VOL_SCALING", "true"),)),

    # Phase 4.1 PBO for promising candidates
    MatrixRun("4_1_PBO", "ema", "SOLUSDT", "1d", ("--folds", "6", "--pbo", "--catalog", "catalog_2019_1d"), (("USE_VOL_SCALING", "true"),)),
    MatrixRun("4_1_PBO", "ema", "MATICUSDT", "1d", ("--folds", "6", "--pbo", "--catalog", "catalog_2019_1d"), (("USE_VOL_SCALING", "true"),)),

    # Phase 4.2 - Regime router 6-fold validation on major pairs
    MatrixRun("4_2", "regime", "BTCUSDT", "4h", ("--folds", "6", "--catalog", "catalog_2019_4h")),
    MatrixRun("4_2", "regime", "ETHUSDT", "4h", ("--folds", "6", "--catalog", "catalog_2019_4h")),
    MatrixRun("4_2", "regime", "SOLUSDT", "4h", ("--folds", "6", "--catalog", "catalog_2019_4h")),
    MatrixRun("4_2", "regime", "BNBUSDT", "4h", ("--folds", "6", "--catalog", "catalog_2019_4h")),
    
    # Phase 4.2 PBO audits for the same pairs
    MatrixRun("4_2_PBO", "regime", "BTCUSDT", "4h", ("--folds", "6", "--pbo", "--catalog", "catalog_2019_4h")),
    MatrixRun("4_2_PBO", "regime", "ETHUSDT", "4h", ("--folds", "6", "--pbo", "--catalog", "catalog_2019_4h")),
    MatrixRun("4_2_PBO", "regime", "SOLUSDT", "4h", ("--folds", "6", "--pbo", "--catalog", "catalog_2019_4h")),
    MatrixRun("4_2_PBO", "regime", "BNBUSDT", "4h", ("--folds", "6", "--pbo", "--catalog", "catalog_2019_4h")),

    # Phase 4.3 - Funding carry 4h
    MatrixRun("4_3", "funding", "BTCUSDT", "4h", ("--folds", "4", "--catalog", "catalog_2019_4h"), (
        ("FUNDING_SPOT_ID", "BTC/USDT.SIM"),
        ("FUNDING_PERP_ID", "BTCUSDT-PERP.SIM"),
    )),
    MatrixRun("4_3", "funding", "ETHUSDT", "4h", ("--folds", "4", "--catalog", "catalog_2019_4h"), (
        ("FUNDING_SPOT_ID", "ETH/USDT.SIM"),
        ("FUNDING_PERP_ID", "ETHUSDT-PERP.SIM"),
    )),
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


def _build_command(run: MatrixRun, lab: str) -> list[str]:
    """Побудувати команду `lab research` для одного прогону."""
    cmd = [
        lab,
        "research",
        "--robot",
        run.robot,
    ]
    cmd.extend(run.extra_args)
    return cmd


def _run_all(
    runs: list[MatrixRun],
    *,
    repo_root: Path,
    out_dir: Path,
    dry_run: bool,
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
        cmd = _build_command(run, lab)
        log_path = out_dir / f"{run.label}.log"
        print(f"  [{run.tier}] {run.label}", end="  ", flush=True)
        if dry_run:
            print(f"(dry-run) {' '.join(cmd)}")
            continue
        try:
            env = dict(os.environ)
            # Map BTCUSDT -> BTC/USDT.SIM
            base = run.symbol.replace("USDT", "")
            instrument_id = f"{base}/USDT.SIM"
            env["INSTRUMENT_ID"] = instrument_id

            env["BAR_INTERVAL"] = run.interval
            for k, v in run.env_vars:
                env[k] = v

            
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
                log_fh.write(f"# env: INSTRUMENT_ID={env['INSTRUMENT_ID']} BAR_INTERVAL={env['BAR_INTERVAL']} BAR_TYPE={env['BAR_TYPE']}\n")
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

    out_dir = repo_root / "reports" / "matrix"
    return _run_all(runs, repo_root=repo_root, out_dir=out_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
