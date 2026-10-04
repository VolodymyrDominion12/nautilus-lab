# 35. Бектести та лог рішень: аудит зручності, гнучкості й інформативності та план покращень

Oct 4, 2026 · аудит за кодом, артефактами прогонів і метаданими каталогів.
Продовження docs/30 (журнал рішень), docs/32–33 (модель виконання, гіпотези) і
плану інгесту (docs/34 — файл у репозиторії відсутній, див. §6).

Коротко: **пакетний бектест уже вміє більше, ніж показує**, і одночасно **планує
клітинки, які фізично не можуть виконатись**. Найгучніший приклад — останній пакет:
50 клітинок, 8 годин, з них 5 клітинок `funding` (деривативи) упали на «no bars in
catalog», бо план перевіряє лише наявність теки каталогу, а не серії бари/фандингу.
Друга системна річ: **важіль комісій зламаний в UI і розійшовся з документацією** — а
саме комісія вирішує, чи живуть деривативи (перп дешевший за спот у 2–4 рази).

---

## 0. Метод і межі

Що зроблено: прочитано код (`application/batch_plan.py`, `api/run_batch_job.py`,
`api/batch_store.py`, `api/routes/batches.py`, `api/serializers.py`, `api/requests.py`,
`application/promotion_gate.py`, `infrastructure/nautilus/{bar_feed,funding_strategy,backtest_runner}.py`,
`interfaces/{cli,composition}.py`, `api/settings_schema.py`), фронтенд (`components/batch/*`,
`components/research/*`, `services/api.ts`, `lib/batch.ts`), документи 28–33 і артефакти
`reports/batches/*` (10 пакетів). Перевірено метадані каталогів і реальні `summary.json`.

Один власний прогін (єдиний вимір у цьому документі):

```bash
INSTRUMENT_ID=ETHUSDT-PERP.SIM BAR_INTERVAL=4h CATALOG_PATH=catalog_perp_4h \
TRIALS_LEDGER_PATH=/tmp/perp_trials.jsonl \
.venv/bin/lab research --robot regime --folds 2 --days 300 --is-fraction 0.7
# exit=0; profitable=1/2 mean=-0.07% buy&hold=+21.96% breakeven=-28.95bps
# promotion_gate=REJECT (preregistered=not measured, ... beats_buy_hold=fail, oos_fills=fail)
```

Висновок з прогону: **рушій уже торгує перп як інструмент** (`ETHUSDT-PERP.SIM`, 4h,
каталог перпів) — перешкода для деривативів не в рушії, а в даних і в пакетному шарі.

---

## 1. Пакетний бектест: як працює і де болить

Потік: `BatchLaunchForm` → `POST /api/batches` (`routes/batches.py:168`) → `plan_cells`
(`application/batch_plan.py:122`) → `run_batch_job` (кожна клітинка = окремий процес
`run_research_job`, env-ізоляція, `DECISION_LOG_SCOPE=oos`) → `batch.json` +
`cells/<id>/{last_run.json,summary.json,decisions/}` → `BatchTablePage` → `RunPage`
з табами «Угоди / Рішення по барах / Аналіз причин / Лог прогону».

Факти останнього пакета `20261003_182518_batch` (прочитано з `batch.json`):

| показник | значення |
|---|---|
| запит | 8 роботів × 7 монет, 1h, `catalog`, folds=6, days=1000, parallel=2 |
| клітинок | 50: **34 ok, 10 blocked, 6 failed** |
| стіна | 8.02 год (02:26 завершення) |
| failed #1–5 | `funding_{SOL,BNB,XRP,DOGE,ADA}`: `no bars in catalog catalog_2019_4h … Run 'lab ingest' first.` |
| failed #6 | `vpin_momentum_DOGE`: `timed out after 14400 s` (тим часом `vpin_momentum_XRP` біг 2.7 год) |
| blocked ×10 | `formulaic_lgbm_{SOL,BNB,XRP,DOGE,ADA}` і `meta_label_{…}` — «model … not found» (це правильна поведінка) |

### B-1. Pre-flight перевіряє теку, а не серію — і обіцяє прогін, якого не буде

`plan_cells` знає лише `exists(catalog)` (`batch_plan.py:170-171`). Відтворення:

```
funding_SOL   catalog=catalog_2019_4h  blocked=None   # «буде запущено»
```

а в `catalog_2019_4h` є бари лише BTC/ETH (4 серії: 2 спот + 2 перп). Помилка видна
лише через години, у полі `error` клітинки. Правильна перевірка — наявність **серії**
`<INSTRUMENT_ID>-<INTERVAL>-LAST-EXTERNAL` плюс потрібних подієвих серій
(`data/funding/<SYMBOL>`, перп-бари) і покриття запитаного вікна. Дані для цього вже є:
`catalog_service` / `data_health` віддають першу й останню дату та кількість рядків
(і саме тому випадає 5 клітинок із 50).

### B-2. Матриця одновимірна: robots × symbols, усе решта — глобальне

`BatchRequest` (`batch_plan.py:44-84`) має один `interval`, один `catalog`, один `env`
на весь пакет; виняток — зашитий спецвипадок `funding` (`:160-163`) з `catalog_2019_4h`/`4h`.
Наслідки:

- **Гіпотези H1…H4 неможливо порівняти в одному пакеті.** Це прямо задокументовано як
  обхід: «env у батчі діє на всі клітинки, тож кожна гіпотеза — окремий батч з міткою»
  (docs/32 §4). Замість однієї матриці 4×N — 5 пакетів по кілька годин, і порівняння
  руками.
- `cell_id = f"{robot}_{base}"` (`:172`) не містить варіанта, тож два варіанти однієї
  клітинки в одному пакеті неможливі навіть структурно.
- **Ринку (спот/перп) як виміру немає:** `instrument_id` завжди спотовий
  (`spot_instrument`, `:110-111`), символи валідуються регексом `<BASE>USDT` (`:40`, `:70`).
  «Бектест на перпах» у пакеті = рівно одна клітинка `funding`.
- UI не надсилає навіть того, що API вже приймає: `is_fraction` (тип є в `api.ts:1261`,
  поле є в `routes/batches.py:76`, форма його не шле → завжди 0.7) і
  `funding_catalog`/`funding_interval` (є в API, немає у формі — тому клітинки `funding`
  з UI не розблокувати).

### B-3. Пакет не має ні прогресу, ні місця в системі джобів

Пакет — сирий `subprocess.Popen` (`routes/batches.py:121-143`), не `JobManager`
(`api/jobs.py:41`). Тому: немає тоста «Task finished», немає блоку «Running now» у
Sidebar, `JOB_TABS` не має ключа batch, `/api/status` про пакети не знає. Прогрес видно,
лише поки відкрита сторінка пакета (полінг 5 с), а `RunPage` робить один `fetchRun` на
mount (`RunPage.tsx:34-42`) — відкрита під час роботи клітинка не оновиться ніколи.
`started_at/finished_at` клітинок і пакета приходять, але не рендеряться: ETA/тривалості
немає, хоч вони безкоштовні.

