# 10. Довідник CLI

Точний синтаксис усіх команд. Команда `lab` — єдина точка входу проєкту.

```bash
uv run lab <команда> [прапорці]
```

Якщо `uv` не має доступу до свого кеша — `.venv/bin/lab <команда>`.

| Команда | Що робить | Код виходу при помилці |
|---------|-----------|------------------------|
| `lab ingest` | Завантажує публічні klines Binance у Parquet-каталог | 1 |
| `lab research` | Бектест/симуляція (основний шлях; за замовчуванням walk-forward) | 1 |
| `lab paper` | Лог гіпотетичних ордерів, без виконання | 1 |
| `lab scan` | Дослідницькі сканери (трикутний арбітраж) | 1 |
| `lab propose` | Офлайн-опитування LLM про гіпотези альф (не торгує) | 1 |
| `lab live` | **Завжди помилка** (жива торгівля вимкнена) | 1 завжди |

Успіх будь-якої команди → код виходу `0`, повідомлення про помилки друкуються в `stderr`.

---

## `lab ingest`

```
usage: lab ingest [-h] [--start START] [--end END] [--catalog CATALOG] [--symbols SYMBOLS]
                  [--incremental] [--funding]
```

| Прапорець | Типово | Опис |
|-----------|--------|------|
| `--start` | 365 днів тому | Початок вікна (UTC, `YYYY-MM-DD`) |
| `--end` | зараз | Кінець вікна (**виключно**, UTC) |
| `--catalog` | `CATALOG_PATH` з `.env` (`catalog`) | Тека каталогу |
| `--symbols` | `BINANCE_SYMBOLS` з `.env` (`ETHUSDT,BTCUSDT`) | Символи через кому |
| `--incremental` | вимкнено | Дозавантажити лише те, що після останнього збереженого бару |
| `--funding` | вимкнено | Вантажити **ставки фандингу** замість klines (див. нижче) |

Що робить: публічний REST `https://api.binance.com/api/v3/klines`, пагінація по 1000 свічок,
без API-ключів. Інтервал беруть із `BAR_INTERVAL` (типово `1h`). Записує бари й опис інструмента в каталог.

Крім барів, ingest зберігає **потік тейкерів** — поле 9 klines
(`takerBuyBaseAssetVolume`) — окремою серією `<catalog>/data/taker_flow/<SYMBOL>/taker_flow.parquet`
(теж Parquet + Zstd, `Decimal` рядком, ключ — час закриття бару). Це не дублювання обсягу:
Nautilus `Bar` не має колонки під taker-обсяг, тож без окремої серії значення гине на
round-trip через рушій і VPIN доводиться рахувати проксі tick-rule. `ResearchBarFeed`
підмішує серію назад у бари за міткою часу (Фаза 4, docs/23 §6).

Запити йдуть через стійкий клієнт (`infrastructure/http_resilience.py`): він читає
`X-MBX-USED-WEIGHT-1M` і вичікує вікно при ≥90% ліміту, поважає `Retry-After` на HTTP 429,
повторює 418 (бан IP) і 5xx з експоненційним backoff. Коли спроби вичерпано — кидає помилку,
а не пише обрізану серію.

Приклади:

```bash
uv run lab ingest --start 2025-01-01
uv run lab ingest --start 2025-01-01 --end 2025-08-01 --symbols ETHUSDT
uv run lab ingest --start 2019-01-01 --end 2025-01-01 --symbols ETHUSDT,BTCUSDT --catalog catalog_long
uv run lab ingest --funding --start 2024-01-01 --symbols ETHUSDT,BTCUSDT
```

Вивід:

```
symbol=ETHUSDT wrote=5088 taker_flow=5088 first=2025-01-01T00:59:59.999000+00:00 last=2025-07-31T23:59:59.999000+00:00 catalog=/.../catalog
```

`taker_flow=0` означає, що серії потоку немає (фід без поля 9 або старий каталог), і VPIN
працюватиме на tick-rule-проксі. `--incremental` на каталозі без цієї серії робить разовий
backfill усього вікна й друкує `taker-flow backfill: re-reading the full window` — інакше
«бари вже свіжі» назавжди лишало б ознаку потоку порожньою.

### `lab ingest --funding`

Вантажить **ставки фандингу** USD-M (`https://fapi.binance.com/fapi/v1/fundingRate`, теж без
ключів) у `<catalog>/data/funding/<SYMBOL>/funding.parquet`. Це не OHLCV, а подієва серія, тому
вона живе окремим піддеревом і не змішується з барами. Інтервал і `BAR_INTERVAL` тут не діють:
фандинг розраховується за розкладом біржі.

