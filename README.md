# nautilus-lab

Лабораторія роботів для біржової торгівлі на [NautilusTrader](https://github.com/nautechsystems/nautilus_trader). Рушій event-driven (Rust + Python): підходить і для середньої частоти (бари 1–15 хв), і як база під HFT (тіки / стакан).

**За замовчуванням це research / симуляція. Live-ордери вимкнені.** Спочатку вчимось на бектесті, потім (окремим рішенням) paper, і лише після цього — live.

## Що всередині

| Шар | Де | Навіщо |
|-----|----|--------|
| Domain | `src/nautilus_lab/domain/` | Сигнали, бари, EMA, ліміти ризику. Без біржі і без Nautilus. |
| Application | `src/nautilus_lab/application/` | Розмір позиції, circuit breaker, запуск research. |
| Infrastructure | `src/nautilus_lab/infrastructure/` | Nautilus BacktestEngine, комісії, slippage, latency. |
| Interfaces | `src/nautilus_lab/interfaces/` | CLI `lab` — єдина точка збору залежностей. |

Перший робот — **EMA crossover** (швидка/повільна середня). Стратегія лише каже *купити / продати*. Скільки лотів і чи взагалі можна входити — вирішує ризик-сервіс.

## Встановлення

Потрібні Python 3.12+ і [uv](https://docs.astral.sh/uv/):

```bash
cd nautilus-lab
cp .env.example .env
uv sync --extra dev
```

## Перший запуск (симуляція)

```bash
uv run lab research
uv run lab research --bars 5000
```

Команда згенерує синтетичні 1-хвилинні бари ETH/USDT, прогонить їх через Nautilus з **комісіями, 50 мс latency і ймовірністю slippage**, і надрукує кількість філів.

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

1. Справжні історичні дані в Parquet catalog Nautilus (не синтетика).
2. Walk-forward: параметри підбирати на одній ділянці, звітувати на іншій.
3. Paper: публічні котирування, **без** реальних ордерів.
4. Live — тільки після явного запиту і окремих ключів у локальному `.env`.

Документація рушія: https://nautilustrader.io/docs/latest/getting_started/