### B-4. Перезапуск — «все або нічого», невдалу клітинку не догнати

`reset_batch` (`batch_store.py:247-295`) стирає всі артефакти й повертає **всі** клітинки
в `queued`; окремої дії «повторити failed/blocked» немає. Ціна: після 4-годинного таймауту
однієї клітинки ще 8 годин на весь пакет. `CELL_TIMEOUT_SECONDS = 4*3600`
(`run_batch_job.py:47`) однаковий для всіх роботів, хоч фактичні часи різняться на два
порядки (`vpin_momentum` на 1h — години, `ema` — хвилини).

### B-5. Пакет не вміє ані аудиту перенавчання, ані пререєстрації — тобто не може пройти ворота

`research_job_config` (`batch_plan.py:212-227`) передає лише robot/source/folds/
is_fraction/catalog/instrument/interval/days: без `--pbo`, без `--register`, без
`tearsheet`, `journal`, `embargo`, стрес-зрізів, optuna. Наслідок структурний, а не
косметичний:

```
promotion_gate=REJECT (preregistered=not measured, …, pbo=not measured, dsr=not measured)
```

Клітинка пакета **не може** стати `PROMOTE` у принципі: `pbo`/`dsr` не міряються, а
`preregistered` не пройде, бо реєстрації з дашборда не існує (прапорець `--register` є
лише в CLI, `cli.py:318`). Пакет — це тріаж; кандидата все одно треба переганяти окремо,
але UI про це не каже і кнопки «перегнати цю клітинку як кандидата» не має.

### B-6. Результат не згортається

`batch_payload` віддає лише рядки (`batch_store.py:471-497`): немає ні рейтингу, ні
«найкращої клітинки», ні агрегату по матриці, ні вердикту воріт, а між пакетами порівняння
немає взагалі (`RunsCompare` бачить лише `research/history`). При цьому частину полів
бекенд **уже** повертає, а UI їх не малює (детально §3 нижче).

---

## 2. Одиночний прогін (Research Lab): найповніша частина, але з трьома дірками

Сильні сторони (варто не втратити): preflight-перевірки (`lib/research.ts:162-340`),
6 пресетів, `ParamOverrides` зі специфікації робота, `AdvancedGates` (optuna, pbo,
embargo, tick-vpin, hawkes, tearsheet, journal, notify, full-sample, стрес-зріз),
`VerdictPanel` з equity, cost-картками (`breakeven`/`paid`/`headroom`), `FoldBreakdown`,
`PboPanel`, `ExperimentHistory`, `RunsCompare`, збереження форми в localStorage.

| # | дірка | доказ |
|---|---|---|
| S-1 | **Немає пререєстрації з UI** | `ResearchRunRequest` (`api/requests.py:12-39`) без `register`; `--register` лише в CLI. Тому кожен прогін із дашборда назавжди `preregistered=not measured` |
| S-2 | **Немає `--vol-target`** | є в CLI (`cli.py:327`), немає ні в DTO, ні в формі |
| S-3 | **Немає довільних override** | `ParamOverrides.tsx:33-53` будує поля лише зі `spec.params[].env` і ріже до 12; у спеці `regime` немає `RISK_PER_TRADE`, `MAX_OPEN_POSITIONS`, `DRAWDOWN_COOLDOWN_DAYS`, `SPOT_TAKER_FEE` → з UI їх не задати |
| S-4 | **Невідомі ключі ігноруються тихо** | `settings_coerce.apply_setting_overrides`: `if field_name is None: continue`; для пакета ключі перевіряються лише регексом `^[A-Z][A-Z0-9_]*$` (`batch_plan.py:82-84`) → `RISK_PER_TRADE=0.02` у textarea не робить нічого і не скаржиться |
| S-5 | **Folds лише 1/2/4/8** | `BasicControls.tsx:125-130`; `scripts/run_matrix.py` і docs/32-33 вимагають 6 — з UI не запустити |
| S-6 | **Пресет «FTX Crash» падає** | `ResearchPresets.tsx:132` шле `stressSlice: 'ftx_collapse'`, валідні значення — `covid2020/ftx2022/etf2024` (`domain/stress_slices.py:9-11`). Preflight це не ловить → прогін стартує і падає в `resolve_stress_slice` |
| S-7 | **Даних IS немає навіть у схемі** | `serialize_fold` (`api/serializers.py:143-178`) містить `in_sample_fills`, але не IS-доходність → твердження «in-sample лише вибирає параметри» на екрані не перевіряється числом |

---

## 3. Що бекенд віддає, а UI не показує (інформативність за нуль ціни)

Найбільший резерв — сторінка прогону пакета **не читає `run.result`**, а там уже лежить
повний `last_run.json` (`batch_store.py:500-528`, тип `api.ts:1280`):

- `multi_window.folds[].oos_metrics` — `fees_paid, max_drawdown, max_dd_pct, turnover,
  sharpe_like, traded_notional, breakeven_cost, paid_cost_rate, cost_headroom`;
- `folds[].oos_ending_balance`, `in_sample_fills`, `candidates_tried`,
  `vol_matched_buy_and_hold_return`, `excess_vs_vol_matched_raw`;
- `provenance` (git-ревізія, `code_dirty`, `settings_sha256`, відпечаток каталогу,
  `preregistration_sha256`) — у фронтенді слово `provenance` не зустрічається, хоч
  `scripts/run_matrix.py:444` саме через це відмовляється працювати на брудному дереві;
- `multi_window`: `median_oos`, `best_oos`, `spread`, `cost_headroom`, `notes` —
  у `build_cell_summary` (`batch_store.py:419-430`) не переносяться, а таблиця пакета
  показує 7 колонок (`BatchTablePage.tsx:20-28`): прогін, Mean OOS, Worst, vs B&H, угоди,
  win, блоки. **Немає сортування за breakeven/headroom/fills/вердиктом** — тобто за тим,
  чим реально відбирають кандидата.
- `trades.avg_r`, `avg_slippage_bps`, `exits` рахуються (`batch_store.py:376-383`) і не
  рендеряться; вкладка «Угоди» показує 9 колонок, хоч `TradeSummary` має `fee`,
  `pnl_source`, `qty_known`, `fee_known`, `mfe/mae`, `stop_loss`, `take_profit`,
  `exit_reason`, `duration_seconds` (`api.ts:940-983`), а сам тип прямо вимагає показувати
  перші три.
- `promotion_gate=…` рахується (`research_runner.py:240-241`), але друкується лише в лог і
  **не потрапляє в структурований результат** (`serializers.build_job_result:285-321`).
  Тому вердикту немає ні на сторінці прогону, ні, тим паче, у таблиці пакета — а це те
  саме число, заради якого все робиться.
- `risk_breaches` (який саме circuit breaker і скільки разів відмовив входу,
  `application/risk.py:93-124`) доходить до звіту (`dtos.py:111`) і до paper-артефактів,
  але **ні в `summary.json`, ні в жодній таблиці пакета** його немає.

---

## 4. Деривативи: що вже готово, а що фізично блокує бектест

### 4.1 Готово (перевірено)

