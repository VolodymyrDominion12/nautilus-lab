# 30. Журнал рішень: життєвий цикл угоди в бектесті

Продовження [28-zhurnal-rishen-decision-trace.md](28-zhurnal-rishen-decision-trace.md).
Етап 1–2 плану «сторінка пакетного бектесту» (2026-09-30). Формат лишається
`decision_trace/1`: нові поля лише додаються, старі читачі їх ігнорують.

## Навіщо

Свіп 2026-09-29 (`reports/decision-sweep/`) показав прогалини, через які журнал не
відповідав на питання «чому саме так»:

| Прогалина | Наслідок |
| --- | --- |
| Рівень стопу не логувався (лише `stop_distance`) | У вікні угоди бектесту немає лінії SL, R-множник не рахується |
| Вихід по ратчету = звичайний `EXIT` | Не відрізнити вихід за сигналом від спрацювання ратчета |
| `meta_label` без `last_trace` | 1761 з 1806 записів без кроків; відхилені сигнали невидимі |
| VPIN-крок без порогу | «0 угод» у vpin_momentum не пояснюється (макс VPIN 0.62 < 0.70) |
| Бар після кожного входу = `ENTRY_BLOCKED_RISK` / `execution.order_working` | Статистика блоків завищена на 1 бар на угоду |
| `STOP_LOSS` з `regime=""` і account уже після стопу | Контекст виходу втрачено |
| `regime=UNKNOWN` у роботів без класифікатора | Дайджест показував «UNKNOWN 100%» |

## Нові outcome

| Outcome | Kind | Коли |
| --- | --- | --- |
| `ENTRY_FILLED` | intrabar | Вхідний ордер виконано: ціна, розмір, комісія, прослизання, затримка, рівень стопу |
| `PENDING_FILL` | bar | Попередній ордер ще не виконано — новий вхід не додається. Це не блок ризику |
| `SIGNAL_VETOED` | bar | Фільтр усередині робота (meta-label) відхилив свій сигнал |
| `RATCHET_EXIT` | bar | Ратчет-стоп закрив позицію |

## Нові кроки

- `execution / fill` (`result=entry_filled`): `side, qty, fill_price, decision_price,
  slippage_bps` (> 0 = гірше за close рішення), `fee`, `fill_delay_s`.
- `execution / protective_stop` (`result=stop_placed`): `stop_loss, risk_per_unit, risk_pct`.
- `plan / ratchet` на кожному барі в позиції: `stop, prior_stop, armed, close, adverse,
  dist_to_stop_pct`; `result` = `hold` | `tightened` | `exit`. На виході ще додається
  `execution / paper_broker` (`result=exit`).
- `filter / meta_label`: `p_success, primary_side, margin_pct`, поріг `threshold`;
  `verdict` = `pass` | `block`.
- `filter / vpin` (vpin_momentum і regime): `margin_pct` і поріг `toxic_threshold`.
- `gate / execution.order_working` тепер `verdict=info` з `order_id, order_side`.

`margin_pct = (значення − поріг) / |поріг| · 100` — єдина шкала «наскільки не дотягнуло»
для різних роботів (`domain/decision_trace.py::margin_pct`). Дайджест рахує фільтр із
`margin_pct ∈ [−5%, 0)` як «майже-сигнал».

## Стоп у `states.stop_loss`

Кожен бар у позиції несе `states.stop_loss` — рівень, що зараз обмежує позицію
(тісніший із захисного стопу на біржі і ратчета). Так `trade_history` без змін малює лінію
SL і бачить, як вона рухалась. `STOP_LOSS` тепер несе режим і account останнього бару
**до** стопу, `entry_price` і `gross_pnl`.

## Реконструкція угод (`application/trade_history.py`)

- `qty` береться з кроку `execution/entry` (раніше завжди 1 «припущено»).
- `ENTRY_FILLED` додає `entry_fill_price`, `entry_slippage_bps`, `entry_fill_delay_s`, `fee`;
  цей рядок є в таймлайні угоди, але не рахується як бар утримання.
- `initial_stop_loss` — стоп на момент входу; R-множник рахується від нього (ратчет, що
  підтягнув стоп до беззбитку, більше не роздуває R).
