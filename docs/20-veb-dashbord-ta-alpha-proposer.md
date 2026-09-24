# Документація: Веб-дашборд Nautilus Lab та Alpha Proposer (Offline LLM)

Цей документ описує роботу інтерактивного веб-дашборду **Nautilus Lab** та містить детальні інструкції щодо використання модуля генерації торгових гіпотез **Alpha Proposer (offline LLM)**.

---

## 1. Загальна архітектура та призначення дашборду

Веб-інтерфейс **Nautilus Lab** розроблений на стеку **React + TypeScript + Vite** (знаходиться у теці `frontend/`). Він слугує візуальним пультом керування для дослідницької платформи та взаємодіє з бекендом **FastAPI** (`src/nautilus_lab/api/app.py`).

Бекенд запускає ті самі сценарії використання (use cases), перевірки ризиків та рушій NautilusTrader, що й консольний інтерфейс `lab`.

```
┌────────────────────────────────────────────────────────┐
│                   React + Vite UI                      │
│            (frontend: http://localhost:5173)           │
└───────────────────────────┬────────────────────────────┘
                            │ HTTP / REST + WebSocket (?token=)
┌───────────────────────────▼────────────────────────────┐
│                    FastAPI Backend                     │
│               (API: http://localhost:8000)             │
└──────┬────────────────────┬────────────────────┬───────┘
       │                    │                    │
┌──────▼──────┐      ┌──────▼──────┐      ┌──────▼──────┐
│  Parquet    │      │  Nautilus   │      │ Offline LLM │
│   Catalog   │      │  Backtest   │      │  Proposer   │
│  (Data/IO)  │      │   Engine    │      │ (Hypothesis)│
└─────────────┘      └─────────────┘      └─────────────┘
```

### Золоті правила безпеки та дослідницької дисципліни в UI

1. **Fail-closed за замовчуванням**:
   - У системі **не існує адаптера виконання угод на реальній біржі**.
   - Режим `lab live` завжди повертає код помилки `1` (`Live trading is disabled. This lab only runs research backtests.`).
   - У лівому сайдбарі дашборду постійно активний статус безпеки: `Safety: fail-closed`.
2. **In-sample ніколи не є результатом**:
   - Параметри, підібрані на вибірці In-Sample (IS), мають статус `selection only`.
   - Результатом визнається виключно чистий Out-of-Sample (OOS).
3. **Порівняння з Buy & Hold на тому ж вікні**:
   - Кожен розрахований прогін вимагає порівняння з базовим утриманням активу на тому ж OOS часовому відрізку.
4. **Ізоляція великих мовних моделей (LLM)**:
   - **Жодного виклику LLM на гарячому шляху бектесту чи симуляції.**
   - Моделі застосовуються виключно в **офлайн-контурі** (Alpha Proposer) для первинного формулювання гіпотез, які далі аналізуються людиною-дослідником.

---

## 2. Як запустити дашборд

Для роботи потрібні два термінали: один для API сервера, другий для веб-клієнта.

### Крок 1: Запуск API бекенду

API потребує extra `api` (`fastapi`, `uvicorn`, `python-dotenv`, `pyyaml`, `websockets`).
Без нього `uvicorn` у `.venv` просто не існує:

```bash
uv sync --extra dev --extra api
```

З кореневої теки проєкту:

```bash
.venv/bin/uvicorn nautilus_lab.api.app:app --port 8000
```

Сервер підніметься на `http://localhost:8000`. Перевірити готовність можна запитом
`http://localhost:8000/api/status` або `GET /` → `{"status": "ok", "message": "Nautilus Lab API is running"}`.
Автозгенеровані сторінки FastAPI (`/docs`, `/redoc`, `/openapi.json`) доступні там само.

### Крок 2: Запуск фронтенду

У другому терміналі:

```bash
cd frontend
npm install    # тільки при першому запуску або оновленні залежностей
npm run dev
```

Відкрийте браузер за адресою: **`http://localhost:5173`**.

> [!TIP]
> Якщо `npm run dev` зупиняється з помилкою `ENOSPC: System limit for number of file watchers reached` (обмеження inotify файлових спостерігачів у Linux), запустіть оптимізовану збірку без спостерігача:
> ```bash
> cd frontend && npm run build && npx vite preview
> ```
> `vite preview` слухає `:4173` — цей origin теж у типовому списку дозволених.

### Крок 3: Як фронтенд знаходить API і як API його захищає

Клієнт читає дві змінні **на етапі збірки** (`frontend/src/config.ts`; значення задаються у
`frontend/.env` за зразком `frontend/.env.example`):

| Змінна | Типово | Що робить |
|---|---|---|
| `VITE_API_URL` | порожньо → `http://localhost:8000` | База всіх запитів. `VITE_API_URL=same-origin` — бандл звертається до хоста, з якого завантажений: деплой за одним реверс-проксі (`deploy/Caddyfile`, `docs/26-deploy-vps.md`), а WebSocket переходить з `https` на `wss`. |
| `VITE_API_TOKEN` | порожньо | Значення для заголовка `X-Lab-Token` у кожному виклику `/api`; для WebSocket — параметр `?token=` (`frontend/src/lib/apiAuth.ts`). |

Бекенд має три незалежні шлюзи (`src/nautilus_lab/api/security.py`). Усі три читаються
**один раз при імпорті** — зміна змінної вимагає рестарту API:

