"""A compact, LLM-ready summary of a session's decision log.

An LLM is good at reading reasons and poor at arithmetic over thousands of rows, so the
split is: this module counts (outcomes, blocks, regime time, forward returns of executed
vs blocked signals, near-misses), and the model gets those numbers plus the narratives
of the bars that matter. Everything here is a pure function over the JSON rows written
by `JsonlDecisionLogWriter`, so it works on old files, on an export, or on rows the
dashboard already holds.

Forward returns are measured close-to-close on the session's own later bar records:
`+N` = the close N `bar_decision` rows after the signal bar, signed by the signal side
(a SELL that was followed by a fall scores positive). They are diagnostics of the filter,
not a backtest: no fees, no stops, no sizing.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

from nautilus_lab.application.decision_narrative import render_narrative
from nautilus_lab.application.decision_trace_codec import upgrade_row

#: Outcomes where the robot wanted a new position and got it.
EXECUTED = frozenset({"ENTRY_OPENED", "REVERSE"})
#: Outcomes where the robot wanted a new position and something stopped it.
BLOCKED = frozenset(
    {
        "ENTRY_BLOCKED_RISK",
        "ENTRY_SKIPPED_PAUSED",
        "ENTRY_SKIPPED_SIZE",
        "AUTO_TRADE_OFF",
        "SESSION_INACTIVE",
    }
)
#: Bars that are worth reading in full.
NOTABLE = frozenset(
    EXECUTED
    | BLOCKED
    | {
        "EXIT",
        "FLATTEN_REGIME_CHANGE",
        "STOP_LOSS",
        "TAKE_PROFIT",
        "MANUAL_CLOSE",
        "STOPS_UPDATED",
        "PAUSED",
        "RESUMED",
        "ERROR",
    }
)
DEFAULT_HORIZONS: tuple[int, ...] = (1, 4, 24)
#: A strategy step this close to its trigger (percent of price) counts as a near-miss.
NEAR_MISS_PCT = 0.2
#: Below this many signals a pattern is reported as a hypothesis, not a finding.
MIN_SIGNALS_FOR_FINDING = 30


@dataclass(frozen=True, slots=True)
class ForwardStats:
    n: int
    mean_pct: float | None
    median_pct: float | None
    hit_rate: float | None


@dataclass
class DecisionDigest:
    session_id: str | None
    robots: list[str]
    instruments: list[str]
    first_ts: str | None
    last_ts: str | None
    bars: int
    bar_seq_gaps: int
    outcomes: dict[str, int]
    blocked_by: dict[str, int]
    regime_share_pct: dict[str, float]
    regime_switches: int
    regime_flip_flops: int
    signals: dict[str, int]
    forward: dict[str, dict[str, ForwardStats]]
    near_misses: int
    near_miss_examples: list[str]
    intrabar: dict[str, int]
    config_hashes: list[str]
    v0_rows: int
    narratives: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            key: getattr(self, key) for key in self.__dataclass_fields__ if key != "forward"
        }
        out["forward"] = {
            group: {h: _stats_dict(stats) for h, stats in by_h.items()}
            for group, by_h in self.forward.items()
        }
        return out


def _stats_dict(stats: ForwardStats) -> dict[str, Any]:
    return {
        "n": stats.n,
        "mean_pct": stats.mean_pct,
        "median_pct": stats.median_pct,
        "hit_rate": stats.hit_rate,
    }


def _close(row: Mapping[str, Any]) -> float | None:
    raw = row.get("close")
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _forward_stats(values: Sequence[float]) -> ForwardStats:
    if not values:
        return ForwardStats(0, None, None, None)
    return ForwardStats(
        n=len(values),
        mean_pct=round(statistics.fmean(values), 4),
        median_pct=round(statistics.median(values), 4),
        hit_rate=round(sum(1 for v in values if v > 0) / len(values), 4),
    )


def _near_miss(row: Mapping[str, Any]) -> str | None:
    """A strategy that evaluated and held, within NEAR_MISS_PCT of its breakout level."""
    for item in row.get("steps") or []:
        if item.get("stage") != "strategy" or item.get("verdict") != "info":
            continue
        dist = (item.get("values") or {}).get("dist_to_breakout_pct")
        if isinstance(dist, (int, float)) and abs(dist) <= NEAR_MISS_PCT:
            return f"{row.get('ts')} {item.get('component')} {dist:+.3f}% до пробою"
    return None


def build_digest(
    rows: Iterable[Mapping[str, Any]],
    *,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    max_narratives: int = 60,
    no_signal_samples: int = 8,
) -> DecisionDigest:
    """Count what the robot did and why over the given rows (any order, any schema)."""
    upgraded = [upgrade_row(row) for row in rows]
    upgraded.sort(key=lambda r: (str(r.get("ts", "")), 0 if r.get("kind") == "intrabar" else 1))
    bars = [r for r in upgraded if r.get("kind", "bar_decision") == "bar_decision"]
    intrabar = [r for r in upgraded if r.get("kind") == "intrabar"]

    outcomes = Counter(str(r.get("outcome")) for r in upgraded if r.get("outcome"))
    blocked_by = Counter(str(r["blocked_by"]) for r in upgraded if r.get("blocked_by"))
    signals = Counter(str(r.get("signal")) for r in bars if r.get("signal"))

    regimes = [str(r.get("regime") or "UNKNOWN") for r in bars]
    regime_counts = Counter(regimes)
    trading_regimes = [g for g in regimes if g not in ("WARMUP", "UNKNOWN", "")]
    switches = sum(1 for a, b in pairwise(trading_regimes) if a != b)
    flip_flops = sum(
        1
        for i in range(2, len(trading_regimes))
        if trading_regimes[i] == trading_regimes[i - 2] != trading_regimes[i - 1]
    )

    seqs = [seq for seq in (r.get("bar_seq") for r in bars) if isinstance(seq, int)]
    gaps = sum(1 for a, b in pairwise(seqs) if b - a > 1)

    closes = [_close(r) for r in bars]
    forward: dict[str, dict[str, list[float]]] = {
        "executed": {f"+{h}": [] for h in horizons},
        "blocked": {f"+{h}": [] for h in horizons},
    }
    for index, row in enumerate(bars):
        outcome = str(row.get("outcome"))
        group = "executed" if outcome in EXECUTED else "blocked" if outcome in BLOCKED else None
        side = row.get("signal")
        entry = closes[index]
        if group is None or side not in ("buy", "sell") or not entry:
            continue
        sign = 1.0 if side == "buy" else -1.0
        for h in horizons:
            later = closes[index + h] if index + h < len(closes) else None
            if later is not None:
                forward[group][f"+{h}"].append(sign * (later - entry) / entry * 100.0)

    near = [text for text in (_near_miss(r) for r in bars) if text]

    notable = [r for r in upgraded if str(r.get("outcome")) in NOTABLE]
    quiet = [r for r in bars if str(r.get("outcome")) in ("NO_SIGNAL", "HOLD_NOOP")]
    step_every = max(1, len(quiet) // max(1, no_signal_samples))
    sampled = quiet[::step_every][:no_signal_samples]
    chosen = sorted(
        notable[-max_narratives:] + sampled,
        key=lambda r: str(r.get("ts", "")),
    )
    narratives = [str(r.get("narrative") or render_narrative(r)) for r in chosen]

    total_bars = len(bars) or 1
    return DecisionDigest(
        session_id=next((r.get("session_id") for r in upgraded if r.get("session_id")), None),
        robots=sorted({str(r.get("robot")) for r in upgraded if r.get("robot")}),
        instruments=sorted({str(r.get("instrument")) for r in upgraded if r.get("instrument")}),
        first_ts=str(upgraded[0].get("ts")) if upgraded else None,
        last_ts=str(upgraded[-1].get("ts")) if upgraded else None,
        bars=len(bars),
        bar_seq_gaps=gaps,
        outcomes=dict(outcomes.most_common()),
        blocked_by=dict(blocked_by.most_common()),
        regime_share_pct={
            k: round(v / total_bars * 100.0, 1) for k, v in regime_counts.most_common()
        },
        regime_switches=switches,
        regime_flip_flops=flip_flops,
        signals=dict(signals.most_common()),
        forward={
            group: {h: _forward_stats(values) for h, values in by_h.items()}
            for group, by_h in forward.items()
        },
        near_misses=len(near),
        near_miss_examples=near[-10:],
        intrabar=dict(Counter(str(r.get("outcome")) for r in intrabar).most_common()),
        config_hashes=sorted({str(r["config_hash"]) for r in upgraded if r.get("config_hash")}),
        v0_rows=sum(1 for r in upgraded if r.get("schema") == "decision_trace/0"),
        narratives=narratives,
    )


def _fwd_line(label: str, stats: Mapping[str, ForwardStats]) -> str:
    cells = []
    for horizon, item in stats.items():
        if item.n == 0:
            cells.append(f"{horizon}: n=0")
        else:
            cells.append(
                f"{horizon}: n={item.n}, mean {item.mean_pct:+.3f}%, "
                f"median {item.median_pct:+.3f}%, hit {item.hit_rate:.0%}"
            )
    return f"- {label}: " + "; ".join(cells)


def digest_markdown(digest: DecisionDigest) -> str:
    """The digest as compact Markdown: what a person pastes into a chat, or the prompt body."""
    lines = [
        f"# Дайджест рішень: {digest.session_id or '—'}",
        "",
        f"- Роботи: {', '.join(digest.robots) or '—'}; інструменти: "
        f"{', '.join(digest.instruments) or '—'}",
        f"- Період: {digest.first_ts} … {digest.last_ts}; барів: {digest.bars}; "
        f"пропусків у bar_seq: {digest.bar_seq_gaps}",
        f"- Конфіги (config_hash): {', '.join(digest.config_hashes) or '—'}",
    ]
    if digest.v0_rows:
        lines.append(f"- Записів старого формату без кроків (v0): {digest.v0_rows}")
    lines += ["", "## Підсумки барів (outcome)", ""]
    lines += [f"- {k}: {v}" for k, v in digest.outcomes.items()] or ["- —"]
    lines += ["", "## Що блокувало входи (blocked_by)", ""]
    lines += [f"- {k}: {v}" for k, v in digest.blocked_by.items()] or ["- нічого"]
    lines += ["", "## Режими", ""]
    lines += [f"- {k}: {v}% барів" for k, v in digest.regime_share_pct.items()]
    lines.append(
        f"- Перемикань режиму: {digest.regime_switches}; «пилка» (A→B→A): "
        f"{digest.regime_flip_flops}"
    )
    lines += ["", "## Сигнали та форвард-прибуток (close-to-close, знак за стороною)", ""]
    lines += [f"- сигнали {k}: {v}" for k, v in digest.signals.items()]
    lines.append(_fwd_line("виконані", digest.forward.get("executed", {})))
    lines.append(_fwd_line("заблоковані", digest.forward.get("blocked", {})))
    lines += [
        "",
        f"## Майже-сигнали (≤ {NEAR_MISS_PCT}% до пробою): {digest.near_misses}",
        "",
    ]
    lines += [f"- {item}" for item in digest.near_miss_examples]
    if digest.intrabar:
        lines += ["", "## Події всередині бару", ""]
        lines += [f"- {k}: {v}" for k, v in digest.intrabar.items()]
    lines += ["", "## Міркування по ключових барах", ""]
    lines += [f"- {text}" for text in digest.narratives] or ["- —"]
    return "\n".join(lines)


SYSTEM_PROMPT = f"""Ти — аналітик торгових рішень робота в paper-режимі.
Тобі дають дайджест журналу рішень: цифри вже пораховані кодом, їх не перераховуй.
Правила:
1. Кожне твердження підкріплюй цифрою з дайджесту або часом бару (ts).
2. Якщо сигналів менше {MIN_SIGNALS_FOR_FINDING}, формулюй висновки як гіпотези, а не факти.
3. Не радь міняти параметри напряму: пропонуй гіпотези для бектесту (що змінити, як перевірити,
   яка метрика підтвердить).
4. Форвард-прибутки — діагностика фільтрів без комісій і стопів, не результат стратегії.
5. Відповідай українською, коротко, з розділами: Що сталося / Чому / Що перевірити.
"""

PRESET_QUESTIONS: dict[str, str] = {
    "why_no_trades": "Чому за період угод не було (або було мало/забагато)? Що саме заважало?",
    "blocking_filter": (
        "Який фільтр або гейт блокує найчастіше і чи рятувало це від збитків "
        "(порівняй форвард-прибуток виконаних і заблокованих сигналів)?"
    ),
    "regime_quality": "Де режим перемикався запізно або хаотично («пилка»)? Наведи бари.",
    "hypotheses": "Які 3 гіпотези для бектесту випливають з цього журналу?",
}


def build_prompt(digest: DecisionDigest, question: str) -> tuple[str, str]:
    """(system, user) messages for `ChatCompleter.complete`."""
    user = f"{digest_markdown(digest)}\n\n## Питання\n\n{question.strip()}\n"
    return SYSTEM_PROMPT, user


def digest_json(digest: DecisionDigest) -> str:
    return json.dumps(digest.as_dict(), ensure_ascii=False, indent=2, default=str)