- `entry_price` навмисно лишається close бару рішення: вихід у бектесті теж оцінюється за
  close, тож PnL порівнює однакове з однаковим. Розрив до фактичного виконання видно окремо.

## Що з цього варто перевірити першим

У свіпі 29.09 після кожного входу наступний бар показував `FLAT` + «ордер уже в роботі»:
ринковий ордер у бар-бектесті виконується з затримкою приблизно на бар. `fill_delay_s` і
`slippage_bps` у `ENTRY_FILLED` покажуть, скільки це коштує кожній стратегії. Якщо
затримка систематична, це кандидат на першу «дрібницю»: вхід фактично відбувається за
ціною наступного бару, а не того, на якому з’явився сигнал.

## Pairs і funding (30.09, друга частина)

Обидва двоногі роботи тепер пишуть той самий `decision_trace/1`
(`infrastructure/nautilus/two_leg_decisions.py`). Запис прив’язаний до ноги A (pairs: A,
funding: спот): її close, її напрям у `signal`; друга нога — у кроках виконання з `leg`.

- **pairs**: запис на кожен вирівняний бар. `filter / cointegration` — ADF p, β, half-life
  проти `adf_pvalue_max` / `max_half_life_bars` (PASS, або INFO з причиною «не коінтегровано»);
  `strategy / PairsTrading` — spread, z, `z_margin_pct` до ближчого порогу, `z_low/z_high/z_exit`;
  у позиції — `open_bars`, time stop (2 × half-life).
- **funding**: запис на кожне funding-нарахування (не на бар). `strategy / FundingCarry` —
  ставка, комісія на інтервал, net APY і `apy_margin_pct` проти `min_net_apy`, basis проти
  `basis_max`; `execution / funding_settlement` — сума виплати. Так видно, чому funding не
  торгував у свіпі: net APY після комісій нижче порогу.
- **Виправлення**: `FundingRobot.on_funding_rate` раніше торгував і на нарахуваннях до
  `trade_start` (прогрів), тож OOS-прогін міг стартувати з позицією, відкритою на IS.
  Тепер прогрів лише пишеться як `WARMUP`, як у решти роботів.
- Нові налаштування `PAIRS_LEG_A` / `PAIRS_LEG_B` (раніше ноги були зашиті в `PairsParams`).

## DECISION_LOG_SCOPE

`DECISION_LOG_SCOPE=oos` (у `Settings` і `WalkForwardRequest.decision_log_scope`): прогони
сітки на in-sample йдуть без `session_id` і нічого не пишуть; OOS-прогін кожного фолду пише
під `<session>-f<fold>` — окремий файл на фолд. Номер сесії фолду є в
`multi_window.folds[i].session_id` результату. Це прибирає другий прохід свіпу.

## Пакетний бектест

Етап 3–4 плану. Запуск матриці роботів × інструментів з дашборда, таблиця прогонів і
сторінка кожного прогону.

```
reports/batches/<batch_id>/
  batch.json                  запит, стан кожної клітинки, pid
  batch.log
  cells/<robot>_<BASE>/
    config.json               payload для run_research_job
    last_run.json / .log      результат (формат вкладки Research)
    stdout.log
    decisions/<session>-f<n>_<дата>.jsonl
    summary.json              рядок таблиці (кеш)
  trials/<cell>.jsonl         trial ledger пакету (не research/trials.jsonl)
```

- `application/batch_plan.py` — план: клітинки, env кожної (інструмент, каталог, модель,
  perp для funding), і що не запуститься та чому — ще до старту.
- `api/run_batch_job.py` — процес пакету: кожна клітинка = окремий `run_research_job` зі
  своїм env, `DECISION_LOG_SCOPE=oos`, паралельно (`parallel`), SIGTERM зупиняє дітей.
- `api/batch_store.py` — файли, рядки таблиці (числа + дайджест + статистика угод),
  імпорт свіпу 29.09 (`POST /api/batches/import-sweep`).
