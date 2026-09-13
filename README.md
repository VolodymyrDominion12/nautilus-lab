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
| [docs/04-tsykl-doslidzhennya.md](docs/04-tsykl-doslidzhennya.md) | **Повний цикл дослідження** на реальних даних, з прикладами виводу |
| [docs/05-roboty.md](docs/05-roboty.md) | Кожен робот: логіка, параметри, реальні результати |
| [docs/06-ryzyk-metryky.md](docs/06-ryzyk-metryky.md) | Ризик-менеджмент, розмір позиції, метрики |
| [docs/07-yak-stvoryty-strategiyu.md](docs/07-yak-stvoryty-strategiyu.md) | **Як створити свою стратегію** — покроково, з кодом і тестами |
| [docs/08-mft-2026-vidpovidnist.md](docs/08-mft-2026-vidpovidnist.md) | Що з «Стратегій MFT 2026» уже в коді, що частково, чого немає |
| [docs/09-mft-moduli-pryklady.md](docs/09-mft-moduli-pryklady.md) | Робочі приклади для VPIN, Хоукса, GLFT, funding, Келлі тощо |
| [docs/10-cli-dovidnyk.md](docs/10-cli-dovidnyk.md) | Довідник усіх команд і прапорців |
| [docs/11-troubleshooting-faq.md](docs/11-troubleshooting-faq.md) | Типові помилки, дивна поведінка, часті питання |
| [docs/12-karta-fayliv.md](docs/12-karta-fayliv.md) | Карта всіх модулів і публічного API |

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
```

`lab research` за замовчуванням читає catalog і робить walk-forward. Друкує окремо in-sample (лише вибір параметрів) і out-of-sample (це і є звіт). Не дивись на in-sample як на результат.

Повний прогін на всій вибірці (це **не** out-of-sample):

```bash
uv run lab research --full-sample
```

Синтетика лишається для тестів і демо без мережі:

```bash
uv run lab research --synthetic --bars 5000
uv run lab research --synthetic --bars 1000 --tearsheet reports/synthetic_tearsheet.html
```

Інші режими навмисно не торгують:

```bash
uv run lab paper   # ще не підключений live feed
uv run lab live    # завжди fail closed
```

## Як додати свого робота

1. Напиши чисту логіку сигналу в `domain/` (на вхід — закритий бар, на вихід — `Signal`).
2. Покрий її тестами в `tests/unit/` (без мережі).
3. Тонкий адаптер у `infrastructure/nautilus/` підписується на дані Nautilus, викликає сигнал, потім `evaluate_entry` + `size_position`, і лише тоді `submit_order`.
4. Не став лоти в стратегії вручну і не читай `.env` із domain.

## Ризик (дефолти)

- 0.5% капіталу на угоду
- стоп 1% ціни (розмір позиції з цього рахується, плече 1x)
- денний збиток 2% — нові входи стоп
- просадка 6% — нові входи стоп

Це консервативний старт, не «оптимум». Міняй лише свідомо в `.env`.

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