| Блок | Стан | Доказ |
|---|---|---|
| Бари перпів Binance USD-M (REST + архів) | ✅ | `binance_klines.py:61-63`; `lab ingest-archive --market um` |
| Funding-серія (REST + архів), nullable mark/index | ✅ | `binance_funding.py:36-38,114-124`; `funding_catalog.py:29-41` |
| Premium index (інгест/сховище/здоров'я) | ✅, але **без споживача** | `binance_premium_index.py:13`; у стратегіях не згадується |
| PERP як інструмент рушія (11 специфікацій, tick/lot, margin) | ✅ | `instrument.py:45-57`, `:306-340` |
| Окремі фі спот/перп | ✅ | `fees.py:22-30`; `settings.py:180-183` |
| `funding` у бектесті + walk-forward + paper | ✅ | `backtest_runner.py:771-863`; `run_walk_forward.py:75-76` |
| Прогін `regime` на перпі 4h | ✅ **виміряно сьогодні** | §0 |

### 4.2 Чого бракує (це і є відповідь на «як запускати бектести для деривативів»)

**D-1 (головне). Немає жодного каталогу, крім `catalog_2019_4h`, на якому `funding` може бігти.**
Причина в коді: обидві ноги читаються з **одного** каталогу (`bar_feed.py:122-127`), і серія
фандингу теж береться з кореня каталогу (`composition.py:142-161`, `funding_catalog(cfg)`).
Реальний стан каталогів:

| каталог | бари | funding | premium |
|---|---|---|---|
| `catalog` (1h) | спот 7 монет | 11 монет | — |
| `catalog_2019_4h` | **спот+перп лише BTC/ETH** | BTC/ETH **з 2023-10-31** | — |
| `catalog_perp_4h`, `_1d` | перп 11 монет | BTC/ETH/SOL | 11 монет |
| `catalog_spot_4h`, `_1d` | спот 11 монет | — | — |

Отже треба або (а) **новий спільний каталог** на інтервал (спот+перп+funding+premium разом),
або (б) **per-leg каталоги в запиті** (`funding_spot_catalog` / `funding_perp_catalog` /
`funding_series_catalog`) і відповідна проводка в `bar_feed`/`_FundingFeedAdapter`.
Варіант (а) дає негайний розблокувальний ефект без зміни коду; (б) — довговічний, і він
**суперечить** пункту B6 плану інгесту («один каталог на ринок і таймфрейм») — розбіжність
треба закрити ADR, інакше наступний інгест зробить funding ще менш запускним.

**D-2. Фандингу немає для 8 з 11 монет у перп-каталогах** (тільки BTC/ETH/SOL)
і в `catalog_2019_4h` він починається з 31.10.2023, хоч бари — з 2019. Це вже зафіксовано
як B1 у плані інгесту; архівний інгест (`lab ingest-archive --market um --dataset funding`)
дає історію з 2020 і закриває одразу обидві дірки.

**D-3. Гейт базису міряє не те, що обіцяє специфікація.** `FundingSnapshot` збирається з
барів: `mark_price = self._last_perp.close` (`funding_strategy.py:177`),
`index_price = self._last_spot.close` (`:205`). Реальні mark/index з
`data/funding/*.parquet` при конверсії в `FundingRateUpdate` **губляться**
(`backtest_runner.py:812-824` несе лише `rate`). Наслідки: `basis_max` фактично міряє
спот↔перп-базис (розумно, але не те, що в спеці: `|mark − index| / index`), а гілка
«index unknown» (`domain/funding.py:167-177`) у бектесті недосяжна. Premium index для
цього вже завантажено — споживача немає.

**D-4. Пакет не вміє перп як вимір** — див. B-2. Плюс `batch_plan.py:8` посилається на
неіснуючий `api/batch_runner.py` (файл — `api/run_batch_job.py`), а спека
`specs/components/derivatives-data.yaml` (обіцяна docs/23, Фаза 3) **відсутня** —
за протоколом SDD це означає, що деривативна підсистема зараз без контракту.

**D-5. Плече/ліквідація.** `default_leverage = Decimal(1)` жорстко
(`backtest_runner.py:189`), полів leverage немає ні в `Settings`, ні в `BacktestRequest`.
Для cash-and-carry це нормально, але має бути **явно** написано в спеці робота: шорт перпа
без моделі ліквідації — це припущення, а не факт.

---

## 5. Комісії: головний важіль дослідження зламаний в UI і розійшовся з документами

Факти:

1. `Settings` має лише `spot_maker_fee/spot_taker_fee/usdm_maker_fee/usdm_taker_fee`
   (`settings.py:180-183`); полів `maker_fee`/`taker_fee` **не існує** (перевірено
   `Settings.model_fields`).
2. `api/settings_schema.py:143-144` показує в UI поля **Maker fee / Taker fee**
   (`MAKER_FEE`/`TAKER_FEE`). Вони мертві: `PUT /api/settings` відповідає
   `400 Unknown setting key: MAKER_FEE` (перевірено `validate_settings_update`), а
   `SPOT_*`/`USDM_*` у схемі **не показані взагалі**.
3. Документи досі вчать саме цим двом: `docs/01:141`, `docs/02:126-129`,
   `docs/04:512`, `docs/06:200` («`paid_cost_bps=5.00` … це рівно `TAKER_FEE` з
   оточення»), `docs/07:535`, `docs/08:288`, `docs/10:653`. Сам `.env:57` уже визнає:
   «`MAKER_FEE`/`TAKER_FEE` … NOT read by Settings: they are leftovers».
   (Той самий хибний слід є і в `AGENTS.md` та скілі: «у цьому оточенні задано
   `MAKER_FEE`/`TAKER_FEE`, тож фактичні комісії беруться звідти» — насправді
   `MAKER_FEE=0.0002` у середовищі ігнорується, а діє `SPOT_TAKER_FEE=0.00075`.)
4. **Стрес-комісій немає в коді** (є лише стрес-зрізи періодів і поріг `min_breakeven_bps`
   у воротах). А план v3 вимагає двох сценаріїв витрат: базовий (VIP0+BNB) і стрес ×1.5.
   Єдиний спосіб зробити стрес сьогодні — вписати `SPOT_TAKER_FEE=0.001` у textarea `env`
   пакета вручну (`docs/33 §4` так і робить).

Це найдешевша правка з найбільшим ефектом: без неї «перп дешевший у 2–4 рази» неможливо
ані перевірити, ані порівняти, а число `paid_cost_bps` у звітах неможливо зіставити з
тарифом із кабінету.

---

## 6. Документаційні розбіжності, які треба закрити (дешево, до коду)

| # | що | доказ |
|---|---|---|
| DOC-1 | **`docs/31` і `docs/34` відсутні, але на них посилається код**: `docs/34` — 9 файлів (`ingest_archive.py:1`, `quality_gate.py:1`, `data_quality.py:1`, `catalog_service.py:117,171`, `data_health.py:198`, `routes/catalog.py:127`, `binance_vision.py:3`, `data_refresh.py:10`, `settings.py:216`); `docs/31` — `settings.py:168`, `regime_router.py:66` | файлів немає в `docs/` |
| DOC-2 | **«роадмап v3» не існує в репозиторії**, хоч на нього спирається план інгесту («вміщається в Ф0–Ф1 роадмапу v3») | план Binance/ф'ючерси, рядки 85 і 115 |
| DOC-3 | `specs/components/derivatives-data.yaml` обіцяна docs/23 (Фаза 3) — відсутня | `ls specs/components/` |
| DOC-4 | Спека `funding` каже `evidence.measured: false`, а STATUS.md — «не виміряно», хоч є 4 пакети з виміром (BTC 3/6 фолдів, 20 філів, breakeven 12.3 bps; ETH 4/6, 24 філи) | `specs/strategies/funding.yaml`, `docs/STATUS.md` |
| DOC-5 | `minimum_bars` для `funding`: у коді **15** (`run_research_backtest.py:79-80`), у скілі/доках — 50 | узгодити |
| DOC-6 | Комісії: 7 документів + `AGENTS.md` + скіл (див. §5) | — |

Окремо: пакет `20261003_182518_batch` уже **виміряв** `funding` (BTC/ETH), але результат
ніде не зафіксовано як evidence — при тому, що числа детерміновані й повторюються
від пакета до пакета (однакові `mean_oos`, `fills`, `breakeven` у 4 пакетах).

---

## 7. Лог рішень: що вже добре і що додати

Перевірено на реальному артефакті (`cells/regime_BTC/decisions/*`, 6 фолдів, 8233 записи):
схема `decision_trace/1`, `run_header` (параметри один раз) + `bar_decision` + `intrabar`;
кожен бар несе `outcome`, `blocked_by`, `signal`, `signal_reason`, `regime`, `states.stop_loss`,
`account`, `bar`, `narrative` українською і **масив `steps`**: `stage/component/verdict/
result/values/thresholds/note` з фактичними числами й **запасом до порогу**
(`er_margin_pct`, `margin_pct`, `dist_to_breakout_pct`, `apy_margin_pct`).

Розподіл outcome у клітинці: `NO_SIGNAL 3828`, `HOLD_NOOP 3237`, `WARMUP 900`,
`ENTRY_OPENED 87`, `ENTRY_FILLED 87`, `STOP_LOSS 49`, `EXIT 35`, `ENTRY_BLOCKED_RISK 4`;
запис входу містить `qty`, `fill_price`, `slippage_bps`, `fill_delay_s`, `fee`, а стоп —
`risk_pct`. Дайджест додає `forward`-доходність по групах (executed/blocked/vetoed) і
горизонтах, `near_misses`, `regime_switches/flip_flops`, пресет питання
`why_no_trades` і опційну LLM-відповідь офлайн-контуром. Це сильна підсистема — нижче
прогалини, а не «все погано».

| # | прогалина | доказ / наслідок |
|---|---|---|
| L-1 | **Розмір позиції не трасується як рішення** | `steps` показують результат (`position_plan` → `noop/entry`), але немає кроку «risk: чому саме 0.358» — `application/risk.py::size_position` не пише в журнал; `gate/risk.max_drawdown` є лише для 4 відмов. Питання «чому такий розмір» із логу не відповідається, хоч саме розмір робить дохідність |
| L-2 | **IS-рішення не пишуться** | пакет жорстко `DECISION_LOG_SCOPE=oos` (`run_batch_job.py:101`); єдиний слід вибору параметрів — рядок `selected=…`. У `trials/<cell>.jsonl` кандидати є, але UI їх не показує: «чому обрано `donchian=90`, а не 24» відповіді немає |
| L-3 | **Дайджест за замовчуванням змішує фолди** | `RunPage` передає `fold` з URL (типово порожній) → `/digest` конкатенує логи всіх фолдів (`routes/batches.py:376-379`): воронка й forward-доходність змішують різні OOS-вікна з **різними** обраними параметрами, і на екрані про це не сказано |
| L-4 | **Немає агрегату по матриці** | дайджест існує лише на клітинку; «який фільтр найчастіше блокував вхід у всіх 50 клітинках», «який breaker домінував» — не питається ніде, хоч `blocked_by` і `risk_breaches` рахуються |
| L-5 | **Комісія не прив'язана до рішення** | `fee` є в записі філу, але немає накопичувальної вартості/`breakeven` на рівні угоди й рішення; вкладка «Угоди» не показує ні `fee`, ні `pnl_source`, ні MFE/MAE (див. §3) |
| L-6 | **Розбіжність «еквіті в лозі» і «еквіті у звіті»** | для `funding` виплати фандингу додаються до еквіті стратегії (`funding_strategy.py:484`) і до реалізованого балансу звіту (`backtest_runner.py:209-211`), але **не** є транзакцією акаунта — тому `RiskEngine` і `account.equity` у журналі бачать еквіті **без** фандингу. Один прогін, два різні числа еквіті |
| L-7 | **Немає панелі осциляторів під графіком угоди** | прямо позначено як «ще не зроблено» в docs/30 |
| L-8 | **Найбільший клас відмов не має `blocked_by`** | `SIGNAL_VETOED` — 54 964 записи в корпусі, і в **усіх** `blocked_by=null`: `on_bar` перетворює `NO_SIGNAL`→`SIGNAL_VETOED` (`signal_strategy.py:355-356`), але код причини приходить з `_process_signal`, який для `signal is None` повертає `None`. Наслідок у UI: `blockedShare` (`frontend/src/lib/batch.ts:224-231`) рахує лише `ENTRY_BLOCKED*`, тож відхилення фільтрів (напр. meta-label) у воронку не потрапляють |
| L-9 | **Відмова фільтра позначена як `info`, а не `block`** | `filter/cointegration`: 850 081 `info/not_cointegrated` проти 109 930 `pass`; `filter/vpin`: 106 389 `info/normal`, 0 `block`. Тому 89% барів pairs не потрапляють у `_vetoed()`, у `blocked_by` і в жоден лічильник блоків — «pairs не торгує» читається як «немає сигналу», а не як «ворота коінтеграції закриті». **Лишається відкритим свідомо** (04.10): `INFO` тут — задокументований вибір автора (`pairs_trading.py::_fit_step`, закріплений `tests/unit/test_two_leg_decisions.py::test_pairs_fit_failure_is_explained`), бо на барі без фіта робот узагалі не оцінював вхід, і «цей крок відкинув сигнал» перебільшувало б. Той самий клас — у `funding` (`Verdict.INFO` на «net APY below min_net_apy» і «basis above basis_max»). Перевести це в `block` без втрати правди можна лише разом із рішенням про словник відмов (див. §10, питання 5): або `Verdict.BLOCK` лише коли вхід справді був на розгляді, або окреме поле `refused_by` для «ворота закриті, оцінювати не було чого». Одним махом це перейменує ~1 млн барів, тому — окреме рішення, не побічна правка |
| L-10 | **Пропущені бари в бектесті невидимі** | `bar_seq` пише лише paper-термінал (`paper_streamer.py:750,812`); у бектесті поля немає, тому `bar_seq_gaps = 0` у **106 з 106** `summary.json`, хоч docs/28 покладається саме на нього |
| L-11 | **Маржа зникає при нульовому порозі (тихий баг)** | `decision_trace.margin_pct` повертає `None`, коли `threshold == 0`, тому `apy_margin_pct` відсутній у **11 223 з 11 223** записів funding із `min_net_apy=0.0` і присутній у 2 041 з 2 041 із ненульовим. Гістограма `/margins` для цих прогонів просто порожня |
| L-12 | **Комісію виходу з журналу не видно** | `fee` є лише у `execution/fill` на вході (135 404 записи); вихід пише `paper_broker result="exit"` з `{side, qty, price}` без комісії й без ковзання (`trade_history.py:342-345` це визнає прямо). Дайджест комісії виключає свідомо (`decision_digest.py:12-14`), у `run_header.params` ставок теж немає — тож «чи з'їла комісія результат» із журналу рішень не читається |
| L-13 | **Фільтри docs/32 жодного разу не вмикалися, і їхній нарратив зламаний** | `filter/htf_trend` і `filter/vol_expansion` — **0 кроків** у корпусі, `ENTRY_FILTER*` — 0 входжень у всіх 10 `batch.json`. `render_narrative` на реальних кроках `entry_filters.py` дає `«HTF_TREND buy None / sell None — потік нормальний.»` (перевірено виконанням): гілки фільтрів у `decision_narrative.py:160-182` немає, тому числа й текст були б хибними |
| L-14 | **Доступ до журналу вузький** | на батч-роуті немає `since`/`until`, пагінації й експорту (`routes/batches.py:342-368`), фронт жорстко просить 200 рядків (`DecisionLogPanel.tsx:112`), CLI-команди для читання журналу не існує взагалі. Оцінка гнучкості за цим виміром — 4/10 |

---

## 8. План покращень

Позначки: **[дешево]** ≤ пів дня, **[середньо]** 1–3 дні, **[структурно]** > 3 днів.
Критерій приймання — те, що можна перевірити командою або тестом, а не «стало краще».

### Хвиля 0 — документаційна гігієна (пів дня, без ризику для коду)

1. **[дешево]** DOC-1: створити `docs/31-...` (перемикачі `REGIME_LEGS` тощо) і
   `docs/34-infrastruktura-danyh-ta-yakist.md` з наявного плану інгесту; або замінити
   посилання в коді. Приймання: `grep -rn "docs/3[14]" src | wc -l` → усі цілі існують.
2. **[дешево]** DOC-2: або додати роадмап v3 у `docs/`, або прибрати згадки й замінити
   посиланням на `docs/21`+`docs/27`. Приймання: жодного посилання на неіснуючий файл.
3. **[дешево]** DOC-3: створити `specs/components/derivatives-data.yaml` (за протоколом
   SDD — **до** коду деривативних змін) з `verified_by` на наявні тести й
   `test_missing_reason` там, де тестів немає.
4. **[дешево]** DOC-4/5/6: оновити `evidence` у `specs/strategies/funding.yaml` реальними
   числами з пакета (з посиланням на `reports/batches/<id>`), узгодити `minimum_bars`,
   виправити 7 документів + `AGENTS.md` + скіл щодо `MAKER_FEE`/`TAKER_FEE`.
   Приймання: `.venv/bin/python specs/_validator.py` зелений; `grep -rn "TAKER_FEE" docs/`
   дає лише `SPOT_TAKER_FEE`/`USDM_TAKER_FEE`.

### Хвиля 1 — комісії як керований важіль (1–2 дні; розблоковує порівняння спот↔перп)

5. **[дешево]** Прибрати мертві `MAKER_FEE`/`TAKER_FEE` зі `settings_schema.py:143-144` і
   додати групу «Fees» з `SPOT_MAKER_FEE/SPOT_TAKER_FEE/USDM_MAKER_FEE/USDM_TAKER_FEE`.
   Приймання: новий тест `tests/unit/test_settings_schema.py` перевіряє, що **кожен**
   ключ схеми приймається `validate_settings_update` (саме цей тест зловив би сьогоднішній баг).
6. **[середньо]** Профілі витрат: `cost_profile` у `BacktestRequest`/`BatchRequest`
   (`spot_vip0_bnb` 7.5/7.5, `um_vip0_bnb` 1.8/4.5, `stress_x1_5`) + селектор у формі
   пакета й у `AdvancedGates`; профіль записується в `batch.json` і в `provenance`.
   Приймання: два пакети з різними профілями дають різні `paid_cost_bps`, а в
   `batch.json` видно, який профіль застосовано; жодного ручного `env`.
7. **[дешево]** У формі пакета — валідація env-ключів проти `Settings.model_fields` і
   підсвічування невідомих (S-4), плюс 1–2 рядки «довільний KEY=value» в
   `ParamOverrides` (S-3). Приймання: `RISK_PER_TRADE=0.02` або застосовується, або
   показує помилку — третього варіанта немає.

### Хвиля 2 — деривативи: зробити бектест на перпах і funding справді запускним (3–5 днів)

8. **[структурно, але з негайним обхідним шляхом]** Розв'язати D-1 в ADR і коді:
   - обхід сьогодні: зібрати спільний каталог `catalog_perp_4h_combined` (спот+перп+funding
     для 11 монет) архівним інгестом — **нуль змін коду**, і `funding` біжить на SOL/DOGE/ADA;
   - довго: `funding_spot_catalog`/`funding_perp_catalog`/`funding_series_catalog` у
     `BacktestRequest` + проводка в `bar_feed.load_multi` і `_FundingFeedAdapter`.
   Приймання: клітинка `funding_SOL` у пакеті дає `status=ok` і ненульові `fills`;
   тест на `plan_cells` не позначає її `blocked`.
9. **[середньо]** Долити `funding` для всіх 11 монет з архіву (D-2) — заодно закриває
   дірку 2020–2023, критичну для H-C (саме 2021 рік мав найвищі ставки).
   Приймання: `data/funding/BTCUSDT` у перп-каталозі починається з 2020-01, не з 2023-10.
10. **[середньо]** Провести реальний mark/index у снапшот фандингу (D-3): або розширити
    `FundingRateUpdate`-шлях, або окремий фід з `data/funding`/`premium_index`. Тоді гейт
    `basis_max` відповідає спеці, і гілка «index unknown» стає досяжною.
    Приймання: тест «снапшот несе інгестовані mark/index, а не клоузи барів»; у спеці
    `funding.yaml` описано, що саме міряє базис.
11. **[дешево]** `lab research --instrument/--interval/--market` (зараз лише через env,
    `cli.py:204-331`; API/UI це вже вміють — асиметрія CLI↔UI).
    Приймання: `lab research --instrument ETHUSDT-PERP.SIM --interval 4h --catalog catalog_perp_4h`
    дає той самий результат, що мій прогін через env.
12. **[дешево]** У спеці `funding` зафіксувати припущення: плече 1×, ліквідація не
    моделюється (D-5).

### Хвиля 3 — пакет: перестати планувати неможливе і почати порівнювати (3–5 днів)

13. **[середньо]** Pre-flight на рівні серії (B-1): у `plan_cells` — `series_probe(catalog,
    instrument_id, interval)` + `needs` робота (спот-бари / перп-бари / `data/funding/<SYM>`)
    + перевірка покриття запитаного вікна; у прев'ю показувати розв'язаний інструмент,
    каталог, вікно, кількість барів. Приймання: пакет із 7 монетами дає `blocked` для
    `funding_SOL/…` **до** старту; тест у `tests/unit/test_batch.py` на це.
14. **[структурно]** Варіанти в матриці (B-2): `variants: [{name, env}]` × robots × symbols,
    `cell_id = f"{robot}_{base}__{variant}"`, per-robot overrides замість спецвипадку
    `funding`. Приймання: H0/H1/H2/H3 для `regime` біжать **одним** пакетом, а таблиця
    показує колонку варіанта.
15. **[середньо]** Порівняння: у межах пакета — рейтинг із сортуванням за `breakeven`,
    `cost_headroom`, часткою прибуткових фолдів і вердиктом; між пакетами — «diff двох
    пакетів» по тих самих `cell_id`/варіантах. Приймання: H1 vs H0 видно одним екраном.
16. **[дешево]** `POST /api/batches/{id}/retry` (тільки failed/blocked/cancelled) і
    `timeout_seconds` на клітинку/робота в запиті (B-4). Приймання: після таймауту
    доганяється одна клітинка, не 50.
17. **[дешево]** Реєстрація пакета в `JobManager` + `JOB_TABS['batch']` + полінг `RunPage`
    поки статус `queued|running` (B-3). Приймання: тост про завершення приходить без
    відкритої сторінки пакета; відкрита під час роботи клітинка оновлюється сама.
18. **[дешево]** У формі пакета — `is_fraction`, `embargo_bars`, селектор каталогу зі
    списку замість вільного тексту, інструменти з реєстру з покриттям (як у
    `BasicControls.tsx:87-95`), і збереження форми (як `lib/researchForm.ts:44`).

### Хвиля 4 — інформативність: вердикт, гроші, причина (2–3 дні)

19. **[середньо]** Persist: `promotion_gate` (структуровано, а не рядком логу),
    `risk_breaches`, і бракуючі поля `multi_window` (`median_oos`, `spread`,
    `vol_matched_buy_and_hold`, `cost_headroom`) у `last_run.json`/`summary.json`.
    Приймання: вердикт і breaker-талі читаються з `summary.json`, а не з `stdout`.
20. **[дешево]** Сторінка прогону: рендерити `run.result` (equity-крива, per-fold метрики,
    cost-картки) — **нуль нових запитів і нуль змін бекенду**; бейдж `PROMOTE/REJECT/
    INCOMPLETE` у шапці клітинки й у таблиці пакета. Приймання: те саме, що показує
    Research Lab, видно на клітинці пакета.
21. **[дешево]** Кнопка «перегнати цю клітинку як кандидата»: відкриває Research Lab із
    тим самим роботом/інструментом/вікном + `--pbo --register`. Це єдиний шлях до
    `PROMOTE`, і зараз він неочевидний.
22. **[дешево]** Виправити `ftx_collapse` → `ftx2022` і брати список слайсів зі `/api/status`
    (S-6); folds у Research — не 1/2/4/8, а вільне число з preflight (S-5).
23. **[середньо]** Вкладка «Угоди»: `fee`, `pnl_source`, `qty_known`/`fee_known`, MFE/MAE,
    `exit_reason`, `duration_seconds` (дані вже приходять, тип їх вимагає).
24. **[середньо]** Лог рішень: крок sizing у `risk.py` (L-1); IS-слід вибору параметрів —
    топ-N кандидатів із `trials/<cell>.jsonl` на сторінці прогону (L-2); прибрати
    змішування фолдів у дайджесті за замовчуванням — або вимагати фолд, або явно писати
    «усі фолди разом» (L-3); агрегат `blocked_by`/`risk_breaches` по матриці (L-4).
24a. **[дешево, найкраще співвідношення в усьому документі]** `blocked_by` для внутрішніх
    вето (`signal_strategy.py:355-356`) — один рядок, і 54 964 записи `SIGNAL_VETOED`
    перестають бути «невидимими» у воронці (L-8); `bar_seq` у бектест-писареві
    (`signal_strategy.py:982-1001`) — ще одне поле, і `bar_seq_gaps` починає ловити
    пропущені бари (L-10); `INFO`→`BLOCK` для відмов фільтрів (L-9); маржа при нульовому
    порозі (L-11); гілки `htf_trend`/`vol_expansion` у нарративі (L-13) — інакше перший же
    прогін із фільтрами docs/32 напише «buy None / sell None».
25. **[структурно]** L-6: або нараховувати фандинг в акаунт рушія (щоб `RiskEngine` і
    журнал бачили ту саму еквіті, що звіт), або явно назвати колонку в журналі
    «engine equity (funding excluded)». Мовчазна розбіжність неприпустима для робота,
    у якого фандинг — це весь альфа.

---

## 9. Пріоритети (вплив × вартість)

| Пріоритет | Що | Чому саме зараз |
|---|---|---|
| 🟢 P0 | Хвиля 0 (документи) + #5 (мертві фі) + #13 (pre-flight серій) + #20 (вердикт і `run.result` на екран) | години роботи; прибирає фальшиві прогони, брехливі контроли й «сліпий» вердикт |
| 🟢 P0 | #8 обхід (спільний каталог) + #9 (funding 11 монет з 2020) | без цього деривативи не тестуються взагалі; заодно закриває 2020–2023 для H-C |
| 🟡 P1 | #6 профілі витрат + #11 `--instrument/--market` | без керованих комісій «перп дешевший» неперевірне; CLI без інструмента — пастка |
| 🟡 P1 | #14 варіанти в пакеті + #16 retry + #17 джоба + #18 форма | перетворює 5 пакетів по 8 год на один порівнюваний експеримент |
| 🟡 P1 | #10 mark/index у базис, #19 persist вердикту/breaker-ів | коректність гейта базису і чесний вердикт у даних |
| ⚪ P2 | #15 diff пакетів, #21 кнопка кандидата, #23 «Угоди», #24 лог-кроки, #25 еквіті | інформативність і зручність; робити після P0–P1 |

---

## 10. Відкриті питання, які треба вирішити рішенням (ADR), а не кодом

1. **Каталоги: спільний ринок чи per-leg шляхи?** Обхід (спільний каталог) швидкий, але
   прямо конфліктує з B6 плану інгесту. Якщо обрати per-leg — треба ADR і оновлення
   `data-catalog` спеки.
2. **Фандинг в акаунті чи поза ним?** Від цього залежить, чи можна довіряти `max_dd`,
   `daily_loss` і breaker-ам на carry-роботі.
3. **Плече.** Лишаємо 1× назавжди (тоді це прямо в спеці) чи вводимо поле з моделлю
   ліквідації (тоді це окрема велика задача зі стрес-сценаріями)?
4. **Що вважаємо «прогоном» у пакеті?** Якщо мета — тріаж, то `promotion_gate` у пакеті
   може бути свідомо `INCOMPLETE`; якщо мета — ворота, то пакет мусить уміти `--pbo`
   і `--register` (інакше UI має чесно писати «цей пакет не може пройти ворота»).
5. **Словник відмов (L-9).** Три варіанти, і вибір не технічний, а смисловий:
   `INFO` (як зараз — «оцінив, діяти нема чого», але відмову не порахувати),
   `BLOCK` (порахувати можна, але на барі без наміру входу це перебільшення),
   або окреме поле `refused_by` поруч із `verdict` («ворота закриті» ≠ «сигнал відкинуто»).
   Третій варіант найдорожчий у коді, але єдиний, що не змушує вибирати між правдою й
   вимірюваністю.

## 11. Чого в цьому аудиті немає

- Жодного прогону, крім одного вказаного в §0; решта чисел — з наявних артефактів
  `reports/batches/*` і з корпусу журналів рішень (48 581 файл, 6 108 647 записів).
- Жодної оцінки прибутковості роботів: результати живуть у `docs/05-roboty.md`,
  `docs/STATUS.md` і `research/journal.md`, а не в плані покращень.

## 12. Виконано в P0-хвилі (04.10.2026)

| # | Що зроблено | Файли | Як перевірено |
|---|---|---|---|
| 1 | Мертві поля `MAKER_FEE`/`TAKER_FEE` прибрано зі схеми; додано групу **Exchange Fees** зі справжніми ключами `SPOT_*`/`USDM_*` | `api/settings_schema.py` | новий тест «кожен ключ схеми приймається `PUT /api/settings`» — саме він ловив би цей баг |
| 2 | Pre-flight перевіряє **серію**, а не теку каталогу: бари інструмента, обидві ноги `funding` в одному каталозі й файл розрахунків; `pairs` — обидві ноги | `application/batch_plan.py`, `api/routes/batches.py` (`_series_probe`) | 4 нові тести; на реальному диску пакет із 7 монет тепер блокує 5 клітинок `funding` **до** старту замість 8 годин прогону |
| 3 | Вердикт воріт став даними: `promotion_gate` у `last_run.json`, у рядку таблиці пакета й у шапці прогону (бейдж + перелік перевірок) | `api/serializers.py`, `api/research_runner.py`, `api/batch_store.py`, `frontend/.../GateBadge.tsx`, `BatchTablePage.tsx`, `RunPage.tsx` | 3 нові тести (серіалізація, прохід у рядок, перебудова застарілого кеша `summary.json` через `SUMMARY_VERSION`) |
| 4 | DOC-1: відновлено `docs/31` (перемикачі `REGIME_LEGS`, фільтри входу) і `docs/34` (перейменовано план інгесту — на нього посилаються 13 місць у коді); `docs/README.md` доповнено | `docs/31-*`, `docs/34-*`, `docs/README.md` | `grep -rn 'docs/3[14]' src` — усі цілі існують; валідатор зелений |
| 5 | DOC-3: створено `specs/components/derivatives-data.yaml` (16 інваріантів, 6 прогалин названі через `test_missing_reason`) | `specs/components/derivatives-data.yaml`, перегенерований `docs/STATUS.md` | `specs/_validator.py` → 24 спеки, 0 помилок; `tests/unit/test_specs.py` зелений |
| 6 | DOC-6: комісії в документації приведено до коду (`SPOT_*`/`USDM_*`, `spot_fee_schedule()`), включно з `AGENTS.md`, скілом, `docs/03`, `docs/12`, `docs/14`, `docs/18`, `docs/27`, UML | 15 файлів документації | `grep` не лишає тверджень про працюючі `MAKER_FEE`/`TAKER_FEE` |
| 7 | DOC-2: примітка, що «роадмап v3» — зовнішній документ, а в репо є `docs/21`+`docs/27` | план Binance/ф'ючерси | — |

Гейти після змін: `pytest` — 1393 passed, 1 skipped; `mypy src tests` — чисто (332 файли);
`ruff check`/`format` — чисто по змінених файлах (єдине зауваження в дереві —
`tests/unit/test_formulaic_modules.py:92`, E501, не з цієї зміни); фронтенд —
`tsc --noEmit`, `vitest` (269 тестів) і `oxlint` (0 помилок) зелені.

**Дві знахідки з першої ж перевірки кандидатного режиму** (обидві виправлені, обидві було видно
лише тому, що вердикт став даними):

1. Реєстрація й прогін в одному джобі давали `preregistered=fail` із поясненням
   «registered after the run»: ворота відмовляють, якщо `registered_at >= run_started_at`, а час
   старту брався один раз — на початку джоба, тобто **до** запису умов. Тепер початок виміру
   береться після запису реєстрації: обіцянку дано раніше, ніж щось виміряно, і це те, що
   перевіряють ворота.
2. Вердикт показував `pbo=pass, dsr=not measured`, хоча аудит рахував DSR (`observations=8`):
   ворота перераховують DSR із OOS **денних** доходностей walk-forward, а фікстура з
   `synthetic_regime_ohlcv` (крок 1 хвилина) вміщається в одну добу. Це не дефект коду, а
   вимога до даних — і саме тому тест на `promote` тепер будує серію з кроком 4h.

Поза хвилею P0 (свідомо): зміни в самій логіці бектесту й у журналі рішень — це P1–P2
(§8 хвилі 1–4), зокрема пункти 24a з L-8…L-13.

## 13. Друга хвиля: лог рішень (04.10.2026, продовження)

Закрито три з шести прогалин корпусу — усі в тому самому місці, де дані вже були, але
читач їх не бачив:

| Прогалина | Що змінено | Тест |
|---|---|---|
| **L-8** (54 964 `SIGNAL_VETOED` без причини) | `domain/decision_trace.py::veto_reason` — спільний для писарів; `signal_strategy` пише `blocked_by=<stage>.<component>` (`filter.regime_legs`, `filter.htf_trend`, `filter.meta_label`…). Мертвий `_vetoed` прибрано | `tests/integration/test_backtest_decision_trace.py::test_a_vetoed_signal_names_the_step_that_blocked_it` — реальний прогін `regime` з `REGIME_LEGS=range`, перевіряє і запис, і `digest.blocked_by` |
| **L-10** (`bar_seq` у бектесті не писався, `bar_seq_gaps=0` у 106/106) | лічильник у `SignalRobot` інкрементується в єдиному писарі `_record_decision_log`, тож жоден шлях не може його забути, а intrabar-запис не збиває послідовність | `test_backtest_records_carry_a_monotonic_bar_seq` — послідовність 1..N і `bar_seq_gaps == 0` на синтетиці без дірок |
| **L-13** (нарратив фільтрів писав «buy None / sell None — потік нормальний») | гілки `htf_trend`, `vol_expansion`, `regime_legs`, `min_hold_bars` у `application/decision_narrative.py` | `test_narrative_speaks_the_entry_filters_not_the_flow_reading` — бере **справжні** кроки `entry_filters.py`, вимагає відсутності `None` і правильних слів |
| **L-11** (немає `apy_margin_pct` при `min_net_apy=0`) | закрито як **пояснене**, а не «полагоджене»: відсоток від нульового порогу не існує математично, а сирі `net_apy` і `min_net_apy` у кроці лишаються — доказів не втрачено | `test_a_zero_threshold_has_no_margin_but_keeps_its_numbers` фіксує саме це |
| **L-1** (у 6.1 млн записів немає жодного числа про розмір позиції) | новий крок `plan/sizing` у **обох** писарях: `signal_strategy` (бектест) і `paper_streamer` (живий термінал), однакові назви полів — `equity`, `risk_fraction`, `risk_cash`, `qty_risk_based`, `stop_distance`, `atr`, `notional`, `notional_cap_hit` + пороги `risk_per_trade`/`stop_pct`/`kelly_fraction`/`vol_scaling_target`/`qty_step`. Нарратив має гілку `_sizing` | `test_an_entry_carries_the_arithmetic_behind_its_size` (реальний прогін: `risk_cash == equity × risk_fraction`, `qty > 0`, крок на барі входу) і `test_both_writers_explain_the_size_the_same_way` (паритет полів між рушієм і терміналом, старий виклик без `steps` не ламається) |

**Перший реальний прогін на кроці сайзингу відразу дав знахідку**, якої доти не було видно з
жодного логу: у smoke-прогоні `regime` на синтетиці **стеля 1× notional стримує розмір на
кожному вході** — `risk_fraction=0.005` давав 161.394 од., а стеля зрізала до 120.752, тобто
`risk_per_trade` там фактично не діє, і жодне регулювання ризику на бар не впливає. Саме тому
крок пише `qty_risk_based` і `notional_cap_hit` окремо: «бюджет ризику вичерпано» і «розмір
зрізала стеля» — протилежні за змістом відповіді для ризик-рев'ю. Порівняння йде з
**неокругленим** розміром: округлення до `qty_step` залишає notional на волосину нижче equity,
і перша версія перевірки (`notional >= equity`) через це не спрацьовувала на реальному прогоні.

Що лишилось у L-1 на майбутнє: числовий слід **вибору** параметрів на IS (L-2) — у журналі є
ефективні параметри прогону, але не те, чому обрано саме їх; кандидати лежать у
`trials/<cell>.jsonl` і в UI не показані.

| **L-2** (у звіті є переможець і `tried=N`, але не видно, **чому** саме він) | пошук більше не викидає невдах: `dtos.CandidateScore` (label + оцінка + IS-дохідність) збирається в `run_walk_forward._grid_search_params`, їде у фолд/звіт, серіалізується як `candidates` + `selection_metric` (`pnl`/`sharpe`/`calmar`) і показується новим компонентом `SelectionRanking` — на сторінці прогону пакета **і** в Research Lab. Optuna чесно віддає `label` без чисел (вона не зберігає параметри спроби) | `test_the_fold_keeps_the_whole_in_sample_ranking` (рейтинг best-first, переможець перший, метрика названа), `test_serialize_fold_carries_the_in_sample_ranking` (+ версія для `serialize_walk_forward`) |
| **§8 п.19–21** (клітинка пакета не могла пройти ворота: без `--register` і без PBO вердикт завжди `INCOMPLETE`) | у прогоні дослідження з'явилися **`register`** (умови тесту пишуться на диск **до** першого бектесту, вікна фолдів рахуються `plan_multi` без прогону) і **`promote`** (після walk-forward доганяється аудит PBO/CSCV, і ворота читають обидві половини). Через це вердикт уперше може бути `PROMOTE`, а всі перевірки — виміряними. Дашборд: поле гіпотези й перемикач «Кандидат» у Advanced gates, кнопка «Перегнати як кандидата» на сторінці прогону клітинки (передає робота, інструмент і кількість фолдів у Research Lab; гіпотезу вписує людина — це її обіцянка, не дашборда). Комбінації, які не можуть пройти ворота (`register` без `folds ≥ 2`, реєстрація синтетики, `register`+`pbo`, `promote`+`pbo`, `promote`+`full-sample`), відмовляються з назвою причини — і на бекенді, і в preflight | `tests/integration/test_candidate_run.py` (реєстрація→`preregistered=pass`, `promote`→`pbo` і `dsr` виміряні, шість відмов із текстом), preflight-тести у `frontend/src/lib/research-logic.test.ts`, `toRunParams`-тести у `researchForm.test.ts` |
| **B-2** (§8 п.14: матриця пакета одновимірна, гіпотези — окремими пакетами) | з'явився вимір **`variants`**: іменовані набори env, кожна клітинка виконується по разу на варіант (`regime_BTC__H1`), групування варіант-перше, валідація (ім'я, унікальність, `SETTINGS_NAME`, стеля `MAX_VARIANTS=8`), round-trip у `batch.json` (перезапуск переплановує ту саму матрицю). Дашборд: поле «Варіанти (гіпотези)» з блоками `[НАЗВА]`, парсер `parseVariants` (з помилкою замість частково зрозумілої матриці), чип варіанта в таблиці пакета | `test_variants_run_the_whole_matrix_once_per_hypothesis`, `test_a_plain_batch_keeps_the_cell_ids_it_always_had`, `test_variants_are_validated_and_survive_a_restart`, `parseVariants`-тести у `frontend/src/lib/batch.test.ts`; наскрізна перевірка `POST /api/batches` з `dry_run`: 3 варіанти × 2 монети → 6 клітинок одним пакетом, некоректна назва → 422 |

