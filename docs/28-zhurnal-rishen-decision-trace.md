# 28. Журнал рішень: decision trace (`decision_trace/1`)

Журнал рішень paper-сесії тепер пояснює кожен закритий бар ланцюжком кроків:
**бар закрито → режим → фільтри → стратегія → план позиції → гейти → виконання**,
з підсумковим кодом `outcome` і текстом-міркуванням українською (`narrative`).
Раніше запис робився *до* виконання, тож не було видно, чи угоду відкрито, чи її
заблокував ризик; у робота `regime` блок `indicators` був завжди порожній.

Увімкнення: `DECISION_LOG_ENABLED=true` (файли `data/paper/decisions/<session-id>_YYYY-MM-DD.jsonl`,
зберігаються `DECISION_LOG_RETENTION_DAYS`, за замовчуванням 7 днів).

## Формат запису

Один рядок JSONL на закритий бар (`kind: "bar_decision"`) і окремі рядки для подій
між закриттями (`kind: "intrabar"`: стоп-лос, тейк-профіт, ручне закриття, зміна SL/TP,
пауза/зняття паузи). Поля старого формату (`ts`, `close`, `regime`, `signal`,
`signal_reason`, `indicators`, `states`) лишились — дашборд і старі скрипти працюють.

```json
{
  "schema": "decision_trace/1", "kind": "bar_decision",
  "ts": "2026-09-26T14:00:00+00:00", "session_id": "regime-eth-3f2a", "robot": "regime",
  "instrument": "ETHUSDT", "close": "2412.5", "regime": "uptrend", "signal": "buy",
  "outcome": "ENTRY_BLOCKED_RISK", "blocked_by": "risk.max_daily_loss", "fill_ids": [],
  "bar_seq": 1842, "bar": {"o": 2398.1, "h": 2415.0, "l": 2395.2, "c": 2412.5, "v": 18234.1},
  "account": {"position": "FLAT", "equity": 9690.2, "day_loss_pct": 3.1, "drawdown_pct": 4.2},
  "steps": [
    {"stage": "regime", "component": "RegimeClassifier", "verdict": "pass", "result": "uptrend",
     "values": {"er": 0.34, "slope": 12.1},
     "thresholds": {"enter_trend_er": 0.3, "exit_trend_er": 0.2, "applied_er": 0.3}},
    {"stage": "strategy", "component": "UptrendBreakout", "verdict": "emit", "result": "buy",
     "values": {"close": 2412.5, "prior_high": 2405.0, "ema": 2371.8, "dist_to_breakout_pct": 0.31}},
    {"stage": "plan", "component": "position_plan", "verdict": "pass", "result": "enter"},
    {"stage": "gate", "component": "risk.max_daily_loss", "verdict": "block",
     "result": "daily loss circuit breaker", "values": {"value": 0.031}, "thresholds": {"limit": 0.03}}
  ],
  "config_hash": "a91c0e22d4f1",
  "narrative": "2026-09-26 14:00 ETHUSDT бар закрито 2412.5. Позиція: FLAT. Режим UPTREND (ER 0.34 ≥ 0.3, нахил EMA +12.1). Donchian: close 2412.5 вище максимуму каналу 2405 (+0.31%) → сигнал BUY. План: FLAT → вхід. Ризик-гейт ЗАБЛОКУВАВ вхід: денний збиток 3.10% ≥ ліміт 3.00%. Підсумок: вхід заблоковано ризиком."
}
```

* `steps[].verdict`: `pass` / `block` / `modify` (фільтр змінив маршрут) / `emit` (видав сигнал чи ордер) / `skip` (не готовий) / `info` (оцінив, дій немає).
* Числа в `steps`, `bar`, `account` — JSON-числа з 8 значущими цифрами (діагностика). Точні суми — у журналі угод.
* `bar_seq` — номер закритого бару сесії; стрибок означає пропущений бар.
* `config_hash` — 12 символів sha256 від конфігу сесії: однаковий хеш = однакові параметри.
* `account` — стан рахунку **до** виконання цього бару (те, на чому вирішували гейти).
* Записи без `schema` (старі) читаються як `outcome: "UNKNOWN_V0"`.