- API: `POST /api/batches` (з `dry_run` — лише план), `GET /api/batches`,
  `GET /api/batches/{id}`, `POST /api/batches/{id}/cancel`,
  `GET /api/batches/{id}/runs/{cell}` (+ `/decisions`, `/trades`, `/digest`, `?fold=`).
  Існуючі `/api/paper/sessions/{key}/…` (угоди, журнал, дайджест) знаходять сесію фолду в
  теці пакету, тож сторінка угоди працює без змін.
- Фронт: вкладка «Пакетний бектест»; адреси `#/batch`, `#/batch/<id>`,
  `#/run/<id>/<cell>?fold=&tab=` (`lib/batch.ts`). Таблиця сортується, кожен рядок —
  посилання; на сторінці прогону — фолди, «Угоди» (посилання на сторінку угоди з графіком),
  «Рішення по барах», «Аналіз причин» (воронка барів, блоки, доходність після виконаних /
  заблокованих / відхилених сигналів, майже-сигнали), «Лог прогону».

## Компактний запис (етап 5)

- **`run_header`** (`RecordKind.RUN_HEADER`, outcome `RUN_HEADER`): один запис на початку
  прогону з повними `params` і `config_hash`, датований першим баром (щоб не сортуватись
  після історії). Далі кожен запис несе лише `config_hash`. Пишуть `SignalRobot` і обидва
  двоногі роботи; paper-термінал поки пише `params` у кожному записі, як і раніше.
- **`indicators`** більше не пишеться, коли є `steps`: `upgrade_row` відтворює його з кроків
  при читанні (ті самі рядки, що й раніше), тож `trade_history`, дашборд і дайджест бачать
  поле як завжди.
- Розмір запису на даних свіпу 29.09: regime 3.9 → 1.6 КБ, ema 3.7 → 1.5 КБ.
- Дайджест бере `params` із заголовка й не рахує його як рішення; реконструкція угод його
  пропускає.
- Схема лишилась `decision_trace/1`: зміни лише додають поля й зменшують дублювання.
  `trade_id` у записах не потрібен — реконструкція і так пов’язує вхід, виконання, стоп і вихід.

## Запас до порогу в усіх роботах (етап 5)

| Робот / крок | Поле | Проти чого |
| --- | --- | --- |
| regime (`RegimeClassifier`) | `er_margin_pct` | ER проти порогу гістерезису, що діяв |
| Bollinger (`RangeMeanReversion`) | `margin_pct` | \|z\| проти `bb_k` |
| Donchian | `dist_to_breakout_pct` | % ціни до пробою каналу |
| formulaic_lgbm | `margin_pct` | max(P(up), P(down)) проти `threshold` |
| vpin, meta_label | `margin_pct` | VPIN / P(take-profit) проти порогу |
| pairs | `z_margin_pct` | \|z\| проти ближчого порогу входу |
| funding | `apy_margin_pct` | net APY проти `min_net_apy` |

## Графік угоди і «поріг ±X%» (етап 6)

- `GET /api/paper/sessions/{key}/trades/{id}` повертає `context`: до 60 барів перед входом
  і 30 після виходу (кроки + stop), щоб лінії на графіку починались раніше за вхід.
- `lib/tradeOverlays.ts::overlaySeries` будує лінії з кроків журналу: EMA (fast/slow),
  канал Donchian (сходинкою), смуги Bollinger, трейл-стоп VPIN і **шлях стоп-лоса** зі
  `states.stop_loss` сходинкою — так видно, як рухався ратчет. Осцилятори (ER, VPIN,
  ймовірності) лишаються в таблиці індикаторів. Плоска лінія «фінального стопу» ховається,
  коли є його шлях.
- `application/decision_margins.py` + `GET /api/batches/{id}/runs/{cell}/margins?fold=`:
  усі запаси по компонентах. У вкладці «Аналіз причин» — гістограма і повзунок «м’якше
  на X%»: скільки оцінок пройшло б поріг. Це підказка для гіпотези, а не результат —
  перевіряти наступним OOS-пакетом із записом у trial ledger.

## Ще не зроблено

- Окрема панель осциляторів під графіком угоди (ER, VPIN, P) з лінією порогу.
- `run_header` і компактний запис для paper-терміналу.
- Кнопка «перевірити гіпотезу»: запуск пакету з м’якшим порогом одним кліком.