**Перший реальний прогін і на цьому кроці дав знахідку** (BTC/USDT.SIM, 1h, 200 днів, 3 фолди):
переможець на фолді 0 — `donchian=120 bb_k=2` з **від'ємною** IS-дохідністю **−1.85%**, і він
випередив другого кандидата на ~1% оцінки (97 287 проти 96 313), тоді як усі 15 кандидатів на
IS були в мінусі. Тобто підбір обрав «найменш поганого», а не прибуткового — саме та різниця,
яку раніше з артефакту не було видно: `selected=…` виглядало як усвідомлений вибір. У клітинках
пакета сітки менші (3–15 кандидатів на фолд за реальними `last_run.json`), тож рейтинг додає
до артефакту одиниці кілобайт.

**L-9 лишається відкритим свідомо** — див. §10, питання 5. Спроба зробити `cointegration`
вердиктом `BLOCK` валить зафіксований тест `test_pairs_fit_failure_is_explained`, і це не
«тест заважає»: `INFO` там означає «ворота закриті, оцінювати не було чого», а `BLOCK` —
«сигнал відкинуто». Різниця смислова, і вирішувати її одним рядком у чужій семантиці
означало б перебільшити ~1 млн барів. З тієї ж причини не додано дзеркальну правку в
`spread_strategy`: жоден двоногий робот сьогодні не видає `BLOCK` у `FILTER`/`STRATEGY`,
тож це був би мертвий код із коментарем, який обіцяє більше, ніж робить.