Пагінація обов'язкова: сторінка вміщає 1000 розрахунків, тобто ~333 дні за типового розкладу
(три розрахунки на добу по 8 год).

`index_price` береться з окремого ендпоінта `fapi/v1/indexPriceKlines` і джойниться за годиною
розрахунку. Якщо індекс не зійшовся, він лишається **невідомим** (`None`), а не підміняється
mark price: у відповіді `fundingRate` поля `indexPrice` не існує, і саме така підміна робила
базис `(mark − index)/index` тотожним нулем.

Вивід (реальний прогін):

```
symbol=ETHUSDT funding=1878 missing_index_price=0 first=2025-01-01T00:00:00.015000+00:00 last=2026-09-18T16:00:00+00:00 catalog=/.../catalog
```

Повторний ingest вікна, що перекривається, **не** створює дублікатів: серія зливається за часом
розрахунку, найновіший запис перемагає.

Помилки:
- `binance klines error: {...}` — біржа повернула помилку (невідомий символ, обмеження).
- `unsupported binance symbol: XXX` — символ не закінчується на `USDT` (підтримуються лише `*USDT`).
- `no public klines for SYMBOL ... in [start, end)` — у вікні немає даних.
- `no public funding settlements for SYMBOL ... in [start, end)` — те саме для `--funding`.
- `... answered HTTP 400; not retryable` — вікно, якого біржа не обслуговує (напр.
  `openInterestHist` не віддає історію глибше ~30 днів), або невідомий символ.
- `gave up after N attempts` — вичерпано бюджет повторів на 429/418/5xx.