## Коди `outcome`

| Код | Коли |
| --- | --- |
| `WARMUP` | Індикатори ще не готові (`bars_seen`/`bars_required` у кроці) |
| `NO_SIGNAL` | Стратегія оцінила бар і сигналу не дала |
| `HOLD_NOOP` | Сигнал є, але позиція вже в цільовому стані |
| `ENTRY_OPENED` / `REVERSE` / `EXIT` | Виконано (див. `fill_ids`) |
| `FLATTEN_REGIME_CHANGE` | Закриття через зміну режиму |
| `ENTRY_BLOCKED_RISK` | Ризик-гейт; `blocked_by` = `risk.<ліміт>` |
| `ENTRY_SKIPPED_PAUSED` / `ENTRY_SKIPPED_SIZE` | Пауза / розмір позиції 0 |
| `AUTO_TRADE_OFF` / `SESSION_INACTIVE` | Сигнал лише записано |
| `STOP_LOSS` / `TAKE_PROFIT` / `MANUAL_CLOSE` / `STOPS_UPDATED` / `PAUSED` / `RESUMED` | Події `intrabar` |

## Де що в коді

* `domain/decision_trace.py` — `TraceStep`, `Stage`, `Verdict`, `Outcome`, протокол `Explainable`.
* Кожен paper-робот має `last_trace` (оновлюється в `on_bar`, сигнатура `on_bar` та сама):
  `RegimeRouter` (режим + VPIN/Hawkes як `modify` + гілка), `AdaptiveEmaRouter`, `UptrendBreakout`,
  `DowntrendBreakout`, `RangeMeanReversion`, `EmaCrossover`, `VpinMomentum`, `FormulaicLgbmStrategy`, `BuyAndHold`.
* `api/paper_streamer.py` — `_decide` / `_execute_signal` додають кроки плану, гейтів і виконання; запис
  робиться **після** виконання; stop/TP/ручні дії пишуть `intrabar`. Помилка запису журналу не зупиняє торгівлю.
* `RiskDecision` має `code`, `value`, `limit` (який запобіжник і на скільки).
* `application/decision_narrative.py` — текст лише з кроків; `application/decision_trace_codec.py` — JSON.
* `application/decision_digest.py` — дайджест для LLM; `application/decision_analysis.py` — виклик моделі.

## API

* `GET /api/paper/sessions/{key}/decision-log?lines=&outcome=A,B&kind=&since=&until=` — записи з фільтрами.
* `GET /api/paper/sessions/{key}/decision-digest?since=&until=` — дайджест (JSON + Markdown).
* `GET /api/decisions/presets` — готові питання.
* `POST /api/decisions/analyze` — `{"session": "<id>", "preset": "blocking_filter"}` або `{"records": [...], "question": "..."}`.
  З `LLM_API_KEY` відповідь моделі зберігається в `reports/decision-analysis/<session>_<час>.md`.
  Без ключа — `status: "no_llm"` і Markdown-дайджест, який можна вставити в будь-який чат.

## Дайджест для LLM

Код рахує, модель пояснює: розподіл `outcome`, `blocked_by`, частка часу в кожному режимі, перемикання
і «пилка» (A→B→A), форвард-прибуток виконаних і заблокованих сигналів (+1/+4/+24 бари, close-to-close,
знак за стороною сигналу, без комісій і стопів), «майже-сигнали» (≤ 0.2% до пробою), пропуски `bar_seq`,
і повні міркування по ключових барах. Промпт вимагає посилатись на цифри й `ts`, позначати висновки як
гіпотези при < 30 сигналах і не радити міняти параметри без бектесту.

## Що далі (не зроблено в цій ітерації)

* Стрічка рішень і маркери на графіку в `LiveTradingTerminal` (зараз — оновлена вкладка DecisionLogPanel).
* Trace у бектесті (`signal_strategy`) і `scripts/trace_diff.py` для порівняння paper ↔ backtest.
* `meta_label` у paper не запускається, тому trace для нього не додано.
