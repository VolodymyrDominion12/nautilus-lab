"""Leaderboard of best backtests.

A leaderboard records and ranks backtest runs so researchers can:
1. Discover the top-performing strategies and parameter sets across instruments and timeframes.
2. Compare out-of-sample (OOS) performance against the buy & hold benchmark.
3. Fully reproduce any backtest using the recorded arguments, candle count, and CLI command.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from nautilus_lab.domain.provenance import RunManifest

LEADERBOARD_ROWS_START = "<!-- leaderboard:rows:start -->"
LEADERBOARD_ROWS_END = "<!-- leaderboard:rows:end -->"

_MAX_CELL = 80


@dataclass(frozen=True, slots=True)
class LeaderboardEntry:
    """One backtest run recorded in the leaderboard."""

    id: str
    recorded_at: datetime
    robot: str
    instrument_id: str
    timeframe: str
    bar_count: int
    source: str
    run_type: str
    folds: int
    # Performance metrics
    oos_return: Decimal | None
    buy_and_hold_return: Decimal | None
    excess_return: Decimal | None
    sharpe_ratio: Decimal | None
    max_drawdown: Decimal | None
    fills: int | None
    fees_paid: Decimal | None
    profitable_folds: str | None
    ending_balance: Decimal | None
    # Arguments & config for complete reproducibility
    strategy_params: dict[str, Any]
    run_args: dict[str, Any]
    reproduce_command: str
    provenance: RunManifest | None = None
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "recorded_at": self.recorded_at.astimezone(UTC).isoformat(),
            "robot": self.robot,
            "instrument_id": self.instrument_id,
            "timeframe": self.timeframe,
            "bar_count": self.bar_count,
            "source": self.source,
            "run_type": self.run_type,
            "folds": self.folds,
            "oos_return": str(self.oos_return) if self.oos_return is not None else None,
            "buy_and_hold_return": (
                str(self.buy_and_hold_return) if self.buy_and_hold_return is not None else None
            ),
            "excess_return": str(self.excess_return) if self.excess_return is not None else None,
            "sharpe_ratio": str(self.sharpe_ratio) if self.sharpe_ratio is not None else None,
            "max_drawdown": str(self.max_drawdown) if self.max_drawdown is not None else None,
            "fills": self.fills,
            "fees_paid": str(self.fees_paid) if self.fees_paid is not None else None,
            "profitable_folds": self.profitable_folds,
            "ending_balance": (
                str(self.ending_balance) if self.ending_balance is not None else None
            ),
            "strategy_params": self.strategy_params,
            "run_args": self.run_args,
            "reproduce_command": self.reproduce_command,
            "provenance": self.provenance.as_dict() if self.provenance is not None else None,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> LeaderboardEntry:
        def _dec(k: str) -> Decimal | None:
            val = payload.get(k)
            if val is None:
                return None
            return Decimal(str(val))

        raw_prov = payload.get("provenance")
        prov = (
            RunManifest.from_dict({str(k): v for k, v in raw_prov.items()})
            if isinstance(raw_prov, dict)
            else None
        )

        recorded_raw = payload.get("recorded_at")
        if isinstance(recorded_raw, str):
            recorded = datetime.fromisoformat(recorded_raw)
        else:
            recorded = datetime.now(UTC)

        return cls(
            id=str(payload.get("id") or uuid.uuid4().hex[:10]),
            recorded_at=recorded,
            robot=str(payload.get("robot") or ""),
            instrument_id=str(payload.get("instrument_id") or ""),
            timeframe=str(payload.get("timeframe") or ""),
            bar_count=int(payload.get("bar_count") or 0),
            source=str(payload.get("source") or "catalog"),
            run_type=str(payload.get("run_type") or "walk_forward"),
            folds=int(payload.get("folds") or 1),
            oos_return=_dec("oos_return"),
            buy_and_hold_return=_dec("buy_and_hold_return"),
            excess_return=_dec("excess_return"),
            sharpe_ratio=_dec("sharpe_ratio"),
            max_drawdown=_dec("max_drawdown"),
            fills=int(payload["fills"]) if payload.get("fills") is not None else None,
            fees_paid=_dec("fees_paid"),
            profitable_folds=str(payload["profitable_folds"])
            if payload.get("profitable_folds") is not None
            else None,
            ending_balance=_dec("ending_balance"),
            strategy_params=dict(payload.get("strategy_params") or {}),
            run_args=dict(payload.get("run_args") or {}),
            reproduce_command=str(payload.get("reproduce_command") or ""),
            provenance=prov,
            notes=str(payload.get("notes") or ""),
        )

    def format_params_summary(self) -> str:
        """Format strategy parameters concisely for table display."""
        if not self.strategy_params:
            return "-"
        items = [f"{k}={v}" for k, v in sorted(self.strategy_params.items())]
        res = ", ".join(items)
        if len(res) > _MAX_CELL:
            res = res[: _MAX_CELL - 3] + "..."
        return res

    def markdown_row(self, rank: int) -> str:
        oos = _fmt_pct(self.oos_return)
        bh = _fmt_pct(self.buy_and_hold_return)
        excess = _fmt_pct(self.excess_return)
        max_dd = _fmt_pct(self.max_drawdown)
        fills_str = str(self.fills) if self.fills is not None else "-"
        params_str = self.format_params_summary().replace("|", "/")
        cmd_snippet = f"`{self.reproduce_command}`" if self.reproduce_command else "-"

        cells = (
            str(rank),
            f"`{self.robot}`",
            f"`{self.instrument_id}`",
            f"`{self.timeframe}`",
            str(self.bar_count),
            f"**{oos}**",
            bh,
            excess,
            max_dd,
            fills_str,
            params_str,
            cmd_snippet,
        )
        return "| " + " | ".join(cells) + " |"


def format_leaderboard_pct(val: Decimal | None) -> str:
    if val is None:
        return "n/a"
    pct = val * Decimal("100")
    sign = "+" if pct > 0 else ""
    return f"{sign}{pct:.2f}%"


_fmt_pct = format_leaderboard_pct


def build_reproduce_command(
    *,
    robot: str,
    instrument_id: str,
    timeframe: str,
    bar_count: int,
    folds: int = 1,
    source: str = "catalog",
    catalog_path: str | None = None,
    strategy_params: dict[str, Any] | None = None,
    run_args: dict[str, Any] | None = None,
) -> str:
    """Build a copy-pasteable CLI command to reproduce the exact backtest."""
    parts: list[str] = []

    # Environment variables for strategy parameters if provided
    env_vars: list[str] = []
    if strategy_params:
        for k, v in sorted(strategy_params.items()):
            # Map common param names to env var names if not already uppercase
            env_name = k.upper()
            env_vars.append(f"{env_name}={v}")

    if env_vars:
        parts.append(" ".join(env_vars))

    parts.append("uv run lab research")
    parts.append(f"--robot {robot}")

    if source == "synthetic":
        parts.append("--synthetic")
        parts.append(f"--bars {bar_count}")
    else:
        if catalog_path and catalog_path != "catalog":
            parts.append(f"--catalog {catalog_path}")
        if instrument_id:
            parts.append(f"--instrument {instrument_id}")
        if timeframe:
            parts.append(f"--interval {timeframe}")

    if folds > 1:
        parts.append(f"--folds {folds}")

    if run_args:
        if run_args.get("use_optuna"):
            parts.append("--optuna")
            if run_args.get("optuna_trials"):
                parts.append(f"--trials {run_args['optuna_trials']}")
        if run_args.get("is_fraction") and Decimal(str(run_args["is_fraction"])) != Decimal("0.7"):
            parts.append(f"--is-fraction {run_args['is_fraction']}")
        if run_args.get("embargo_bars") and int(run_args["embargo_bars"]) != 10:
            parts.append(f"--embargo-bars {run_args['embargo_bars']}")
        if run_args.get("stress_slice"):
            parts.append(f"--slice {run_args['stress_slice']}")
        if run_args.get("bar_vpin"):
            parts.append("--bar-vpin")
        if run_args.get("tick_vpin"):
            parts.append("--tick-vpin")
        if run_args.get("hawkes"):
            parts.append("--hawkes")

    return " ".join(parts)


def rank_leaderboard_entries(
    entries: Sequence[LeaderboardEntry],
    sort_by: str = "oos",
) -> list[LeaderboardEntry]:
    """Sort entries by the given metric (descending for returns/sharpe, ascending for DD)."""
    sorted_list = list(entries)

    def _sort_key(item: LeaderboardEntry) -> tuple[Decimal, Decimal, int]:
        low = Decimal("-999999")
        if sort_by == "excess":
            primary = item.excess_return if item.excess_return is not None else low
        elif sort_by == "sharpe":
            primary = item.sharpe_ratio if item.sharpe_ratio is not None else low
        elif sort_by == "drawdown":
            # For drawdown, smaller magnitude is better (negative value preferred)
            primary = -item.max_drawdown if item.max_drawdown is not None else Decimal("999999")
        elif sort_by == "fills":
            primary = Decimal(item.fills) if item.fills is not None else low
        elif sort_by == "date":
            primary = Decimal(int(item.recorded_at.timestamp()))
        else:  # default 'oos'
            primary = item.oos_return if item.oos_return is not None else low

        # Secondary tie-breakers: excess return, fills
        secondary = item.excess_return if item.excess_return is not None else low
        fills = item.fills or 0
        return (primary, secondary, fills)

    sorted_list.sort(key=_sort_key, reverse=True)
    return sorted_list


def generate_markdown_leaderboard(
    entries: Sequence[LeaderboardEntry],
    top_n: int | None = None,
) -> str:
    """Generate the full research/leaderboard.md document content."""
    ranked = rank_leaderboard_entries(entries, sort_by="oos")
    if top_n is not None and top_n > 0:
        ranked = ranked[:top_n]

    lines: list[str] = [
        "# Лідерборд бектестів (Backtest Leaderboard)",
        "",
        "Таблиця найкращих перевірених бектестів за результатами Out-of-Sample (OOS).",
        "Кожен запис містить стратегію, інструмент, таймфрейм, кількість свічок, усі параметри",
        "запуску та готову CLI-команду для 100% точного відтворення.",
        "",
        "## Правила включення",
        (
            "- **In-sample — лише вибір, OOS — це звіт**: "
            "оцінка базується на out-of-sample або агрегаті фолдів."
        ),
        "- **Порівняння з Buy & Hold**: excess return відображає альфу над пасивним утриманням.",
        "- **Повна відтворюваність**: точні аргументи та зафіксована команда запуску.",
        "",
        (
            "| # | Стратегія | Інструмент | ТФ | Свічки | OOS Return | "
            "Buy&Hold | Excess | Max DD | Fills | Аргументи | Команда для відтворення |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
        LEADERBOARD_ROWS_START,
    ]

    for rank, entry in enumerate(ranked, start=1):
        lines.append(entry.markdown_row(rank))

    lines.append(LEADERBOARD_ROWS_END)
    lines.extend(
        [
            "",
            "## Як запустити відтворення",
            (
                "Щоб повторити будь-який бектест з таблиці, скопіюйте команду "
                "з останньої колонки або скористайтеся CLI:"
            ),
            "```bash",
            "uv run lab leaderboard --reproduce 1   # показати повну інструкцію відтворення топ-1",
            "uv run lab leaderboard                 # переглянути таблицю в терміналі",
            "```",
            "",
            "Також можна додати новий бектест до лідерборду прапорцем `--leaderboard`:",
            "```bash",
            "uv run lab research --robot regime --folds 4 --leaderboard",
            "```",
        ]
    )

    return "\n".join(lines) + "\n"


def load_leaderboard_entries(jsonl_path: Path) -> tuple[LeaderboardEntry, ...]:
    """Read all entries from the machine-readable JSONL log."""
    if not jsonl_path.exists():
        return ()
    entries: list[LeaderboardEntry] = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        trimmed = line.strip()
        if not trimmed:
            continue
        try:
            data = json.loads(trimmed)
            if isinstance(data, dict):
                entries.append(LeaderboardEntry.from_dict(data))
        except (json.JSONDecodeError, ValueError):
            continue
    return tuple(entries)


def append_leaderboard_record(jsonl_path: Path, entry: LeaderboardEntry) -> None:
    """Append one entry to the JSONL log."""
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry.as_dict(), ensure_ascii=False)
    with jsonl_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{line}\n")


def regenerate_markdown_file(
    markdown_path: Path,
    jsonl_path: Path,
    sort_by: str = "oos",
) -> None:
    """Regenerate the markdown table from the JSONL entries."""
    entries = load_leaderboard_entries(jsonl_path)
    ranked = rank_leaderboard_entries(entries, sort_by=sort_by)
    content = generate_markdown_leaderboard(ranked)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(content, encoding="utf-8")


def record_leaderboard_entry(
    *,
    markdown_path: Path,
    jsonl_path: Path,
    entry: LeaderboardEntry,
) -> None:
    """Add a new entry to the JSONL ledger and update the Markdown leaderboard table."""
    append_leaderboard_record(jsonl_path, entry)
    regenerate_markdown_file(markdown_path, jsonl_path)


_ROBOT_PARAM_NAMES: dict[str, tuple[str, ...]] = {
    "regime": (
        "fast_ema",
        "slow_ema",
        "donchian_period",
        "bb_period",
        "bb_k",
        "enter_trend_er",
        "exit_trend_er",
    ),
    "ema": ("fast_ema", "slow_ema", "ema_min_spread_pct"),
    "vpin_momentum": ("vpin_ema_period", "vpin_atr_multiple", "vpin_quantile"),
    "adaptive_ema": ("adaptive_period", "adaptive_selectivity"),
    "pairs": ("z_entry", "z_exit"),
    "formulaic_lgbm": ("formulaic_threshold",),
    "meta_label": ("meta_label_threshold",),
    "ml_obi": ("meta_label_threshold",),
    "funding": ("funding_min_net_apy", "funding_holding_periods"),
}


def strategy_params_for_robot(
    robot: str,
    selected: object | None = None,
    cfg_params: dict[str, object] | None = None,
) -> dict[str, object]:
    """Extract relevant strategy parameter dict from SelectedParams or Settings."""
    names = _ROBOT_PARAM_NAMES.get(
        robot,
        ("fast_ema", "slow_ema", "donchian_period", "bb_k"),
    )
    res: dict[str, object] = {}
    if selected is not None:
        for name in names:
            if hasattr(selected, name):
                val = getattr(selected, name)
                res[name] = str(val) if isinstance(val, Decimal) else val
    elif cfg_params is not None:
        for name in names:
            if name in cfg_params:
                val = cfg_params[name]
                res[name] = str(val) if isinstance(val, Decimal) else val
    return res
