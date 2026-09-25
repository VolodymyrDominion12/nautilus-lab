# nautilus-lab

Лабораторія роботів для біржової торгівлі на [NautilusTrader](https://github.com/nautechsystems/nautilus_trader). Рушій event-driven (Rust + Python): підходить і для середньої частоти (бари 1–15 хв), і як база під HFT (тіки / стакан).

**За замовчуванням це research / симуляція. Live-ордери вимкнені.** Спочатку вчимось на бектесті, потім (окремим рішенням) paper, і лише після цього — live.

## Документація

Повний посібник — у теці [`docs/`](docs/README.md). Написаний так, щоб було зрозуміло навіть без досвіду в трейдингу.

| Документ | Про що |
|----------|--------|
| [docs/01-osnovy.md](docs/01-osnovy.md) | Що це, базові поняття бектесту, глосарій |
| [docs/02-vstanovlennya.md](docs/02-vstanovlennya.md) | Встановлення, `.env`, усі змінні, швидкий старт |
| [docs/03-arhitektura.md](docs/03-arhitektura.md) | Шари системи і повний ланцюг даних |
| [docs/uml/](docs/uml/README.md) | UML-діаграми: як працює застосунок (класи, послідовності, стани) |
| [docs/04-tsykl-doslidzhennya.md](docs/04-tsykl-doslidzhennya.md) | **Повний цикл дослідження** на реальних даних, з прикладами виводу |
| [docs/05-roboty.md](docs/05-roboty.md) | Кожен робот: логіка, параметри, реальні результати |
| [docs/06-ryzyk-metryky.md](docs/06-ryzyk-metryky.md) | Ризик-менеджмент, розмір позиції, метрики |
| [docs/07-yak-stvoryty-strategiyu.md](docs/07-yak-stvoryty-strategiyu.md) | **Як створити свою стратегію** — покроково, з кодом і тестами |
| [docs/08-mft-2026-vidpovidnist.md](docs/08-mft-2026-vidpovidnist.md) | Що з «Стратегій MFT 2026» уже в коді, що частково, чого немає |
| [docs/13-ai-2026-vidpovidnist.md](docs/13-ai-2026-vidpovidnist.md) | Що з «Алгоритми ШІ 2026» можна застосувати безпечно (overlays, нові роботи) |
| [docs/09-mft-moduli-pryklady.md](docs/09-mft-moduli-pryklady.md) | Робочі приклади для VPIN, Хоукса, GLFT, funding, Келлі тощо |
| [docs/10-cli-dovidnyk.md](docs/10-cli-dovidnyk.md) | Довідник усіх команд і прапорців |
| [docs/11-troubleshooting-faq.md](docs/11-troubleshooting-faq.md) | Типові помилки, дивна поведінка, часті питання |
| [docs/12-karta-fayliv.md](docs/12-karta-fayliv.md) | Карта всіх модулів і публічного API |
| [docs/14-llm-model-u-torhivli.md](docs/14-llm-model-u-torhivli.md) | Як LLM/LRM-модель допомагає в торгівлі (і де їй не місце) + офлайн-контур гіпотез |
| [docs/15-audit-vypravlennya.md](docs/15-audit-vypravlennya.md) | Аудит коректності: знайдені помилки логіки та як їх виправлено |
| [docs/16-llm-vidpovidnist.md](docs/16-llm-vidpovidnist.md) | Мапа LLM-огляду → код: які ролі LLM реалізовані, які свідомо ні |
| [docs/17-ml-ansambli-vidpovidnist.md](docs/17-ml-ansambli-vidpovidnist.md) | Мапа ML-огляду (ансамблі, TBM, мета-маркування, CPCV/DSR/PBO) → код |
| [docs/18-transformery-ssm-vidpovidnist.md](docs/18-transformery-ssm-vidpovidnist.md) | Трансформери / SSM / xLSTM: чому не беруться і що переноситься дешево |
| [docs/19-ml-steking-vidpovidnist.md](docs/19-ml-steking-vidpovidnist.md) | ML стекінг vs мета-маркування; дірки в навчанні моделей і їх закриття |
| [docs/20-veb-dashbord-ta-alpha-proposer.md](docs/20-veb-dashbord-ta-alpha-proposer.md) | **Веб-дашборд** (React + FastAPI): API, вкладки, безпека, Alpha Proposer |
| [docs/21-roadmap-rozvytku.md](docs/21-roadmap-rozvytku.md) | Стратегічний роудмап розвитку та критерії валідації |
| [docs/22-plan-realizatsii-roadmap.md](docs/22-plan-realizatsii-roadmap.md) | План реалізації роудмапу, звірений із кодом |
| [docs/23-infrastruktura-danyh-plan.md](docs/23-infrastruktura-danyh-plan.md) | Інфраструктура даних: аудит зовнішнього огляду проти коду, що потрібно, а що ні |
| [docs/24-paper-treydynh.md](docs/24-paper-treydynh.md) | **Paper-сесії**: як запускати, які роботи проходять, виміряні числа, чому тікові дані поки не основа |
| [docs/25-xsmom-ta-vorota-dopusku.md](docs/25-xsmom-ta-vorota-dopusku.md) | **Крос-секційний momentum** (`lab xsmom`) і **ворота допуску**: пороги, які робот мусить пройти до paper |
| [docs/26-deploy-vps.md](docs/26-deploy-vps.md) | **Деплой на VPS**: живий paper 24/7 з журналом і відновленням, `LAB_ROLE=paper`, Docker + Caddy + Tailscale, збирач тіків, `pull_vps.sh` |
| [docs/План багатороботний paper-термінал.md](docs/План%20багатороботний%20paper-термінал.md) | План багатороботного paper-терміналу: кілька незалежних сесій, портфель, спільні фіди |

## Що всередині

| Шар | Де | Навіщо |
|-----|----|--------|
| Domain | `src/nautilus_lab/domain/` | Сигнали, бари, EMA, ліміти ризику. Без біржі і без Nautilus. |
| Application | `src/nautilus_lab/application/` | Розмір позиції, circuit breaker, ingest, walk-forward, ворота допуску. |
| Infrastructure | `src/nautilus_lab/infrastructure/` | Binance REST/WebSocket, Parquet catalog, Nautilus BacktestEngine, комісії, slippage, paper-сесії. |
| Interfaces | `src/nautilus_lab/interfaces/` | CLI `lab` — єдина точка збору залежностей. |
| API | `src/nautilus_lab/api/` | FastAPI-дашборд: запускає ті самі use cases, що й CLI. |
| Frontend | `frontend/` | React + TypeScript + Vite UI до цього API (окрема тека, окремий `package.json`). |
| Deploy | `deploy/` | Docker Compose + Caddy + конфіги VPS для живого paper 24/7. |

Роботів у домені **11** (`RobotName` у `domain/regime.py`), і це не те саме, що
«роботів, яких рушій уміє зібрати»: до бектесту підключено **8** з них
(`BACKTEST_WIRED_ROBOTS`) — `regime`, `ema`, `pairs`, `vpin_momentum`,
`formulaic_lgbm`, `meta_label`, `adaptive_ema`, `ml_obi`. Решта (`funding`, `glft`,
`tri_scan`) — поки лише доменні будівельні блоки, і спроба запустити їх падає
явно, а не підміняється іншою стратегією. Деталі й статуси — [docs/05](docs/05-roboty.md).

Перший робот — **regime**: класифікатор ринку (Kaufman Efficiency Ratio + нахил EMA) і три окремі стратегії:

| Ринок | Стратегія |
|-------|-----------|
| Тренд вгору | Donchian breakout long (імпульс за максимумами) |
| Тренд вниз | Donchian breakout short (імпульс за мінімумами) |
| Флет | Bollinger mean reversion (відкупити низ, продати верх) |

Стратегія лише каже *купити / продати / вийти в кеш*. Скільки лотів і чи взагалі можна входити — вирішує ризик-сервіс. При зміні режиму позиція закривається. Live-ордери як і раніше вимкнені.

## Встановлення

Потрібні Python 3.12+ і [uv](https://docs.astral.sh/uv/):

```bash
cd nautilus-lab
cp .env.example .env

# Базове встановлення для розробки:
uv sync

# Веб-дашборд (FastAPI + uvicorn):
uv sync --extra api

# Або повний стек плагінів (LightGBM, Optuna, Plotly, алерти, дашборд):
uv sync --extra ml --extra research --extra visualization --extra alerts --extra api
```

Група `dev` (pytest, ruff, mypy, coverage, hypothesis) ставиться `uv sync` за замовчуванням
(`[dependency-groups]`). Optional extras із `pyproject.toml`: `api`
(fastapi, uvicorn, websockets, pyyaml, python-dotenv — потрібен для дашборду),
`ml` (LightGBM), `research` (optuna, arch, polars), `visualization` (plotly, kaleido),
`alerts` (httpx).

## Запуск досліджень та інструментів

```bash
# 1. Публічні Binance klines → Nautilus Parquet catalog (без API-ключів):
uv run lab ingest --start 2025-01-01

# 2. Walk-forward: підбір параметрів на 70% історії, звіт на решті 30%:
uv run lab research
uv run lab research --robot ema

# 3. Байєсівська оптимізація Optuna (підбір параметрів на In-Sample без перенавчання):
uv run lab research --optuna --trials 30

# 4. Інтерактивний HTML Tearsheet (крива капіталу, просадки, теплова карта, угоди):
uv run lab research --tearsheet reports/tearsheet.html

# 5. Сповіщення в Telegram / Webhook після завершення або при спрацюванні лімітів:
uv run lab research --optuna --trials 20 --notify

# 6. Багатовіконний walk-forward: N ковзних фолдів і агрегат out-of-sample.
#    Одна нарізка дає одне число з однієї ділянки історії; це дає розподіл.
uv run lab research --robot regime --folds 4

# 7. Аудит перенавчання (PBO/CSCV): чи взагалі щось значить підбір параметрів.
#    Рахує ймовірність того, що переможець in-sample провалиться out-of-sample.
uv run lab research --robot regime --pbo
```

`lab research` за замовчуванням читає catalog і робить walk-forward. Друкує окремо in-sample (лише вибір параметрів) і out-of-sample (це і є звіт). Не дивись на in-sample як на результат.

`--folds N` (N ≥ 2) виконує окремий walk-forward на кожному з N ковзних фолдів — на кожному фолді параметри підбираються заново на його власному in-sample — і друкує агрегат out-of-sample разом із планкою `buy&hold`. Жоден робот досі не має виміряної переваги над buy&hold: у `specs/strategies/` немає жодного статусу `validated`, і це задокументований результат, а не «ще не дороблено». Деталі — [docs/05 §4](docs/05-roboty.md) і [docs/24 §4](docs/24-paper-treydynh.md).

Повний прогін на всій вибірці (це **не** out-of-sample):

```bash
uv run lab research --full-sample
```

Синтетика лишається для тестів і демо без мережі:

```bash
uv run lab research --synthetic --bars 5000
uv run lab research --synthetic --bars 1000 --tearsheet reports/synthetic_tearsheet.html
```

## Інші джерела даних

`lab ingest` уміє не лише klines — усе з публічних ендпоінтів, без ключів:

```bash
uv run lab ingest --incremental                   # дописати тільки нові бари (пропустити, якщо вже актуально)
uv run lab ingest --funding --symbols ETHUSDT     # розрахунки фінансування USD-M → catalog/data/funding/
uv run lab ingest --trades --symbols ETHUSDT      # агреговані угоди (тіки) → catalog/data/agg_trade/
uv run lab ingest --trades --live-ticks 20 --symbols ETHUSDT   # 20 хв живого WS-потоку замість REST-історії
uv run lab ingest --depth --symbols ETHUSDT       # живі L2-снапшоти стакану; працює, доки не зупиниш
```

Тіки потрібні для **справжнього** VPIN і Хоукса, і це не те саме, що бар-рівневий
фільтр. `lab research` має три різні прапорці:

| Прапорець | На чому рахує | Що потрібно |
|-----------|---------------|-------------|
| `--bar-vpin` | обсяг **бару** як проксі потоку | нічого додатково |
| `--tick-vpin` | справжні агреговані угоди | серія `agg_trade` у каталозі |
| `--hawkes` | справжня інтенсивність Хоукса | серія `agg_trade` у каталозі |

Пастка: рушій читає **відсутню** серію тіків як порожню (`agg_trades_catalog.py`), тож
`--tick-vpin` на каталозі без `--trades` не падає — він просто не має на чому
рахувати. Перевіряй наявність серії заздалегідь (веб-дашборд показує її як
`present`/`missing` по кожному інструменту).

## ML-конвеєр

```bash
uv run lab ml train --model-type meta_label --catalog catalog --output models/meta.txt
uv run lab ml train --model-type formulaic --output models/formulaic.txt --folds 5 --embargo 10
uv run lab ml train --model-type obi --output models/obi.txt        # потрібна серія стакану
```

Навчання йде з **purged K-fold** (`--folds`, `--embargo`) і потрійним бар'єром
(`--profit`, `--stop`, `--horizon`, `--vol-window`) — тобто з тим самим захистом від
просочування майбутнього, що й у бектесті. Команда друкує `saved=<шлях> rows=...
folds=...` і потребує extra `ml` (`uv sync --extra ml`); без нього вона падає з
`lightgbm extra not installed`. Далі шлях до моделі передається роботам через
`FORMULAIC_MODEL_PATH`, `META_LABEL_MODEL_PATH` або `ML_OBI_MODEL_PATH`. Якщо шляху
немає, роботи цих родин беруть евристичний класифікатор — і саме тому без
натренованої моделі вони схильні **не торгувати** (це чесний `fills=0`, а не зламаний
режим; див. [docs/24 §5](docs/24-paper-treydynh.md)).

## Крос-секційний momentum

```bash
uv run lab xsmom --symbols BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT --folds 6   # кошик, walk-forward по фолдах
uv run lab xsmom --symbols BTCUSDT,ETHUSDT --lookbacks 14,30,60 --top-n 2,3 --rebalance 7
uv run lab xsmom --symbols BTCUSDT,ETHUSDT --pbo                       # + аудит перенавчання і ворота
```

Робот ранжує кошик за минулою дохідністю, тримає `top-n` найсильніших і переранжовує
кожні `--rebalance` барів. Наприкінці друкується рядок **воріт допуску**
(`promotion_gate=PROMOTE|REJECT|INCOMPLETE`), пороги яких зафіксовані заздалегідь у
`application/promotion_gate.py`: `folds ≥ 6`, частка прибуткових OOS-фолдів ≥ 0.83,
OOS-філів ≥ 30, `PBO ≤ 0.3`, `DSR ≥ 0.95`. Будь-яка неперевірена умова читається як
`not measured` і **не** вважається пройденою — тому verdict буває `INCOMPLETE`, і це
не те саме, що `REJECT`. Гіпотеза xsmom наразі відхилена: протокол, пороги й результат
— [docs/25](docs/25-xsmom-ta-vorota-dopusku.md).

## Paper-сесії (репетиція без ордерів)

Paper-сесія проганяє **заморожену** конфігурацію вперед і пише повний журнал: кожен
філ, кожну позицію, комісії, PnL і переоцінку відкритої позиції. Рушій, комісії та
модель філів — ті самі, що в бектесті; ордери нікуди не надсилаються.

```bash
uv run lab paper --robot regime --bars 1500 --journal      # останні 1500 барів каталогу
uv run lab paper --robot pairs --bars 800                  # дві ноги
uv run lab paper --robot vpin_momentum --bars 400 --select-on-is   # параметри — лише на IS
uv run lab paper --robot regime --source live --live-bars 5 # + закриті бари з публічного WS
uv run lab paper --robot regime --bars 200 --tick-vpin       # тік-рівневий фільтр (потрібна серія aggTrades)
```

Тіки можна зібрати лише живим потоком: REST-історія не віддає їх у дослідницькому
масштабі (виміри — [docs/24 §5.2](docs/24-paper-treydynh.md)).

```bash
uv run lab ingest --trades --live-ticks 20 --symbols ETHUSDT   # 20 хв живого потоку в каталог
uv run python scripts/measure_tick_vpin.py --symbol ETHUSDT    # розподіл VPIN на зібраному
```

Сесії дописуються в `reports/paper/sessions.jsonl`. Шість роботів реально торгують у
paper (`regime`, `ema`, `pairs`, `ml_obi`, `meta_label`, `adaptive_ema`); `vpin_momentum`
і `formulaic_lgbm` запускаються й чесно не торгують — причини, числа й виміри в
[docs/24](docs/24-paper-treydynh.md). Жоден робот досі не має виміряної переваги над
buy&hold, тому `lab live` лишається fail closed.

```bash
uv run lab live    # завжди fail closed, код 1
```

## Офлайн-контур ШІ-дослідження (поза гарячим шляхом)

Гіпотези можна просити у великої мовної моделі — але **тільки офлайн**, і кожна
відповідь стає артефактом у git, який перевіряє людина. Жодна стратегія не викликає
LLM, `lab live` і далі fail closed.

```bash
uv run lab propose --dry-run                                      # побачити промпт, без мережі
uv run lab propose --count 5 --journal                            # потрібен LLM_API_KEY у .env
uv run lab propose --base-url http://127.0.0.1:11434/v1 --model qwen2.5:14b

uv run lab research --robot regime --folds 4 --journal            # рядок у журнал дослідження
```

Артефакт лягає в `research/hypotheses/`, рішення по ньому — у `research/journal.md`
(і машинний лог `research/journal.jsonl`); `--journal` лише дописує рядки.
Деталі, пастки (передусім temporal leakage) і шаблони промптів —
[docs/14](docs/14-llm-model-u-torhivli.md) і [research/README.md](research/README.md).

## Як додати свого робота

Проєкт працює за принципом **spec before code**: специфікація пишеться й звіряється з
кодом машиною (`.venv/bin/python specs/_validator.py`), а не тримається «в голові».
Повний протокол — [docs/07](docs/07-yak-stvoryty-strategiyu.md) і
[specs/README.md](specs/README.md); коротко:

1. **Специфікація:** `specs/strategies/<robot>.yaml` за зразком `regime.yaml`, і
   `.venv/bin/python specs/_validator.py <robot>` — нуль помилок **до** коду.
2. Чиста логіка сигналу в `domain/<robot>.py`: клас з `on_bar(bar) -> Signal | None`
   (на вхід — **закритий** бар, на вихід — напрямок, без розміру позиції, без
   `nautilus_trader`, без `.env`, без мережі).
3. Тести в `tests/unit/test_<robot>.py` — без мережі.
4. Додати назву в `RobotName` **і** в `BACKTEST_WIRED_ROBOTS`
   (`domain/regime.py`). Без другого кроку робот падає fail closed:
   `robot '...' has no backtest adapter yet`.
5. Адаптер: гілка в `infrastructure/nautilus/signal_strategy.py::_build_robot()`
   (для спредових пар — `spread_strategy.py`) і проброс параметрів у
   `backtest_runner.py`.
6. Нові параметри — ланцюг із п'яти місць: `infrastructure/settings.py` →
   `.env.example` → `application/dtos.py` → `interfaces/composition.py` →
   `backtest_runner.py`.
7. `application/param_grid.py` — власна гілка сітки (інакше робот тихо візьме сітку
   `regime` і виглядатиме працюючим) і `run_research_backtest.py::minimum_bars` —
   мінімум барів на прогрів.
8. Оновити спеку під фактичні `grid`, `minimum_bars`, `grid_source` і прогнати
   `uv run pytest tests/ -q`.

Paper-режим підхопить робота автоматично: `PAPER_SUPPORTED_ROBOTS` дорівнює
`BACKTEST_WIRED_ROBOTS`, і це закріплено тестом — CLI не може обіцяти робота, якого
рушій не вміє зібрати.

## Ризик (дефолти)

- 0.5% капіталу на угоду
- стоп 1% ціни (або 2×ATR, коли ATR прогрітий): з нього рахується розмір позиції
  (плече 1x), і після входу на цій відстані стоїть reduce-only стоп-ордер
  (`USE_PROTECTIVE_STOP=true`; pairs поки без стопа)
- денний збиток 2% — нові входи стоп
- просадка 6% — нові входи стоп

Це консервативний старт, не «оптимум». Міняй лише свідомо в `.env`.

Запобіжники блокують лише **нові входи**; вихід (FLAT або зустрічний сигнал) ризик-шар
не блокує ніколи. Капітал для кривої, метрик і запобіжників — баланс плюс відкриті
позиції за останньою ціною; позиція, відкрита в кінці вікна, входить у `ending_balance`.

## Дашборд (React + FastAPI)

Дашборд — це **той самий** рушій і ті самі use cases, що й CLI, лише з інтерфейсом:
він не має власної логіки бектесту. Два процеси, API першим.

```bash
# термінал 1 — API на :8000
.venv/bin/uvicorn nautilus_lab.api.app:app --port 8000

# термінал 2 — UI на :5173
cd frontend && npm install && npm run dev
```

`VITE_API_URL` перевизначає адресу API (типово `http://localhost:8000`); у деплої
через один реверс-проксі ставиться `VITE_API_URL=same-origin` (див. `deploy/Caddyfile`).
Деталі фронтенду — [frontend/README.md](frontend/README.md), API, вкладки й Alpha
Proposer — [docs/20](docs/20-veb-dashbord-ta-alpha-proposer.md).

### Безпека API

API дашборду запускає процеси, переписує `.env` і ходить у LLM з ключем із нього, тому
приймає браузерні запити лише з origin дашборду (`API_ALLOWED_ORIGINS`, за замовчуванням
Vite `:5173`/`:4173` і сам API `:8000`). Для додаткового захисту задай `API_TOKEN` у `.env`
і той самий `VITE_API_TOKEN` у `frontend/.env`; тоді кожен виклик `/api` потребує
заголовка `X-Lab-Token`. Запускай API лише на `127.0.0.1`.

Третя, окрема гарантія — **роль сервера**: `LAB_ROLE=paper` робить так, що сервер
приймає лише контроли живого paper-терміналу (`/api/paper/live/*` і створення сесії), а
дослідження, ingest, навчання ML, пропозиції альф і перезапис `.env` — відхиляє.
Це саме те, що потрібно VPS, який торгує 24/7: він не може переписати власні
налаштування з браузера. Деталі — [docs/26](docs/26-deploy-vps.md).

## Тести і якість

```bash
uv run pytest
uv run pytest --cov --cov-report=term-missing   # поріг покриття fail_under = 80
uv run ruff check --fix && uv run ruff format
uv run mypy src tests
.venv/bin/python specs/_validator.py            # спеки проти коду
```

## Далі

1. **Paper** — живий paper-термінал (кілька незалежних сесій, спільні WS-фіди, журнал,
   портфель) можна підняти на VPS: [docs/26](docs/26-deploy-vps.md). Ордери не
   надсилаються.
2. **Live — не «наступний крок», а відсутня підсистема.** Адаптера виконання в проєкті
   немає: `LIVE_ENABLED=true` нічого не змінює, жоден прапорець не робить `lab live`
   робочим, і жоден робот не має виміряної переваги над buy&hold. Це запобіжник, а не
   незавершене налаштування.

Документація рушія: https://nautilustrader.io/docs/latest/getting_started/