| Шлюз | Змінна | Поведінка |
|---|---|---|
| Origin | `API_ALLOWED_ORIGINS` | Порожньо → типові `http://localhost:5173`, `http://127.0.0.1:5173`, `http://localhost:4173`, `http://127.0.0.1:4173`, `http://localhost:8000`, `http://127.0.0.1:8000`. Запит, що несе заголовок `Origin`, мусить походити з цього переліку, інакше `403`. Запити без `Origin` (curl, скрипти, тести) не браузерна атака — вони проходять. |
| Токен | `API_TOKEN` | Порожньо → вимкнено. Інакше кожен виклик під `/api` вимагає заголовок `X-Lab-Token` (порівняння через `hmac.compare_digest`); для WebSocket — `?token=`, бо заголовок у handshake не поставити. Статичні монти `/static_reports` і `/static_hypotheses` звільнені від токена: дашборд вбудовує тиршити в `iframe`, який заголовка надіслати не може. |
| Роль | `LAB_ROLE` | `full` (типово) — усе. `paper` — сервер лише для живого paper-терміналу: для рольового шлюзу читання (`GET`/`HEAD`/`OPTIONS`) лишається відкритим (токен, якщо заданий, усе одно потрібен), дозволені тільки `POST /api/paper/live/{start,stop,close-position,update-stops}`, `POST /api/paper/sessions` і дії над сесією `/api/paper/sessions/<id або name>/{stop,pause,resume,close-position,update-stops}`; решта записів (research, ingest, ML, `PUT /api/settings`, `/api/propose`) — `403` з поясненням. Невідоме значення → сервер не стартує (fail closed, а не «тихо full»). |

---

## 3. Огляд розділів дашборду

Вкладки сайдбара в порядку (`frontend/src/App.tsx`): `home` (Command Center), `research`
(Research & Backtest), `catalog` (Parquet Catalog), `strategies` (Strategy Specs), `ml`
(ML Pipeline), `journal` (Experiment Journal), `paper` (Trading Terminal), `scan`
(Arb Scanner), `alpha` (Alpha Ideas), `settings` (Settings). Крім вкладок, є палітра
команд (`⌘K` / `Ctrl+K`) і модальне вікно «Guide & Docs» (`?`). На сервері з
`LAB_ROLE=paper` UI сам відкривається на вкладці `paper` і показує банер, що research,
ingest, ML і зміна налаштувань тут вимкнені.

### 3.1. Command Center (`/home`)
Центральна панель моніторингу:
- **Running Now**: показує поточні асинхронні задачі (`research`, `ingest`, `ml_train`, `paper`) з таймером тривалості виконання.
- **Latest Research Verdict**: швидкий огляд останнього завершеного бектесту (Out-of-Sample Return, річний Sharpe, максимальна просіка Max DD, комісії, обіг) та чіткий вердикт: `Beats Buy&Hold`, `Underperforms Buy&Hold` чи `Inconclusive`.
- **Recent Experiments**: список останніх запусків із можливістю швидкого переходу до аналізу.
- **Data coverage**: таблиця покриття по кожному інструменту — бари, taker-flow, тіки (aggTrades), L2-глибина, фандинг. Порожня опційна серія означає, що відповідний фільтр працював би на власних значеннях за замовчуванням, тому панель показує `missing` явно.
- **Catalog & Models Overview**: кількість інструментів у каталозі, дата останнього бару (свіжість даних), загальна кількість барів, розмір та перелік збережених навчених моделей ML.

### 3.2. Research & Backtest (`/research`)
Основне робоче місце кількісного дослідника:
- **Вибір стратегії**: випадаючий список будується з `GET /api/strategies`, тобто з **усіх** `specs/strategies/*.yaml` — `regime`, `ema`, `pairs`, `vpin_momentum`, `formulaic_lgbm`, `meta_label`, `adaptive_ema`, `funding`, `ml_obi`, `glft`, `tri_scan`. Специфікація, яку не вдалося розпарсити, не зникає мовчки: її ім'я повертається у `failed_specs` (робота без специфікації виглядала б так само, як та, якої ніколи не було).
- **Джерело даних**: Parquet-каталог або синтетичні бари для smoke-тесту.
- **Walk-Forward Builder**: інтерактивне розбиття історії:
  - частка In-Sample (`is_fraction`, за замовчуванням `0.7`);
  - захисний ембарго-інтервал (`embargo_bars`, за замовчуванням `10`);
  - кількість фолдів (`folds`, при $N \ge 2$ проводиться багатовіконне тестування зі збереженням OOS агрегату).
- **Режим пошуку параметрів**:
  - Grid Search (детермінована сітка);
  - Optuna TPE (байєсівська оптимізація із заданням кількості спроб `--trials`).
- **Спеціальні аудити**:
  - **PBO / CSCV**: розрахунок імовірності перенавчання (Probability of Backtest Overfitting);
  - **Стрес-слайси**: готові історичні зрізи екстремальної волатильності (`covid2020`, `ftx2022`, `etf2024`).
