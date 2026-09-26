"""The decision trace as a short Ukrainian paragraph: "bar closed, regime was X because…".

Rendered only from the recorded steps (never from the robot's own logic), so the text
cannot drift from what the code actually decided: if a step is missing, the sentence is
missing. Works on the JSON row (`decision_trace_codec.record_to_dict`), which is also
how old files are re-rendered.

Example:

    14:00 ETHUSDT закрито 2412.5. Позиція: FLAT. Режим UPTREND (ER 0.34 ≥ 0.3, нахил
    +12.1). VPIN 0.42 — потік нормальний. Donchian: close 2412.5 вище максимуму каналу
    2405 (+0.31%) → сигнал BUY. План: FLAT → вхід. Ризик-гейт ЗАБЛОКУВАВ: денний збиток
    3.1% ≥ ліміт 3%. Підсумок: вхід заблоковано ризиком.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

OUTCOME_UK: dict[str, str] = {
    "WARMUP": "прогрів індикаторів, рішень ще немає",
    "NO_SIGNAL": "сигналу немає",
    "HOLD_NOOP": "позиція вже відповідає сигналу, дій немає",
    "ENTRY_OPENED": "відкрито позицію",
    "EXIT": "позицію закрито",
    "REVERSE": "позицію перевернуто",
    "FLATTEN_REGIME_CHANGE": "закриття через зміну режиму",
    "ENTRY_BLOCKED_RISK": "вхід заблоковано ризиком",
    "ENTRY_SKIPPED_PAUSED": "вхід пропущено (пауза)",
    "ENTRY_SKIPPED_SIZE": "вхід пропущено (розмір позиції 0)",
    "AUTO_TRADE_OFF": "сигнал не виконано (автоторгівля вимкнена)",
    "SESSION_INACTIVE": "сигнал не виконано (сесія неактивна)",
    "STOP_LOSS": "спрацював стоп-лос",
    "TAKE_PROFIT": "спрацював тейк-профіт",
    "MANUAL_CLOSE": "позицію закрито вручну",
    "STOPS_UPDATED": "рівні SL/TP змінено вручну",
    "PAUSED": "сесію поставлено на паузу",
    "RESUMED": "сесію знято з паузи",
    "ERROR": "помилка під час обробки",
    "UNKNOWN_V0": "невідомо (запис старого формату)",
}

RISK_UK: dict[str, str] = {
    "max_daily_loss": "денний збиток",
    "max_drawdown": "просідання від піку",
    "max_open_positions": "кількість відкритих позицій",
    "max_var_99": "VaR 99%",
    "max_cvar_99": "CVaR 99%",
    "equity": "equity не додатна",
    "day_start_equity": "equity на початок дня не додатна",
    "peak_equity": "пікова equity не додатна",
}

_PCT_CODES = {"max_daily_loss", "max_drawdown", "max_var_99", "max_cvar_99"}


def fmt(value: object, *, signed: bool = False) -> str:
    """Readable number: 2412.53, 18.5, 0.1052, 1.2e-05. Non-numbers as text."""
    if isinstance(value, bool) or value is None:
        return str(value)
    if not isinstance(value, (int, float)):
        return str(value)
    number = float(value)
    magnitude = abs(number)
    if magnitude >= 1000:
        text = f"{number:.2f}"
    elif magnitude >= 1:
        text = f"{number:.3f}"
    elif magnitude == 0:
        text = "0"
    else:
        text = f"{number:.3g}"
    if "." in text and "e" not in text:
        text = text.rstrip("0").rstrip(".")
    if signed and number > 0:
        text = "+" + text
    return text


def pct(value: object) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{float(value):+.2f}%"
    return str(value)


def _v(step: Mapping[str, Any], key: str) -> object:
    return (step.get("values") or {}).get(key)


def _t(step: Mapping[str, Any], key: str) -> object:
    return (step.get("thresholds") or {}).get(key)


def _header(row: Mapping[str, Any]) -> str:
    ts = row.get("ts")
    when = ts
    if isinstance(ts, str):
        try:
            when = datetime.fromisoformat(ts).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            when = ts
    close = row.get("close")
    try:
        close_text = fmt(float(close)) if close is not None else "?"
    except (TypeError, ValueError):
        close_text = str(close)
    if row.get("kind") == "intrabar":
        return f"{when} {row.get('instrument', '')} ціна {close_text}."
    return f"{when} {row.get('instrument', '')} бар закрито {close_text}."


def _account(row: Mapping[str, Any]) -> str | None:
    account = row.get("account") or {}
    position = account.get("position")
    if not position:
        return None
    if position == "FLAT":
        return "Позиція: FLAT."
    parts = [f"Позиція: {position} {fmt(account.get('qty'))} @ {fmt(account.get('entry_price'))}"]
    levels = []
    if account.get("stop_loss") is not None:
        levels.append(f"SL {fmt(account.get('stop_loss'))}")
    if account.get("take_profit") is not None:
        levels.append(f"TP {fmt(account.get('take_profit'))}")
    if levels:
        parts.append(f"({', '.join(levels)})")
    if account.get("unrealized_pnl") is not None:
        parts.append(f"нереалізований PnL {fmt(account.get('unrealized_pnl'), signed=True)}")
    return " ".join(parts) + "."


def _warmup(step: Mapping[str, Any]) -> str:
    seen = _v(step, "bars_seen")
    required = _v(step, "bars_required")
    of = f"{seen}/~{required}" if required is not None else f"{seen}"
    return f"{step.get('component')}: прогрів ({of} барів)."


def _regime(step: Mapping[str, Any]) -> str:
    result = str(step.get("result", "?")).upper()
    er = _v(step, "er")
    applied = _t(step, "applied_er")
    slope = _v(step, "slope")
    if isinstance(er, (int, float)) and isinstance(applied, (int, float)):
        sign = "≥" if er >= applied else "<"
        why = f"ER {fmt(er)} {sign} {fmt(applied)}"
    else:
        why = f"ER {fmt(er)}"
    extra = f", alpha {fmt(_v(step, 'alpha'))}" if _v(step, "alpha") is not None else ""
    return f"Режим {result} ({why}, нахил EMA {fmt(slope, signed=True)}{extra})."


def _filter(step: Mapping[str, Any]) -> str:
    name = str(step.get("component", "")).upper()
    verdict = step.get("verdict")
    if verdict == "skip":
        return f"{name}: ще немає даних."
    reading = _v(step, "vpin")
    if reading is None:
        reading = f"buy {fmt(_v(step, 'buy_intensity'))} / sell {fmt(_v(step, 'sell_intensity'))}"
    else:
        reading = fmt(reading)
    flow = "токсичний" if step.get("result") == "toxic" else "нормальний"
    text = f"{name} {reading} — потік {flow}"
    if verdict == "modify":
        text += f"; фільтр змінив маршрут ({step.get('note')})"
    return text + "."


def _donchian(step: Mapping[str, Any]) -> str:
    up = step.get("component") == "UptrendBreakout"
    close = fmt(_v(step, "close"))
    level_key = "prior_high" if up else "prior_low"
    level = fmt(_v(step, level_key))
    ema = fmt(_v(step, "ema"))
    dist = pct(_v(step, "dist_to_breakout_pct"))
    result = step.get("result")
    edge = "максимуму" if up else "мінімуму"
    if result in ("buy", "sell"):
        side = "вище" if up else "нижче"
        return (
            f"Donchian: close {close} {side} {edge} каналу {level} ({dist}) "
            f"→ сигнал {result.upper()}."
        )
    if result == "flat":
        side = "нижче" if up else "вище"
        return f"Donchian: close {close} {side} EMA {ema} → вихід (FLAT)."
    side = "нижче" if up else "вище"
    ema_side = "вище" if up else "нижче"
    return (
        f"Donchian: close {close} {side} {edge} каналу {level} ({dist}), "
        f"але {ema_side} EMA {ema} — утримуємось."
    )


def _range(step: Mapping[str, Any]) -> str:
    close = fmt(_v(step, "close"))
    lower, upper, mean = fmt(_v(step, "lower")), fmt(_v(step, "upper")), fmt(_v(step, "mean"))
    z = fmt(_v(step, "z"), signed=True)
    result = step.get("result")
    if result == "buy":
        return f"Bollinger: close {close} на/нижче нижньої смуги {lower} (z {z}) → сигнал BUY."
    if result == "sell":
        return f"Bollinger: close {close} на/вище верхньої смуги {upper} (z {z}) → сигнал SELL."
    if result == "flat":
        if _v(step, "z") is None:
            return "Bollinger: волатильність 0, смуги не визначені → FLAT."
        return f"Bollinger: close {close} повернувся до середньої {mean} (z {z}) → FLAT."
    return f"Bollinger: close {close} між смугами [{lower}; {upper}], z {z} — без сигналу."


def _ema(step: Mapping[str, Any]) -> str:
    fast, slow = _v(step, "fast_ema"), _v(step, "slow_ema")
    sign = (
        "≥"
        if isinstance(fast, (int, float)) and isinstance(slow, (int, float)) and fast >= slow
        else "<"
    )
    target = "LONG" if step.get("result") == "buy" else "SHORT"
    return (
        f"EMA-крос: швидка {fmt(fast)} {sign} повільна {fmt(slow)} "
        f"(спред {pct(_v(step, 'spread_pct'))}) → ціль {target}."
    )


def _vpin_momentum(step: Mapping[str, Any]) -> str:
    result = step.get("result")
    close, ema = fmt(_v(step, "close")), fmt(_v(step, "ema"))
    if _v(step, "trail_stop") is not None:
        stop = fmt(_v(step, "trail_stop"))
        if result == "flat":
            return f"VPIN-momentum: close {close}, EMA {ema}, трейлінг-стоп {stop} → вихід (FLAT)."
        return (
            f"VPIN-momentum: у позиції {_v(step, 'bars_in_position')} барів, close {close}, "
            f"EMA {ema}, трейлінг-стоп {stop} — утримуємось."
        )
    if result in ("buy", "sell"):
        side = "вище" if result == "buy" else "нижче"
        return (
            f"VPIN-momentum: токсичний потік і close {close} {side} EMA {ema} "
            f"→ сигнал {result.upper()}."
        )
    return f"VPIN-momentum: close {close}, EMA {ema} — умов для входу немає."


def _formulaic(step: Mapping[str, Any]) -> str:
    probs = (
        f"P(up) {fmt(_v(step, 'p_up'))}, P(down) {fmt(_v(step, 'p_down'))}, "
        f"P(flat) {fmt(_v(step, 'p_flat'))}, поріг {fmt(_t(step, 'threshold'))}"
    )
    result = step.get("result")
    if result:
        return f"Модель: {probs} → сигнал {str(result).upper()}."
    return f"Модель: {probs} — без сигналу."


def _regime_change(step: Mapping[str, Any]) -> str:
    return (
        f"Режим змінився {str(_v(step, 'from_regime')).upper()} → "
        f"{str(_v(step, 'to_regime')).upper()}: закриваємо позицію (FLAT)."
    )


def _strategy(step: Mapping[str, Any]) -> str:
    component = step.get("component")
    if component in ("UptrendBreakout", "DowntrendBreakout"):
        return _donchian(step)
    if component == "RangeMeanReversion":
        return _range(step)
    if component == "EmaCrossover":
        return _ema(step)
    if component == "VpinMomentum":
        return _vpin_momentum(step)
    if component == "FormulaicLgbm":
        return _formulaic(step)
    if component == "BuyAndHold":
        return "Бенчмарк buy&hold: завжди ціль LONG → BUY."
    if _v(step, "from_regime") is not None:
        return _regime_change(step)
    return _generic(step)


def _plan(step: Mapping[str, Any]) -> str:
    holding = str(_v(step, "holding") or "?").upper()
    result = step.get("result")
    words = {
        "noop": "без змін (вже в цільовій позиції)",
        "exit": "вихід",
        "enter": "вхід",
        "exit_and_enter": "вихід і вхід у протилежний бік",
    }
    return f"План: {holding} → {words.get(str(result), str(result))}."


def _gate(step: Mapping[str, Any]) -> str:
    component = str(step.get("component", ""))
    verdict = step.get("verdict")
    if component == "auto_trade":
        return "Автоторгівля вимкнена — сигнал лише записано." if verdict == "block" else ""
    if component == "session_active":
        return "Сесія неактивна — сигнал лише записано." if verdict == "block" else ""
    if component == "paused":
        return "Сесія на паузі — новий вхід пропущено." if verdict == "block" else ""
    if component.startswith("risk"):
        code = component.split(".", 1)[1] if "." in component else ""
        if verdict == "pass":
            dl, dd = _v(step, "day_loss_pct"), _v(step, "drawdown_pct")
            return f"Ризик-гейт: OK (денний збиток {fmt(dl)}%, просідання {fmt(dd)}%)."
        label = RISK_UK.get(code, step.get("result") or code)
        value, limit = _v(step, "value"), _t(step, "limit")
        if (
            code in _PCT_CODES
            and isinstance(value, (int, float))
            and isinstance(limit, (int, float))
        ):
            return (
                f"Ризик-гейт ЗАБЛОКУВАВ вхід: {label} {float(value) * 100:.2f}% ≥ "
                f"ліміт {float(limit) * 100:.2f}%."
            )
        return f"Ризик-гейт ЗАБЛОКУВАВ вхід: {label}."
    return _generic(step)


def _execution(step: Mapping[str, Any]) -> str:
    result = step.get("result")
    if result == "exit":
        pnl = _v(step, "realized_pnl")
        pnl_text = f", PnL {fmt(pnl, signed=True)}" if pnl is not None else ""
        return (
            f"Виконано: закрито {_v(step, 'side')} {fmt(_v(step, 'qty'))} @ "
            f"{fmt(_v(step, 'price'))}{pnl_text}."
        )
    if result == "entry":
        levels = ""
        if _v(step, "stop_loss") is not None:
            levels = f" (SL {fmt(_v(step, 'stop_loss'))}, TP {fmt(_v(step, 'take_profit'))})"
        return (
            f"Виконано: відкрито {_v(step, 'side')} {fmt(_v(step, 'qty'))} @ "
            f"{fmt(_v(step, 'price'))}{levels}."
        )
    if result == "skipped":
        return f"Вхід пропущено: {step.get('note')}."
    return _generic(step)


def _intrabar(step: Mapping[str, Any]) -> str:
    component = step.get("component")
    if component in ("stop_loss", "take_profit"):
        name = "Стоп-лос" if component == "stop_loss" else "Тейк-профіт"
        return (
            f"{name} {fmt(_v(step, 'level'))} зачеплено (high {fmt(_v(step, 'high'))}, "
            f"low {fmt(_v(step, 'low'))})."
        )
    if component == "manual_close":
        return "Позицію закрито вручну з терміналу."
    if component == "update_stops":
        stop, target = fmt(_v(step, "stop_loss")), fmt(_v(step, "take_profit"))
        return f"Рівні змінено вручну: SL {stop}, TP {target}."
    if component == "pause":
        return "Сесію поставлено на паузу: нові входи зупинено, виходи працюють."
    if component == "resume":
        return "Паузу знято: нові входи дозволені."
    return _generic(step)


def _generic(step: Mapping[str, Any]) -> str:
    values = ", ".join(f"{k} {fmt(v)}" for k, v in (step.get("values") or {}).items())
    head = f"{step.get('component')}: {step.get('verdict')}"
    if step.get("result"):
        head += f" → {step.get('result')}"
    tail = f" ({values})" if values else ""
    note = f" — {step.get('note')}" if step.get("note") else ""
    return f"{head}{tail}{note}."


_BY_STAGE: dict[str, Callable[[Mapping[str, Any]], str]] = {
    "warmup": _warmup,
    "regime": _regime,
    "filter": _filter,
    "strategy": _strategy,
    "plan": _plan,
    "gate": _gate,
    "execution": _execution,
    "intrabar": _intrabar,
}


def render_narrative(row: Mapping[str, Any]) -> str:
    """One paragraph for one record. Old (v0) rows get a best-effort sentence."""
    parts = [_header(row)]
    account = _account(row)
    if account:
        parts.append(account)
    steps = row.get("steps") or []
    if not steps:
        # v0: only the snapshot fields exist.
        regime = row.get("regime")
        if regime:
            parts.append(f"Режим {str(regime).upper()}.")
        if row.get("signal"):
            parts.append(f"Сигнал {str(row['signal']).upper()} ({row.get('signal_reason')}).")
        else:
            parts.append("Сигналу немає.")
    for item in steps:
        render = _BY_STAGE.get(str(item.get("stage")), _generic)
        text = render(item)
        if text:
            parts.append(text)
    outcome = row.get("outcome")
    if outcome:
        parts.append(f"Підсумок: {OUTCOME_UK.get(str(outcome), str(outcome))}.")
    return " ".join(parts)
