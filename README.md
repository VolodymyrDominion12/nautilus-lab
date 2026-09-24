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
| [docs/24-paper-treydynh.md](docs/24-paper-treydynh.md) | **Paper-сесії**: як запускати, які роботи проходять, виміряні числа, чому тікові дані поки не основа |
| [docs/25-xsmom-ta-vorota-dopusku.md](docs/25-xsmom-ta-vorota-dopusku.md) | **Крос-секційний momentum** (`lab xsmom`) і **ворота допуску**: пороги, які робот мусить пройти до paper |
| [docs/26-deploy-vps.md](docs/26-deploy-vps.md) | **Деплой на VPS**: живий paper 24/7 з журналом і відновленням, `LAB_ROLE=paper`, Docker + Caddy + Tailscale, збирач тіків, `pull_vps.sh` |

## Що всередині

| Шар | Де | Навіщо |
|-----|----|--------|
| Domain | `src/nautilus_lab/domain/` | Сигнали, бари, EMA, ліміти ризику. Без біржі і без Nautilus. |
| Application | `src/nautilus_lab/application/` | Розмір позиції, circuit breaker, ingest, walk-forward. |
| Infrastructure | `src/nautilus_lab/infrastructure/` | Binance klines, Parquet catalog, Nautilus BacktestEngine, комісії, slippage. |
| Interfaces | `src/nautilus_lab/interfaces/` | CLI `lab` — єдина точка збору залежностей. |

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
uv sync --extra dev

# Або повний стек плагінів (візуалізація Plotly, Optuna, Polars, алерти):
uv sync --extra dev --extra research --extra visualization --extra alerts
```

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

`--folds N` (N ≥ 2) виконує окремий walk-forward на кожному з N ковзних фолдів — на кожному фолді параметри підбираються заново на його власному in-sample — і друкує агрегат out-of-sample разом із планкою `buy&hold`. Станом на зараз жоден із трьох роботів цю планку не обганяє; деталі — [docs/05 §4](docs/05-roboty.md).

Повний прогін на всій вибірці (це **не** out-of-sample):

```bash
uv run lab research --full-sample
```

Синтетика лишається для тестів і демо без мережі:

```bash
uv run lab research --synthetic --bars 5000
uv run lab research --synthetic --bars 1000 --tearsheet reports/synthetic_tearsheet.html
```

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

Сесії дописуються в `reports/paper/sessions.jsonl`. П'ять роботів реально торгують у
paper (`regime`, `ema`, `pairs`, `ml_obi`, `meta_label`); `vpin_momentum` і
`formulaic_lgbm` запускаються й чесно не торгують — причини, числа й виміри в
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

1. Напиши чисту логіку сигналу в `domain/` (на вхід — закритий бар, на вихід — `Signal`).
2. Покрий її тестами в `tests/unit/` (без мережі).
3. Тонкий адаптер у `infrastructure/nautilus/` підписується на дані Nautilus, викликає сигнал, потім `evaluate_entry` + `size_position`, і лише тоді `submit_order`.
4. Не став лоти в стратегії вручну і не читай `.env` із domain.

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

## Дашборд і безпека API

API дашборду запускає процеси, переписує `.env` і ходить у LLM з ключем із нього, тому
приймає браузерні запити лише з origin дашборду (`API_ALLOWED_ORIGINS`, за замовчуванням
Vite `:5173`/`:4173` і сам API `:8000`). Для додаткового захисту задай `API_TOKEN` у `.env`
і той самий `VITE_API_TOKEN` у `frontend/.env`; тоді кожен виклик `/api` потребує
заголовка `X-Lab-Token`. Запускай API лише на `127.0.0.1`.

## Тести і якість

```bash
uv run pytest
uv run ruff check --fix && uv run ruff format
uv run mypy src tests
```

## Далі (коли будеш готовий)

1. Paper: публічні котирування, **без** реальних ордерів.
2. Live — тільки після явного запиту і окремих ключів у локальному `.env`.

Документація рушія: https://nautilustrader.io/docs/latest/getting_started/