- **Фільтри режиму за потоком** (advanced gates):
  - `Bar-level VPIN` — проксі обсягу бару;
  - `Tick-level VPIN` (`--tick-vpin`) — реальний поділ агресора з aggTrades;
  - `Hawkes intensity` (`--hawkes`) — гейт кластеризованого потоку з тієї ж серії тіків.
  Два останні доступні лише для роботів із `RegimeRouter` (`regime`, `meta_label`, а tick-VPIN також `vpin_momentum`) і лише коли каталог містить серію aggTrades: форма блокує прогін, який бекенд однаково відхилить, бо рушій читає відсутню серію як порожню (фільтр тихо працював би на значеннях за замовчуванням).
- **Інтерактивний графік котирувань**:
  - Бурштинова зона — період відбору параметрів (IS);
  - Зелена зона — тестовий період OOS, на якому фіксується фінальний результат.
- **Панель вердикту (VerdictPanel)**:
  - Розрахунок точки беззбитковості по комісіях (**breakeven fee rate**): чи витримає стратегія реальний taker fee ($0.05\% - 0.1\%$).
  - Таблиця пофолдового розбору (FoldBreakdown) та матриця PBO.
- **Copy CLI**: кнопка копіює еквівалентну команду `lab research`, зібрану лише з прапорців, які реально існують у `interfaces/cli.py`; інструмент передається змінною `INSTRUMENT_ID` (окремого прапорця `--instrument` не існує).

### 3.3. Parquet Catalog (`/catalog`)
Керування локальними історичними даними:
- Перегляд доступних Parquet-каталогів, діапазонів дат (start/end), розміру файлів та кількості барів.
- **Ingest Binance data**: вбудована форма завантаження публічних даних з Binance без біржових ключів. Чотири види ingest, кожен пише власне дерево в тому самому каталозі:
  - `Klines` — `api/v3/klines` → `data/bar/`, підтримує інкрементальне оновлення;
  - `Trades` — `api/v3/aggTrades` → `data/agg_trade/` (одна Parquet-партиція на добу UTC), вмикає tick-level VPIN і Hawkes;
  - `Funding` — `fapi/v1/fundingRate` → `data/funding/`;
  - `Depth` — живий L2-знімок через WebSocket → `data/orderbook/`; не має вікна `start/end`, триває до натискання «Stop ingest» і захоплює один символ за раз.
- **Series beside the bars**: таблиця покриття (кількість рядків, остання доба наявності) для кожної серії та бейдж, чи придатні tick-фільтри.
- Візуальний графік свічок для перевірки відсутності аномалій чи розривів у даних.

### 3.4. Strategy Specs (`/strategies`)
Відображення живих специфікацій стратегій із `specs/strategies/*.yaml`:
- Статус валідації робота (`candidate`, `validated`, `rejected`).
- Прапорець підключення до бектест-адаптера (`wired_in_backtest`).
- Кількість барів прогріву (`minimum_bars`).
- Джерело сітки (`grid_source`) та опис усіх регульованих параметрів.

### 3.5. ML Pipeline (`/ml`)
Контур машинного навчання для факторних альф:
- Навчання моделей **LightGBM** на крипто-барах.
- Використання Purged Cross-Validation для усунення витоку даних через автокореляцію фічей.
- Інвентаризація збережених моделей у каталозі `models/`.

### 3.6. Experiment Journal (`/journal`)
Журнал контролю якості та відтворюваності:
- Канбан-дошка зі стовпчиками `pending`, `accepted`, `rejected`, `rerun`.
- Запис параметрів запуску, умов (gates), кількості угод (fills), OOS метрик та посилань на артефакти.
- Інтегрований блок **Alpha Proposer (offline LLM)** (детально нижче).

### 3.7. Paper-термінал (`/paper`)
Вкладка `paper` (у сайдбарі — «Trading Terminal») має два контури:

- **Пакетний прогін** — `POST /api/paper/run` (лог: `GET /api/paper/log`, скасування: `POST /api/paper/cancel`): симуляція на потоці барів із виведенням списку гіпотетичних ордерів. Робот мусить бути з `PAPER_SUPPORTED_ROBOTS`, інакше `400` з переліком підтриманих.
- **Живий paper-термінал** — `POST /api/paper/sessions`: сесія на закритих барах публічного Binance-WS із розігрівом з каталогу (`WARMUP_BARS = 300`), віртуальним капіталом, SL/TP і тими самими ризик-брейкерами та комісіями з `Settings`, що й дослідницькі прогони. Стан і бари приходять через **WebSocket `/api/paper/live-stream`** (`?session=<id або name>`, без параметра — головна сесія); команди — `POST /api/paper/sessions/{key}/stop|pause|resume|close-position|update-stops`, портфель — `GET /api/paper/portfolio`. Деталі контуру — `docs/24-paper-treydynh.md`.

**Це симуляція, а не торгівля.** Біржових ключів проєкт не потребує (дані — з публічних ендпоінтів), адаптера виконання не існує, жоден ордер на біржу не надсилається. Поле `mode` сесії (`paper` / `live_guarded`, перемикач у терміналі) лише записується у стан сесії й нікуди не маршрутизується — рушій завжди філить у симульований венчур, а «Live Guarded» у UI — текст попередження.

### 3.8. Arb Scanner (`/scan`)
Вкладка `scan` (у сайдбарі — «Arb Scanner», компонент `frontend/src/components/ScanTab.tsx`) викликає `POST /api/scan/triangular`:
- Перебирає трикутні шляхи на **демонстраційній** таблиці курсів (`command_center.scan_triangular_demo`) і повертає `count` / `opportunities` з приміткою `Demo rates only — not live market data.`
- Поточна реалізація завжди дає 0 можливостей — це навмисний каркас, і UI каже це прямо, а не ховає.
- Скан лише читає: жодних ордерів і жодного живого потоку котирувань.