> ⚠️ **Один каталог — один ingest.** Повторний запуск із вікном, що перекривається, створить
> дублікати барів і зламає всі наступні `lab research`. Деталі: [04](04-tsykl-doslidzhennya.md#крок-1-ingest--завантаження-історії).

---

## `lab research`

```
usage: lab research [-h] [--bars BARS]
                    [--robot {regime,ema,pairs,vpin_momentum,formulaic_lgbm,meta_label,
                              adaptive_ema,funding,ml_obi,glft,tri_scan}]
                    [--synthetic] [--full-sample] [--walk-forward]
                    [--is-start IS_START] [--is-end IS_END]
                    [--oos-start OOS_START] [--oos-end OOS_END]
                    [--is-fraction IS_FRACTION] [--catalog CATALOG]
                    [--slice SLICE] [--embargo-bars EMBARGO_BARS] [--bar-vpin]
                    [--tearsheet TEARSHEET] [--optuna] [--trials TRIALS]
                    [--folds FOLDS] [--notify] [--pbo] [--pbo-blocks PBO_BLOCKS]
```

| Прапорець | Типово | Опис |
|-----------|--------|------|
| `--bars` | `3000` | Кількість барів для синтетичного режиму |
| `--robot` | `ROBOT` з `.env` (`regime`) | Який робот запускати. Підключені до рушія (7 із 11 значень `RobotName`): `regime`, `ema`, `pairs`, `vpin_momentum`, `formulaic_lgbm`, `meta_label`, `adaptive_ema`. `funding`, `ml_obi`, `glft`, `tri_scan` **падають з помилкою** (код 1), бо адаптера ще немає — див. [05](05-roboty.md#0-таблиця-стану-читати-першою) |
| `--synthetic` | вимкнено | Синтетичні бари замість каталогу (мережа не потрібна). Режим **повного прогону**, не walk-forward |
| `--full-sample` | вимкнено | Один прогін каталогу на всій серії. **Не** є out-of-sample звітом |
| `--walk-forward` | увімкнено для каталогу | Підбір на in-sample, звіт на out-of-sample |
| `--is-start`, `--is-end` | — | Вікно in-sample (UTC, `YYYY-MM-DD`, кінець виключно) |
| `--oos-start`, `--oos-end` | — | Вікно out-of-sample |
| `--is-fraction` | `0.7` | Частка історії на підбір, коли дати не задані |
| `--catalog` | `CATALOG_PATH` | Тека каталогу |
| `--slice` | — | Стрес-період: `covid2020`, `ftx2022`, `etf2024` |
| `--embargo-bars` | `EMBARGO_BARS` (`10`) | Розрив між IS і OOS |
| `--bar-vpin` | вимкнено | Увімкнути VPIN-фільтр режиму (робот `regime`) |
| `--tearsheet PATH` | — | Зберегти інтерактивний HTML-звіт (тиршит) за вказаним шляхом |
| `--optuna` | вимкнено | Замінити перебір сітки на байєсівську оптимізацію (Optuna TPE) на in-sample |
| `--trials N` | `20` | Кількість спроб Optuna (працює лише з `--optuna`) |
| `--folds N` | `1` | Кількість ковзних фолдів. `N >= 2` → **окремий walk-forward на кожен фолд** і звіт-агрегат out-of-sample замість однієї нарізки; `N == 1` — звичайний єдиний спліт; `N < 1` — помилка (код 1) |
| `--notify` | вимкнено | Надіслати сповіщення про завершення (Telegram/Webhook) |
| `--pbo` | вимкнено | **Аудит перенавчання (PBO/CSCV)** замість звичайного прогону: кожна конфігурація сітки оцінюється на кожному блоці історії. Див. [нижче](#pbo--аудит-перенавчання) і [15](15-audit-vypravlennya.md) |
| `--pbo-blocks N` | `8` | Кількість послідовних блоків історії для `--pbo`. `N < 2` — помилка (код 1) |
| `--journal` | вимкнено | Дописати рядок про цей прогін у журнал дослідження (`research/journal.md` + `research/journal.jsonl`). Див. [нижче](#journal--журнал-дослідження) |

Логіка вибору режиму:

0. `--pbo` має найвищий пріоритет: він повністю замінює звичайний прогін (див. нижче).
1. `--synthetic` без `--walk-forward` → синтетичний повний прогін.
2. `--synthetic --walk-forward` (або `--synthetic --optuna`) → синтетичний **walk-forward** (1-хвилинні бари).
3. `--full-sample` → один прогін по всьому каталогу (лише in-sample).
4. інакше → walk-forward по каталогу (типово).
5. `--folds N` з `N >= 2` перекриває пункти 2 і 4: замість однієї нарізки виконується **N ковзних
   walk-forward**. Працює і на каталозі, і на `--synthetic`, і для всіх трьох підключених роботів
   (`regime`, `ema`, `pairs`).

Спосіб підбору параметрів:
- типово — **сітка** (`tried=6` для `regime`, `4` для `ema`, `3` для `pairs`);
- з `--optuna` — **байєсівська оптимізація** Optuna TPE, `tried=` дорівнює кількості trials.
  У рядку звіту це видно: `walk-forward (grid):` або `walk-forward (optuna):`.

Приклади:

```bash
uv run lab research --synthetic --bars 5000              # швидкий smoke-тест
uv run lab research                                     # walk-forward, regime, каталог
uv run lab research --robot ema                          # baseline
uv run lab research --robot pairs                        # дві ноги
uv run lab research --full-sample                        # вся вибірка, лише in-sample
uv run lab research --is-fraction 0.5 --embargo-bars 0   # інша нарізка
uv run lab research --bar-vpin                           # VPIN-фільтр
uv run lab research --slice etf2024 --catalog catalog_long
uv run lab research --is-start 2025-01-01 --is-end 2025-05-01 \
                    --oos-start 2025-05-15 --oos-end 2025-07-01 --catalog catalog_ok
uv run lab research --optuna --trials 30                   # байєсівський підбір замість сітки
uv run lab research --tearsheet reports/tearsheet.html     # зберегти HTML-звіт
uv run lab research --optuna --trials 20 --notify          # + сповіщення про завершення
uv run lab research --synthetic --bars 1200 --walk-forward # walk-forward на синтетиці
uv run lab research --robot regime --folds 4              # багатовіконний walk-forward (4 фолди)
uv run lab research --robot ema --folds 4                 # те саме для baseline
```

Вивід walk-forward:

```
walk-forward (grid): parameters selected on in-sample only; report out-of-sample. tried=6 selected=... IS=[...] OOS=[...]
in-sample (selection only) fills=117 ending=109331.62479635
out-of-sample (report this) fills=51 ending=100814.86162670
```

Вивід багатовіконного walk-forward (`--folds 4`) — спершу кожен фолд окремо, потім агрегат:

```
multi-window walk-forward (grid): 4 rolling folds, parameters re-selected on each fold's own in-sample window; report the out-of-sample aggregate. windows=[..., ...]
fold 0 OOS=[2025-11-22T13:59:59.999000+00:00, 2026-02-04T17:59:59.999000+00:00) fills=163 return=6.01% buy_hold=-17.49% selected=...
fold 1 OOS=[2026-02-04T17:59:59.999000+00:00, 2026-04-19T19:59:59.999000+00:00) fills=69 return=-1.13% buy_hold=3.81% selected=...
fold 2 OOS=[2026-04-19T19:59:59.999000+00:00, 2026-07-02T17:59:59.999000+00:00) fills=53 return=-6.23% buy_hold=-29.33% selected=...
fold 3 OOS=[2026-07-02T17:59:59.999000+00:00, 2026-09-14T08:59:59.999001+00:00) fills=56 return=3.65% buy_hold=53.00% selected=...
out-of-sample aggregate profitable=2/4 mean=0.58% median=1.26% worst=-6.23% best=6.01%
baseline buy&hold mean=2.50% oos_fills=341
folds=4 profitable=2/4 mean_oos=0.58% median_oos=1.26% worst=-6.23% best=6.01% mean_buy_hold=2.50% (does not beat buy&hold) oos_fills=341
```

Межі вікон друкуються повними ISO-мітками, а не датами: на внутрішньоденних барах OOS-блок може
тривати години, і дата без часу показала б той самий день для всіх фолдів.

Після рядка `baseline buy&hold ...` друкується ще рядок breakeven-cost по фолдах
(лог вище — з прогону до цього оновлення, тому його не містить). Реальний вигляд із
`lab research --robot ema --folds 3` (16.09.2026):

```
breakeven_cost mean_bps=-18.91 folds_measured=3/3
```

Середнє рахується лише по фолдах, де були філи: фолд без торгів не має breakeven, і
підставляти туди нуль означало б усереднювати вимір із не-виміром.

Вивід повного прогону / синтетики (`lab research --robot regime --synthetic --bars 3000 --full-sample`,
прогін 16.09.2026 — числа залежать від `--bars` і сіда):

```
fills=89 positions=35 ending=972891.27247309
fees_paid=49393.76524691 max_dd=0.03451770006438345845057962636 turnover=49920159.25631 sharpe_like=0.01818787608975104788522822970
cost traded_notional=98787530.4936200021675456 paid_cost_bps=5.00 breakeven_cost_bps=93.36
regime synthetic backtest with fees (maker=0.0002 taker=0.0005), 50ms latency, 25% one-tick slippage
```

Синтетичний шлях (`--synthetic`) не друкує рядка-заголовка — він зʼявляється лише на
катальному `--full-sample` (`full-sample catalog run (in-sample only; not an out-of-sample report)`).

Рядок `cost ...` — це [breakeven-cost](06-ryzyk-metryky.md#7-метрики-звіту-domainmetricspy):
`paid_cost_bps` — скільки комісії сплачено за одиницю двобічного обороту
(`traded_notional` = усі філи, і входи, і виходи), `breakeven_cost_bps` — максимальна стала
комісія, за якої PnL цього прогону дорівнював би нулю. Приклад вище — синтетика, тобто артефакт
random walk, а не результат; на реальному каталозі breakeven зазвичай **нижчий** за сплачену
ставку (наприклад `--robot ema --full-sample`: `paid_cost_bps=5.00 breakeven_cost_bps=-46.40`).
Для `--folds N≥2` друкується `breakeven_cost mean_bps=... folds_measured=k/N` — середнє лише по
фолдах, де філи взагалі були.

Помилки (усі → код виходу 1):

| Повідомлення | Причина |
|--------------|---------|
| `bar timestamps must be strictly increasing` | Дублікати в каталозі (повторний ingest) → див. [11](11-troubleshooting-faq.md#bar-timestamps-must-be-strictly-increasing) |
| `no bars in catalog ... Run 'lab ingest' first.` | Порожній каталог або вікно/слайс поза даними |
| `no bars in catalog ... in the requested window` | Вікно поза межами завантаженої історії |
| `bar_count must be >= 150 so indicators can warm up` | Замало барів (regime 150, pairs 200, решта 50) |
| `walk-forward dates require --is-start --is-end --oos-start --oos-end` | Задано не всі чотири дати |
| `in-sample must not overlap out-of-sample` | IS заходить у OOS |
| `multi-window runs derive their own windows; drop --is-start/--oos-start` | Явні дати разом із `--folds N >= 2` — багатовіконний прогін будує вікна сам |
| `<N> bars cannot fill <F> folds at in_sample_fraction=... with embargo_bars=...` | Замало барів на таку кількість фолдів → менше `--folds`, менший `--is-fraction` або довша історія |
| `unknown stress slice 'xxx'; use one of: covid2020, ftx2022, etf2024` | Друкарська помилка в `--slice` |
| `unsupported instrument_id: XXX` | Інструмент не в списку симуляції |
| `unsupported bar interval 'xx'` | `BAR_INTERVAL` не з набору `1m/5m/15m/1h/4h/1d` |
| `Live trading is disabled...` | `TRADING_MODE=live` |

---

## `lab paper`

```
usage: lab paper [-h] [--bars BARS] [--robot {regime,ema}]
```

| Прапорець | Типово | Опис |
|-----------|--------|------|
| `--bars` | `500` | Кількість синтетичних барів |
| `--robot` | `regime` | Лише `regime` або `ema` |

Що робить: проганяє синтетичні бари через вибраний робот і **записує** в лог ордери,
які були б надіслані. Жодного рушія, жодного виконання, жодного оновлення капіталу,
жодного стану позиції (тому може записати кілька `buy` підряд).

```bash
uv run lab paper --bars 500
uv run lab paper --robot ema --bars 200
```

```
paper_orders=289 (no exchange submission)
2024-01-01T00:49:00+00:00 ETH/USDT.SIM buy qty=13.045 reason=donchian breakout long
...
```

Друкує перші 10 ордерів; повний список — в об'єкті `PaperTradingLogger.orders`.

---

## `lab scan`

```
usage: lab scan [-h] [--triangular]
```

| Прапорець | Опис |
|-----------|------|
| `--triangular` | Шукає цикли від'ємної ваги серед курсів-зразків |

Без прапорця — помилка `Specify --triangular` (код 1).

```bash
uv run lab scan --triangular
triangular_opportunities=0
```

Курси зараз зашиті в `cli.py` (`USDT/BTC = 0.000015`, `BTC/ETH = 15`, `ETH/USDT = 3500`)
і дають нуль можливостей — це демонстрація, а не реальний сканер.
Для власних курсів використовуйте `scan_triangular_opportunities()`
(див. [09 §7](09-mft-moduli-pryklady.md#7-трикутний-арбітраж-зі-своїми-курсами)).

---

## `lab propose`

```
usage: lab propose [-h] [--prompt PROMPT] [--count COUNT] [--as-of AS_OF]
                   [--model MODEL] [--base-url BASE_URL] [--output-dir OUTPUT_DIR]
                   [--slug SLUG] [--dry-run] [--journal]
```

**Офлайн-контур дослідження.** Питає велику мовну модель про гіпотези альф і записує
відповідь як артефакт для рев'ю. Команда **не торгує, не читає ринкові дані й не
викликається з гарячого шляху** — жодна стратегія не бачить LLM.

| Прапорець | Типово | Опис |
|-----------|--------|------|
| `--prompt` | `01-generate-alphas.md` | Файл промпту або гола назва з `LLM_PROMPTS_DIR` |
| `--count N` | `5` | Скільки гіпотез просити |
| `--as-of YYYY-MM-DD` | сьогодні | Дата відсічення знань, яку бачить модель (захист від temporal leakage) |
| `--model` | `LLM_MODEL` | Ідентифікатор моделі |
| `--base-url` | `LLM_BASE_URL` | Будь-який OpenAI-сумісний ендпоінт, зокрема локальний сервер ваг |
| `--output-dir` | `LLM_HYPOTHESES_DIR` | Тека артефактів |
| `--slug` | авто | Перевизначити ім'я файлу артефакта |
| `--dry-run` | вимкнено | Надрукувати готовий промпт; **мережі не торкається, ключ не потрібен** |
| `--journal` | вимкнено | Дописати рядок `⏳ pending` у журнал дослідження |

```bash
uv run lab propose --dry-run                      # що саме піде в модель
uv run lab propose --count 5 --as-of 2026-09-15   # потрібен LLM_API_KEY у .env
uv run lab propose --base-url http://127.0.0.1:11434/v1 --model qwen2.5:14b
```

Без `LLM_API_KEY` команда **падає закрито** (код 1) і нічого не вигадує замість моделі.
Артефакт із provenance (модель, хеш промпту, as-of, сира відповідь, блок `review`)
лягає в `research/hypotheses/`; повторний виклик не перезаписує попередній файл.
Деталі — [14](14-llm-model-u-torhivli.md) і [research/README.md](../research/README.md).

---

## `lab live`

```
usage: lab live [-h]
```

Завжди завершується помилкою:

```
$ uv run lab live
Live trading is disabled. This lab only runs research backtests.
$ echo $?
1
```

Це не «ще не налаштовано», а **свідомий запобіжник**: у коді немає жодного адаптера,
який може надіслати ордер на біржу. Прапорець `LIVE_ENABLED=true` у `.env` нічого не змінює.

---

## Додаткові інструменти дослідника

### `--tearsheet PATH` — інтерактивний HTML-звіт

```bash
uv run lab research --tearsheet reports/tearsheet.html
uv run lab research --synthetic --bars 800 --tearsheet reports/synthetic.html
```

Створює HTML-тиршит (крива капіталу, просадки, угоди) і друкує `tearsheet_saved=<шлях>`.
Потрібен extra `visualization`. Якщо `plotly` немає — прогін не падає, лише попередження в лог.
У walk-forward зберігається тиршит **out-of-sample** прогону. У багатовіконному прогоні
(`--folds N >= 2`) зберігається тиршит **останнього** фолда.

### `--journal` — журнал дослідження

```bash
uv run lab research --robot regime --folds 4 --journal
uv run lab propose --count 5 --journal
```

Дописує один рядок у `research/journal.md` (людська таблиця) і один JSON-рядок у
`research/journal.jsonl` (машинний лог). Скрипт **лише дописує**: існуючі рядки він не
переписує, тому рішення, яке ти вписав руками, переживе наступний прогін.

У колонку `OOS` ніколи не потрапляє in-sample число: для прогону без OOS-спліту там
`n/a`, а сама цифра йде в колонку «Причина» з поміткою `IS return ... (not an OOS number)`.

Типово вимкнено. Щоб увімкнути для всіх прогонів — `JOURNAL_ENABLED=true` у `.env`.
Якщо маркери `journal:rows:start/end` у файлі зникли, команда завершується кодом 1
(краще явна помилка, ніж рядок, дописаний невідомо куди).

### `--optuna [--trials N]` — байєсівська оптимізація параметрів

```bash
uv run lab research --optuna --trials 30
```

Замість сітки (`tried=6`) працює Optuna TPE з кількістю спроб `--trials` (типово 20).
У рядку звіту видно `walk-forward (optuna):`. Потрібен extra `research` (пакет `optuna`);
без нього — помилка `optuna is not installed; run: uv sync --extra research`.

⚠️ Більше спроб = вищий ризик перенавчання. Порівнюйте результат зі звичайною сіткою.

### `--notify` — сповіщення про завершення

```dotenv
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
ALERT_WEBHOOK_URL=https://...
```

```bash
uv run lab research --optuna --trials 20 --notify
```

Потрібен extra `alerts` (`httpx`). Збій надсилання не впливає на код виходу (завжди 0) —
у лог іде попередження. Без заданих змінних працює «порожній» нотифікатор.

### Walk-forward на синтетиці

```bash
uv run lab research --synthetic --bars 1200 --walk-forward
```

Раніше `--synthetic` завжди давав повний прогін; тепер у комбінації з `--walk-forward`
(або `--optuna`) виконується справжній walk-forward на 1-хвилинних синтетичних барах.
Реальний вивід для 1200 барів:

```
walk-forward (grid): ... tried=6 selected=donchian=20 bb_k=2.5 ...
in-sample (selection only) fills=17 ending=272625.25800441
out-of-sample (report this) fills=2 ending=99900.20080881
```

Зверніть увагу на розрив: IS +172%, OOS −0.1%. Це не стратегія, це демонстрація того,
як виглядає перенавчання на синтетиці.

### `--folds N` — багатовіконний (ковзний) walk-forward

```bash
uv run lab research --robot regime --folds 4
uv run lab research --robot ema --folds 4
uv run lab research --synthetic --bars 5000 --folds 2
```

`--folds 1` (типово) — це стара поведінка: **одна** нарізка (перші `--is-fraction` історії на підбір,
решта на звіт). Одна нарізка дає одне число з однієї ділянки історії, тому не відрізняє перевагу
від випадковості. `N >= 2` запускає окремий walk-forward на кожен фолд і друкує
**агрегат out-of-sample**: скільки фолдів у плюсі, середнє/медіану, найгірший і найкращий фолд,
сумарну кількість філів і порівняння з buy&hold.

Як розкладаються вікна:

- перший in-sample блок займає `--is-fraction` історії (типово 70%), далі розрив `--embargo-bars`,
  далі `N` однакових послідовних out-of-sample блоків, які заповнюють залишок;
- фолд *i* підбирає параметри на in-sample-вікні, що **зсувається на один OOS-блок уперед**, і
  звітує на блоці, який іде за ним — тобто це прогноз, а не повторне читання тих самих даних;
- останній фолд забирає остачу від ділення націло, тому фінальне вікно завжди доходить до
  найсвіжішого бару;
- сума OOS-блоків усіх фолдів дорівнює тому самому OOS-вікну, яке дала б одна нарізка — просто
  порізаному на частини.

Що ще варто знати:

- працює для каталогу й для `--synthetic`, для однолегових роботів (`regime`, `ema`) і для `pairs`;
- з `--tearsheet` зберігається тиршит **лише останнього** фолда, а не зведений;
- ціна: `--robot regime --folds 4` на каталозі з ~23.7 тис. годинних барів — **≈86 с**
  (4 фолди × 6 кандидатів сітки на in-sample-вікнах по ~16.6 тис. барів). Звичайний єдиний спліт —
  кілька секунд, тому для швидких ітерацій лишайте `--folds 1`;
- явні дати (`--is-start/--is-end/--oos-start/--oos-end`) з `--folds N >= 2` дають помилку
  `multi-window runs derive their own windows` — багатовіконний прогін будує вікна сам;
- реальний результат і висновки — [05 §4](05-roboty.md#4-багатовіконний-walk-forward-чи-була-перевага-взагалі).

### `--pbo` — аудит перенавчання

```bash
uv run lab research --robot regime --pbo               # 8 блоків (типово)
uv run lab research --robot regime --pbo --pbo-blocks 4
uv run lab research --robot regime --pbo --optuna --trials 30
uv run lab research --robot regime --synthetic --bars 2000 --pbo --pbo-blocks 4
```

Замість одного walk-forward цей режим рахує **ймовірність перенавчання бектесту**
(Probability of Backtest Overfitting) методом CSCV:

1. історія ріжеться на `--pbo-blocks N` однакових **послідовних** блоків;
2. кожна конфігурація сітки проганяється на **кожному** блоці окремо — виходить матриця
   `блоки × конфігурації`;
3. для кожного з `C(N, N/2)` симетричних розбиттів одна половина блоків грає in-sample
   (обираємо найкращу конфігурацію), друга — out-of-sample (дивимось, яке місце вона посіла);
4. **PBO** — частка розбиттів, де переможець in-sample упав у **нижню половину** out-of-sample.

Як читати результат:

| PBO | Що це означає |
|-----|----------------|
| ≈ 0 | ранжування конфігурацій стабільне: вибір на одній частині історії відтворюється на іншій |
| ≈ 0.5 | переможець in-sample — підкидання монети, вибір нічого не значить |
| > 0.5 | вибір **шкодить**: улюблена конфігурація систематично провалюється на нових даних |
| `undefined` | у сітці менше 2 конфігурацій, або всі розбиття «нічийні» — числа немає, і це чесна відповідь |

Приклад виводу (ETH/USDT 1h, 2024-01-01…2026-09-14, 8 блоків × 6 конфігурацій):

```
blocks=8 configurations=6
  [0] fast_ema=10 slow_ema=20 donchian=10 bb_k=2 ... :: -6.43% -8.06% -5.95% -0.30% -2.02% -2.98% 5.12% -4.62%
  [1] fast_ema=10 slow_ema=20 donchian=10 bb_k=2.5 ... :: -4.97% 3.65% -2.18% 3.89% -2.84% 1.08% 3.25% 2.10%
  ...
PBO=0.086 over 70 splits x 6 configurations on 8 blocks (selection generalises)
DSR=0.012535716455923718 (observations=8 trials=6 sharpe=0.1469381132927457961447239220 threshold=1.025116290164639145467374220)
```

(Обидва рядки — реальний вивід: перший збігається з прогоном `--pbo-blocks 8`, другий узятий
з того самого прогону; PBO і DSR друкуються разом, з однієї матриці.)

Другий рядок — **DSR** (дефльований коефіцієнт Шарпа, Bailey & López de Prado 2014):
ймовірність, що Sharpe переможця сітки перевищив би очікуваний максимум `trials`
прогонів із нульовою навичкою, з поправкою на асиметрію та ексцес розподілу. Він рахується
на **тій самій** матриці, що й PBO: спостереження — блоки доходностей переможця, спроби —
конфігурації сітки. Замало блоків (< 8), одна конфігурація або нульова дисперсія — рядок
каже `DSR undefined: <причина>`, а не вигадує число. Деталі й межі застосовності —
[17 §2](17-ml-ansambli-vidpovidnist.md) і `specs/components/deflated-sharpe.yaml`.

Що ще варто знати:

- **ціна:** `блоки × конфігурацій` бектестів. Для `regime` це `8 × 6 = 48` прогонів на 8-х
  частинах історії (≈3 хв на каталозі з ~23.7 тис. годинних барів);
- **кожен блок симулюється з нуля**, тому втрачає власні бари на розгін індикаторів;
  якщо блок коротший за мінімум робота (`150` барів для `regime`, `200` для `pairs`,
  `80` для `formulaic_lgbm`) — помилка з підказкою зменшити `--pbo-blocks`;
- **низький PBO ≠ прибутковість.** Він каже лише, що *порядок* конфігурацій відтворюється.
  Стратегія, яка втрачає гроші на всіх блоках, дасть низький PBO і залишиться збитковою;
- **DSR ≠ прибутковість** і не замінює порівняння з buy&hold: він каже лише, чи не є сам
  Sharpe наслідком того, що конфігурацій перебрали багато;
- працює і на каталозі, і на `--synthetic`, для однолегових роботів і для `pairs`;
- сумісний з `--notify` (надсилає `summary_line()`), несумісний з `--tearsheet` (тиршит не
  генерується — режим не має єдиного «того самого» прогону).

## Змінні середовища: швидка шпаргалка

Повний опис — у [02-vstanovlennya.md](02-vstanovlennya.md#3-усі-змінні-налаштування).
Найуживаніші:

```dotenv
TRADING_MODE=research        # research | paper | live (live завжди блокується)
CATALOG_PATH=catalog
BAR_INTERVAL=1h              # 1m | 5m | 15m | 1h | 4h | 1d
INSTRUMENT_ID=ETH/USDT.SIM
BINANCE_SYMBOLS=["ETHUSDT","BTCUSDT"]
STARTING_EQUITY=100000
RISK_PER_TRADE=0.005
STOP_PCT=0.01
MAX_DAILY_LOSS=0.02
MAX_DRAWDOWN=0.06
KELLY_FRACTION=0.25
MAX_VAR_99=0.05
ROBOT=regime
EMBARGO_BARS=10
MAKER_FEE=0.001
TAKER_FEE=0.001
USE_BAR_VPIN=false

# Офлайн-контур дослідження (lab propose) і журнал
LLM_API_KEY=                 # порожньо = цикл вимкнено (fail closed)
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
LLM_PROMPTS_DIR=research/prompts
LLM_HYPOTHESES_DIR=research/hypotheses
JOURNAL_ENABLED=false
JOURNAL_PATH=research/journal.md
JOURNAL_JSONL_PATH=research/journal.jsonl
```

Пріоритет джерел: **змінні оболонки → `.env` → значення в коді**.
Перевірити, що реально бачить програма:

```bash
uv run python -c "
from nautilus_lab.infrastructure.settings import Settings
s = Settings()
print('mode:', s.trading_mode, 'robot:', s.robot, 'interval:', s.bar_interval)
print('fees:', s.fee_schedule(), 'risk:', s.risk_limits().risk_per_trade)
"
```

---

## Типові послідовності команд

**Перше знайомство (5 хвилин, без мережі):**

```bash
uv run lab research --synthetic --bars 3000
uv run lab paper --bars 500
uv run lab live            # переконатися, що жива торгівля заблокована
```

**Повний цикл на реальних даних:**

```bash
rm -rf catalog
uv run lab ingest --start 2025-01-01 --symbols ETHUSDT,BTCUSDT
uv run lab research --robot ema          # baseline
uv run lab research                      # основний прогін
uv run lab research --robot pairs
uv run lab research --robot regime --folds 4   # чи витримує результат нарізку на 4 вікна
```

**Стрес-тести на довгій історії:**

```bash
uv run lab ingest --start 2019-01-01 --end 2025-01-01 --symbols ETHUSDT --catalog catalog_long
uv run lab research --slice covid2020 --catalog catalog_long
uv run lab research --slice ftx2022   --catalog catalog_long
uv run lab research --slice etf2024   --catalog catalog_long
```

**Перевірка якості після зміни коду:**

```bash
uv run pytest
uv run ruff check --fix && uv run ruff format
uv run mypy src tests
uv run lab research --synthetic --bars 3000
```

## Куди йти далі

- Щось не працює → [11-troubleshooting-faq.md](11-troubleshooting-faq.md)
- Що означає вивід → [04-tsykl-doslidzhennya.md](04-tsykl-doslidzhennya.md#крок-5-як-читати-звіт)