### 3.9. Alpha Ideas (`/alpha`)
Вкладка `alpha` — основне робоче місце Alpha Proposer (компонент `frontend/src/components/AlphaIdeasTab.tsx`):
- Форма запуску (Count, Dry run, Write journal entry, необов'язкова назва/шлях промпту) → `POST /api/propose`.
- Архів артефактів: `GET /api/hypotheses` (список із `research/hypotheses/*.json` із датою, розміром, моделлю, `count_parsed` / `count_flagged`) і `GET /api/hypotheses/{filename}` (повний вміст прогону, зокрема `raw_response` і блок `review`).
- Кнопка «випробувати в Research» передає формулу у вкладку **Research & Backtest** (перемикання стану — `frontend/src/App.tsx`); сам контур LLM цим не викликається.

### 3.10. Settings (`/settings`)
Керування конфігурацією середовища `.env` (`GET /api/settings/schema`, `GET /api/settings`, `PUT /api/settings`):
- Групи полів із `settings_schema.py`: **Trading Mode**, **Risk Limits**, **Robot Defaults**, **Data Catalog**, **Risk Overlays**, **Alerts**, **Research Journal**, **Alpha Ideas / LLM**.
- Маскування: значення, чия назва закінчується на `_KEY`, `_TOKEN`, `_SECRET` або `_URL` (і не містить `PATH`), віддаються як `xx****yy`.
- `PUT` приймає лише відомі ключі (`Unknown setting key: ...` інакше) і нормалізує їх до верхнього регістру перед записом у `.env`.

---

## 4. Перелік API-маршрутів

Нижче — **усі** маршрути з `src/nautilus_lab/api/app.py` (звірено з `grep -n "@app\." src/nautilus_lab/api/app.py`):
47 HTTP-ендпоінтів і один WebSocket (48 маршрутів разом; у `/api/settings` їх два — `GET` і `PUT`).
Усі, крім кореневого `/`, статичних монтів і автозгенерованих `/docs`, `/redoc`,
`/openapi.json`, лежать під префіксом `/api` і проходять три шлюзи з розділу 2.

### 4.1. Стан, дані й довідка

| Метод | Шлях | Що робить |
|---|---|---|
| `GET` | `/` | Heartbeat: `{"status": "ok", "message": "Nautilus Lab API is running"}`. |
| `GET` | `/api/status` | Пульс дашборду. `?catalog_path=` обирає каталог. Віддає стан чотирьох джобів (`research`, `ingest`, `ml_train`, `paper`) з мітками й секундами, перелік роботів (`strategies_available`, `wired_robots`, `tick_vpin_robots`, `hawkes_robots`, `paper_robots`), `stress_slices`, `bar_interval`, `trading_mode`, `lab_role`, `live_safe_mode: FAIL_CLOSED`, `is_live: false`, `live_paper_robots`, `live_paper_persisted`. |
| `GET` | `/api/command-center` | Один пакет для вкладки Command Center: `jobs`, `safety`, `robots`, `catalog_last_date`, `catalog_total_bars`, `data_series`, `recent_experiments`, `models`, `journal`, `last_research`. |
| `GET` | `/api/catalogs` | Перелік доступних Parquet-каталогів і каталог за замовчуванням. |
| `GET` | `/api/catalog` | Опис каталогу (`?catalog_path=`): інструменти, діапазони, розміри, кількість барів. |
| `GET` | `/api/catalog/bars` | Бари для графіка: `instrument_id`, `catalog_path`, `bar_interval`, `start`, `end`, `limit` (типово `500`); помилка читання → `400` з текстом причини. |
| `GET` | `/api/data` | Здоров'я даних (`?catalog_path=`): які з чотирьох серій (бари, aggTrades, фандинг, L2) реально є і докуди сягають. Відсутня серія означає `missing`, а не «фільтр працював на значеннях за замовчуванням». |
| `GET` | `/api/strategies` | Специфікації з `specs/strategies/*.yaml` (`name`, `wired_in_backtest`, `minimum_bars`, `grid_source`, `status`, `params`) плюс `failed_specs`. |
| `GET` | `/api/reports` | Список HTML-тиршитів із `reports/`, найсвіжіші першими. |

### 4.2. Дослідження (walk-forward)

| Метод | Шлях | Що робить |
|---|---|---|
| `POST` | `/api/research` | Запускає бектест окремим процесом. Тіло (`ResearchRunRequest`): `robot`, `source`, `bars`, `folds`, `is_fraction`, `embargo_bars`, `use_optuna`, `optuna_trials`, `pbo`, `pbo_blocks`, `bar_vpin`, `tick_vpin`, `hawkes`, `stress_slice`, `generate_tearsheet`, `journal`, `notify`, `full_sample`, `catalog_path`, `instrument_id`, `bar_interval`, `is_start`/`is_end`, `oos_start`/`oos_end`, `param_overrides`. Повторний запуск при активній джобі → `{"status": "error"}`. |
| `POST` | `/api/research/cancel` | Зупиняє поточний прогін; якщо нічого не біжить — `{"status": "idle"}`. |
| `GET` | `/api/research/log` | Хвіст логу прогону плюс розібраний звіт і `is_running`. |
| `GET` | `/api/research/history` | Останні прогони з `reports/` (`?limit=`, типово `20`). |
| `GET` | `/api/research/history/{history_id}` | Один запис історії; немає → `404`. |

### 4.3. Каталог та ingest

| Метод | Шлях | Що робить |
|---|---|---|
| `POST` | `/api/catalog/ingest` | Завантаження публічних Binance-даних. Тіло (`IngestRunRequest`): `symbols`, `start`, `end`, `catalog`, `incremental`, `series` (`klines` \| `trades` \| `funding` \| `depth`). |
| `POST` | `/api/catalog/ingest/cancel` | Зупиняє ingest. |
| `GET` | `/api/catalog/ingest/log` | Лог ingest і стан джоби. |

### 4.4. Журнал і налаштування

| Метод | Шлях | Що робить |
|---|---|---|
| `GET` | `/api/journal` | Записи `research/journal.jsonl` (найновіші першими) з індексом для PATCH. |
| `PATCH` | `/api/journal/{index}` | Рішення по запису: `decision` ∈ `pending`, `accepted`, `rejected`, `rerun`. |
| `GET` | `/api/settings/schema` | Схема груп і полів для форми Settings. |
| `GET` | `/api/settings` | Поточні значення з `.env` із замаскованими секретами. |
| `PUT` | `/api/settings` | Записує зміни в `.env`; невідомий ключ → `400`. |

### 4.5. ML

| Метод | Шлях | Що робить |
|---|---|---|
| `GET` | `/api/ml/models` | Інвентар навчених моделей із `models/`. |
| `POST` | `/api/ml/train` | Навчання окремим процесом. Тіло (`MLTrainRequest`): `model_type` (`formulaic` \| `meta_label` \| `obi`), `catalog_path`, `instrument_id`, `bar_interval`, `output_path`, `folds`, `embargo`, `horizon`, `profit_multiple`, `stop_multiple`, `vol_window`, `start`, `end`, `threshold`. |
| `POST` | `/api/ml/train/cancel` | Зупиняє навчання. |
| `GET` | `/api/ml/train/log` | Лог навчання, `is_running`, OOF-метрики, вікно тренування. |

### 4.6. Paper

| Метод | Шлях | Що робить |
|---|---|---|
| `POST` | `/api/paper/run` | Пакетна paper-симуляція (`robot`, `bars`, `source`). Робот поза `PAPER_SUPPORTED_ROBOTS` → `400`. |
| `POST` | `/api/paper/cancel` | Зупиняє пакетний прогін. |
| `GET` | `/api/paper/log` | Лог і підсумок пакетного прогону, разом із `disclaimer`. |
| `GET` | `/api/paper/sessions` | Усі живі paper-сесії (`summaries`) і портфель. |
| `POST` | `/api/paper/sessions` | Старт живої сесії. Тіло (`PaperLiveStartRequest`): `symbol`, `interval`, `robot`, `starting_equity`, `risk_per_trade`, `stop_pct`, `take_profit_multiple`, `mode`, `auto_trade`, `name`, `notes`. Невідомий робот або некоректна конфігурація → `400`. |
| `GET` | `/api/paper/portfolio` | Зведення по всіх сесіях. |
| `GET` | `/api/paper/sessions/{key}` | Стан однієї сесії за `id` або `name`; немає → `404`. |
| `POST` | `/api/paper/sessions/{key}/stop` | Остаточно зупиняє сесію. |
| `POST` | `/api/paper/sessions/{key}/pause` | Пауза входів (виходи не гейтяться). |
| `POST` | `/api/paper/sessions/{key}/resume` | Знімає паузу входів. |
| `POST` | `/api/paper/sessions/{key}/close-position` | Ручне закриття позиції. |
| `POST` | `/api/paper/sessions/{key}/update-stops` | Правка SL/TP (`stop_loss`, `take_profit`). |
| `GET` | `/api/paper/live/state` | Стан **головної** сесії (або idle-стан, якщо сесій немає). |
| `POST` | `/api/paper/live/start` | Старт сесії тим самим тілом, що `/api/paper/sessions`. |
| `POST` | `/api/paper/live/stop` | Стоп головної сесії; якщо її немає → `400`. |
| `POST` | `/api/paper/live/close-position` | Закриття позиції головної сесії. |
| `POST` | `/api/paper/live/update-stops` | SL/TP головної сесії. |

### 4.7. Alpha Proposer, скан, WebSocket і статика

| Метод | Шлях | Що робить |
|---|---|---|
| `POST` | `/api/propose` | Один виклик офлайн-контуру LLM. Тіло (`ProposeRequest`): `count`, `dry_run`, `prompt`, `as_of`, `model`, `base_url`, `output_dir`, `slug`, `journal`. `dry_run=true` → рендер промпту без мережі; без `LLM_API_KEY` → `400`; помилка ендпоінта → `502`. |
| `GET` | `/api/hypotheses` | Список артефактів із `research/hypotheses/` (файл, дата, розмір, `url`, `model`, `as_of`, `count_parsed`, `count_flagged`, `review_status`). |
| `GET` | `/api/hypotheses/{filename}` | Повний вміст артефакту. `..`, `/` чи `\` у назві → `400`, відсутній файл → `404`, битий JSON → `500`. |
| `POST` | `/api/scan/triangular` | Демонстраційний трикутний скан на статичній таблиці курсів (`Demo rates only — not live market data.`). Ордерів не виставляє. |
| `WS` | `/api/paper/live-stream` | Стан і бари обраної сесії в одному з'єднанні: `?session=<id або name>` обирає сесію, без параметра — головну. Перше повідомлення `{"type": "INIT_STATE", "data": ...}`, далі сервер відповідає `pong` на `ping` від клієнта. **Автентифікація інакша, ніж у HTTP:** handshake не несе заголовків і CORS на нього не діє, тому той самий шлюз читає токен із `?token=`, а `Origin` — із самого handshake. Відмова → закриття з кодом `1008` і причиною. |
| статика | `/static_reports`, `/static_hypotheses` | Монти `reports/` і `research/hypotheses/` для `iframe` і посилань. Звільнені від токена, бо не змінюють стан. |

---

## 5. Повний посібник: Alpha Proposer (Offline LLM)

Є дві точки входу, і обидві кличуть один і той самий `POST /api/propose`:

- **вкладка Alpha Ideas** (`frontend/src/components/AlphaIdeasTab.tsx`) — повне робоче місце: форма запуску, архів артефактів, перегляд прогону й передача формули в Research (розділ 3.9);
- **компактний блок угорі Experiment Journal** (`frontend/src/components/ProposeAlpha.tsx`) — та сама форма без архіву.

Він відповідає за формулювання гіпотез щодо напрямку руху ціни за допомогою мовної моделі. Гіпотези записуються у форматі строгого математичного DSL факторів і не допускають довільних текстових рекомендацій чи підглядання в майбутнє.

```
┌─────────────────────────────────────────────────────────────┐
│                 Alpha Proposer (frontend)                   │
│   [Count: 5]  [x] Dry run  [ ] Write journal  [Preview]     │
└──────────────────────────────┬──────────────────────────────┘
                               │ POST /api/propose
┌──────────────────────────────▼──────────────────────────────┐
│                API: execute_propose()                       │
│    nautilus_lab/application/run_alpha_proposal.py           │
└──────────────┬──────────────────────────────┬───────────────┘
               │ dry_run = True               │ dry_run = False
┌──────────────▼──────────────┐┌──────────────▼──────────────┐
│    Локальний рендеринг      ││      Виклик LLM клієнта     │
│   Шаблон: 01-generate-      ││  (OpenAICompatibleChatClient│
│         alphas.md           ││  Перевірка: LLM_API_KEY != "")│
│  Підстановка: {{AS_OF}},    │└──────────────┬───────────────┘
│   {{COUNT}}, {{FEATURES}}   │               │
└──────────────┬──────────────┘               │ HTTP POST /chat/completions
               │                              ▼
               │               ┌──────────────────────────────┐
               │               │   Зовнішній LLM Endpoint     │
               │               │   (DeepSeek / OpenAI / vLLM) │
               │               └──────────────┬───────────────┘
               │                              │ Raw JSON
               │               ┌──────────────▼──────────────┐
               │               │ 1. Парсинг JSON-масиву       │
               │               │ 2. Feature Contract Guard    │
               │               │    (unknown_identifiers)     │
               │               │ 3. Factor DSL AST валідація  │
               │               │ 4. Запис артефакту .json     │
               │               └──────────────┬───────────────┘
               │                              │
┌──────────────▼──────────────────────────────▼───────────────┐
│                    Вивід результату у UI                    │
│   (Термінальне вікно + додавання картки в Journal)         │
└─────────────────────────────────────────────────────────────┘
```

---

### 5.1. Що необхідно для запуску промпту

Вимоги залежать від вибраного режиму: **Dry run** чи **Реальний виклик**.

#### Варіант 1: Режим Dry run (попередній перегляд — безкоштовно і без ключів)
Якщо позначено чекбокс **Dry run (no API call)**:
1. **API-ключ не потрібен.**
2. Жодні запити в інтернет чи до платних API не відправляються.
3. Потрібен лише запущений бекенд і наявність файлу шаблону промпту `research/prompts/01-generate-alphas.md` (теку задає `LLM_PROMPTS_DIR`). Артефакт у `research/hypotheses/` при цьому **не пишеться**: dry run нічого не створює.
4. Натискання кнопки **«Preview prompt»** згенерує фінальний текст запиту, в якому:
   - `{{AS_OF}}` замінено на поточну дату відсікання знань (модель не повинна знати нічого після цієї дати);
   - `{{COUNT}}` замінено на значення з поля Count;
   - `{{FEATURES}}` замінено на контракт `FEATURE_NAMES` — **12** дозволених ознак у тому порядку, в якому їх повертає рушій (`domain/formulaic_alphas.py`): `ret, ret_5, vol_10, volume_ratio, close_loc, momentum_10, reversal_3, vol_of_vol, trend_er, range_pct, high_low_spread, vol_20`. Це не «будь-які ринкові ознаки», а рівно ті, що рахуються на закритих барах; усе поза цим списком позначиться як `UNKNOWN IDENTIFIERS`.
   - Шаблон, у якому бракує хоч одного з трьох плейсхолдерів, — помилка, а не прогін із порожньою підстановкою.

#### Варіант 2: Бойовий режим генерації (Dry run знято)
Якщо прапорець **Dry run** знято, система надсилає реальний запит до моделі. Для цього у файлі `.env` (або у вкладці **Settings** дашборду) обов'язково мають бути налаштовані змінні:

1. **`LLM_API_KEY`** *(критично, fail-closed)*:
   Секретний ключ вашого API. Якщо він порожній або відсутній, бекенд поверне помилку 400:
   ```
   LLM_API_KEY is not set, so propose fails closed. Set it in .env, or use dry_run=true.
   ```
2. **`LLM_BASE_URL`** *(типово: `https://api.deepseek.com/v1`)*:
   Базова адреса будь-якого OpenAI-сумісного сервісу:
   - **DeepSeek API**: `https://api.deepseek.com/v1` (рекомендовано за замовчуванням);
   - **OpenRouter**: `https://openrouter.ai/api/v1`;
   - **OpenAI**: `https://api.openai.com/v1`;
   - **Локальний сервер без цензури та витрат (Ollama / vLLM)**: `http://localhost:11434/v1` (працює локально, ключ можна вказати довільний, наприклад `ollama`).
3. **`LLM_MODEL`** *(типово: `deepseek-chat`)*:
   Назва моделі, наприклад: `deepseek-chat`, `deepseek-reasoner`, `gpt-4o`, `claude-3-5-sonnet`.
4. **Додаткові налаштування**:
   - `LLM_TEMPERATURE=0.2` (низьке значення для забезпечення строгих формул без галюцинацій);
   - `LLM_TIMEOUT_SECONDS=120` (таймаут генерації).

---

### 5.2. Елементи керування у формі

| Елемент | Значення за замовчуванням | Опис |
|---|---|---|
| **Count** | `5` | Кількість гіпотез, які повинна згенерувати модель у відповіді. |
| **Dry run (no API call)** | `true` (увімкнено) | Запобігає випадковому витрачанню коштів. Зніміть прапорець, коли готові до реального виклику. |
| **Write journal entry** | `false` (вимкнено) | Якщо увімкнено, результат автоматично додасть новий запис зі статусом `pending` у журнал досліджень — `research/journal.md` і `research/journal.jsonl` (шляхи з `JOURNAL_PATH` / `JOURNAL_JSONL_PATH`) — і картка з'явиться на канбан-дошці. |
| **Prompt** | `01-generate-alphas.md` | Необов'язкове поле у вкладці **Alpha Ideas**: назва файлу в теці `LLM_PROMPTS_DIR` або повний шлях. Порожньо — типовий шаблон. |
| **Кнопка запуску** | *Preview prompt* / *Run propose* | Запускає або формування тексту промпту, або відправку запиту до моделі. |

---

### 5.3. Що повертає модель та як влаштована валідація

У разі успішного виклику система виконує багаторівневу перевірку:

1. **Feature Contract Guard**:
   Парсер перевіряє кожну використану в формулі змінну проти списку реальних факторів `FEATURE_NAMES`. Якщо модель використала вигадану ознаку (наприклад, `order_flow_imbalance`, якщо її немає в контракті), така гіпотеза отримує статус:
   `[!] UNKNOWN IDENTIFIERS` з попередженням у терміналі:
   ```
   WARNING: 1 proposal(s) reference identifiers that are not real features.
   That is usually an invented feature - review by hand before any run.
   ```
2. **Перевірка компіляції Factor DSL**:
   Формула перевіряється абстрактним синтаксичним деревом (AST) у модулі [factor_dsl.py](file:///home/volodymyr/PycharmProjects/nautilus-lab/src/nautilus_lab/domain/factor_dsl.py). Розраховується структурна складність (`complexity`).
3. **Збереження незмінного артефакту**:
   Файл пишеться в `LLM_HYPOTHESES_DIR` (типово `research/hypotheses/`) під іменем
   `<as_of>-<model>-<prompt_sha256[:8]>.json`, наприклад `2026-01-31-deepseek-chat-9a1c4f77.json`.
   Якщо такий файл уже існує, додається суфікс `-r2`, `-r3`… — попередній прогін **не
   перезаписується ніколи**, навіть тим самим промптом і моделлю. Поля артефакту:

   ```json
   {
     "version": 1,
     "created_at": "2026-01-31T09:12:44+00:00",
     "model": "deepseek-chat",
     "endpoint_host": "api.deepseek.com",
     "as_of": "2026-01-31",
     "prompt_file": "research/prompts/01-generate-alphas.md",
     "prompt_sha256": "9a1c4f77...",
     "feature_contract": ["ret", "ret_5", "vol_10", "volume_ratio", "close_loc", "momentum_10", "reversal_3", "vol_of_vol", "trend_er", "range_pct", "high_low_spread", "vol_20"],
     "count_requested": 5,
     "count_parsed": 4,
     "count_flagged": 1,
     "hypotheses": [],
     "raw_response": "…сира відповідь моделі…",
     "review": {
       "status": "pending",
       "note": "",
       "gates": { "purged_cv": null, "walk_forward_oos": null, "buy_and_hold_oos": null }
     }
   }
   ```

   Тобто зберігається не сам рендер промпту, а його шлях і `sha256` (рендер відтворюється
   з шаблону, `count` і `as_of` — саме тому `as_of` фіксується в імені файлу), плюс сира
   відповідь моделі, структурований масив гіпотез і блок аудиту `review` для фіксації
   результатів бектесту людиною.

#### Структура валідної гіпотези:

```json
{
  "name": "mom_vol_ratio",
  "formula": "zscore(delta(close, 5)) * rank(volume)",
  "mechanism": "Короткостроковий імпульс ціни, підтверджений сплеском об'єму, відображає агресивний ринковий ордер покупців, який розбирає ліквідність у стакані.",
  "horizon_bars": 5,
  "expected_sign": 1,
  "kill_condition": "Середній OOS IC падає нижче 0 або прибутковість після вирахування taker-комісії стає від'ємною.",
  "unknown_identifiers": []
}
```

- `formula` — математичний вираз над дозволеними функціями (`ALLOWED_FORMULA_FUNCTIONS`: `abs, clip, corr, delta, delay, log, max, mean, min, pow, rank, sign, sqrt, std, sum, ts_max, ts_mean, ts_min, ts_std, zscore`).
- `mechanism` — економічне обґрунтування: чому ця неефективність існує і хто оплачує наш прибуток.
- `expected_sign` — очікуваний напрямок: `+1` (ріст), `-1` (падіння).
- `kill_condition` — критерій спростування гіпотези (захист від самообману).
- `unknown_identifiers` — не порожній лише тоді, коли формула згадує щось поза контрактом; це **лінт, а не гейт**: він показує людині, що саме модель вигадала, і рішення лишається за нею.

---

### 5.4. Той самий контур із CLI: `lab propose`

Дашборд і CLI запускають один і той самий `execute_propose()`, тож прапорці вкладки
**Alpha Ideas** і прапорці команди — це той самий набір (`src/nautilus_lab/interfaces/cli.py`):

| Прапорець | Типово | Що робить |
|---|---|---|
| `--prompt` | `01-generate-alphas.md` | Файл промпту або гола назва у теці `LLM_PROMPTS_DIR` (`research/prompts/`). Відсутній або порожній файл → помилка, а не прогін із порожнім промптом. |
| `--count` | `5` | Скільки гіпотез просити (`count >= 1`). |
| `--as-of` | сьогодні (UTC) | Дата відсікання знань у форматі `YYYY-MM-DD`; саме її бачить модель і саме вона потрапляє в ім'я артефакту. |
| `--model` | `LLM_MODEL` (`deepseek-chat`) | Ідентифікатор моделі. |
| `--base-url` | `LLM_BASE_URL` (`https://api.deepseek.com/v1`) | OpenAI-сумісна база; локальні сервери (`http://localhost:11434/v1`) теж працюють. |
| `--output-dir` | `LLM_HYPOTHESES_DIR` (`research/hypotheses/`) | Куди писати артефакт. |
| `--slug` | — | Перевизначити базове ім'я артефакту. |
| `--dry-run` | вимкнено | Відрендерити промпт, нікуди не дзвонити й нічого не писати. Ключ не потрібен. |
| `--journal` | вимкнено (або `JOURNAL_ENABLED=true`) | Додати рядок `pending` у журнал досліджень. |

```bash
.venv/bin/lab propose --dry-run --count 5 --as-of 2026-01-31   # перегляд промпту, без мережі й витрат
.venv/bin/lab propose --count 5 --journal                      # реальний виклик моделі
```

**Fail closed на ключі.** Реальний виклик без `LLM_API_KEY` не «тихо пропускається»: API
повертає `400` з текстом `LLM_API_KEY is not set, so propose fails closed. Set it in .env, or use dry_run=true.`,
CLI друкує те саме в `stderr` і виходить з кодом `1`.

**Ніяких LLM на гарячому шляху.** Мережу до моделі тримає рівно один контур —
`application/propose_alphas.py` (логіка) і `infrastructure/llm_client.py`
(`OpenAICompatibleChatClient`); імпортують їх лише `composition.py`, `cli.py`, `api/app.py`
і `run_alpha_proposal.py`, тож жоден бектест їх не бачить. Модель лише пропонує: артефакт
фіксується, рішення ухвалює людина, і тільки тоді щось потрапляє в `domain/`
(`docs/14-llm-model-u-torhivli.md`, розділ 1).

---

## 6. Робочий процес після отримання гіпотез

Отримання гіпотези від Alpha Proposer — це лише початок дослідження:

```
[ Alpha Proposer (LLM) ]
          │
          ▼
 [ Артефакт у research/hypotheses/*.json ]
          │
          ▼
 [ Перегляд людиною-дослідником ]
          │
          ▼
 [ Реалізація фактора у formulaic_lgbm або нової стратегії ]
          │
          ▼
 [ Вкладка Research & Backtest: Walk-Forward OOS бектест ]
          │
          ▼
 [ Порівняння з Buy & Hold та breakeven-fee ]
          │
          ▼
 [ Experiment Journal: фіксація рішення (Accepted / Rejected) ]
```

1. **Ручний аудит**: перевірте економічний глузд та відсутність `UNKNOWN IDENTIFIERS`.
2. **Тестування на історії**:
   - Перейдіть на вкладку **Research & Backtest**;
   - Оберіть робота `formulaic_lgbm` або відповідну стратегію;
   - Запустіть Walk-Forward бектест із кількома фолдами (`folds >= 2`).
3. **Фіксація результату**:
   - Перейдіть на вкладку **Experiment Journal**;
   - Перетягніть картку дослідження у стовпчик **accepted** (якщо стратегія стабільно перемагає Buy&Hold з урахуванням реальних комісій) або **rejected** (якщо перевагу не виявлено).
