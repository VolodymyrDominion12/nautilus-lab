# Документація nautilus-lab

Повний посібник з лабораторії торгових роботів на [NautilusTrader](https://nautilustrader.io/docs/latest/getting_started/).
Написано так, щоб людина **без досвіду в алгоритмічній торгівлі** могла пройти весь шлях:
від встановлення до власної стратегії, перевіреної на історії.

> **Головне правило цього проєкту.** Тут нічого не торгує реальними грошима.
> `lab live` завжди падає з помилкою (fail closed), `lab paper` лише пише в лог,
> а `lab research` — це симуляція на історії. Живий адаптер виконання не підключений.

## З чого почати

| Якщо ти... | Читай у такому порядку |
|------------|------------------------|
| Бачу цей проєкт уперше, не знаю слів «бектест», «спред», «walk-forward» | [01-osnovy.md](01-osnovy.md) → [02-vstanovlennya.md](02-vstanovlennya.md) → [04-tsykl-doslidzhennya.md](04-tsykl-doslidzhennya.md) |
| Хочу просто запустити і побачити результат | [02-vstanovlennya.md](02-vstanovlennya.md) → розділ «Швидкий старт» |
| Хочу зрозуміти, як влаштований код | [03-arhitektura.md](03-arhitektura.md) → [12-karta-fayliv.md](12-karta-fayliv.md) |
| Хочу написати свою стратегію | [07-yak-stvoryty-strategiyu.md](07-yak-stvoryty-strategiyu.md) |
| Хочу зрозуміти, що з «Стратегій MFT Криптоторгівлі 2026.md» уже є в коді | [08-mft-2026-vidpovidnist.md](08-mft-2026-vidpovidnist.md) |
| Хочу використати MFT-модулі (VPIN, Хоукс, Келлі, GLFT...) у своєму коді | [09-mft-moduli-pryklady.md](09-mft-moduli-pryklady.md) |
| Шукаю точний синтаксис команд | [10-cli-dovidnyk.md](10-cli-dovidnyk.md) |
| Щось упало з помилкою | [11-troubleshooting-faq.md](11-troubleshooting-faq.md) |

## Перелік документів

| Файл | Про що |
|------|--------|
| [01-osnovy.md](01-osnovy.md) | Що це за лабораторія, базові поняття трейдингу та бектесту, глосарій термінів |
| [02-vstanovlennya.md](02-vstanovlennya.md) | Встановлення, `.env`, усі змінні налаштування, швидкий старт за 5 команд |
| [03-arhitektura.md](03-arhitektura.md) | Чотири шари (domain / application / infrastructure / interfaces) і повний ланцюг даних |
| [04-tsykl-doslidzhennya.md](04-tsykl-doslidzhennya.md) | Повний цикл дослідження: ingest → walk-forward → стрес-слайси → чутливість → висновок |
| [05-roboty.md](05-roboty.md) | Кожен робот детально: `regime`, `ema`, `pairs` — логіка, параметри, коли працює і коли ні |
| [06-ryzyk-metryky.md](06-ryzyk-metryky.md) | Ризик-менеджмент (розмір позиції, стопи, circuit breakers, Келлі, VaR) і як читати метрики |
| [07-yak-stvoryty-strategiyu.md](07-yak-stvoryty-strategiyu.md) | Покроковий рецепт створення нової стратегії + готовий приклад коду й тестів |
| [08-mft-2026-vidpovidnist.md](08-mft-2026-vidpovidnist.md) | Мапа: розділ MFT-документа → модуль коду → статус (готово / частково / немає) |
| [09-mft-moduli-pryklady.md](09-mft-moduli-pryklady.md) | Робочі приклади коду для MFT-модулів, які не підключені до CLI |
| [10-cli-dovidnyk.md](10-cli-dovidnyk.md) | Довідник CLI: усі команди, прапорці, коди виходу, змінні середовища |
| [11-troubleshooting-faq.md](11-troubleshooting-faq.md) | Типові помилки та їх причини, часті питання |
| [12-karta-fayliv.md](12-karta-fayliv.md) | Карта всіх модулів проєкту: файл → що робить → ключові функції |

## Що вміє проєкт (коротко)

- **Завантаження даних** з публічного Binance REST (klines, без API-ключів) у Nautilus Parquet-каталог.
- **Бектест** на реальному рушії NautilusTrader: комісії maker/taker, затримка 50 мс, імовірнісне проковзування.
- **Walk-forward дослідження**: підбір параметрів на першій частині історії (in-sample) і звіт на тій, яку стратегія «не бачила» (out-of-sample), з розривом-embargo.
- **Три роботи**: `regime` (тренд/флет з трьома підстратегіями), `ema` (перетин ковзних), `pairs` (статистичний арбітраж ETH/BTC).
- **Ризик-шар**: розмір позиції від стопу, ATR-стопи, денний ліміт збитку, ліміт просадки, VaR-запобіжник, дробовий Келлі.
- **MFT-модулі** зі «Стратегій MFT Криптоторгівлі 2026.md»: VPIN, процеси Хоукса, коінтеграція + O-U, GLFT-маркет-мейкінг, funding cash-and-carry, трикутний арбітраж Беллмана-Форда, HAR-RV, EGARCH, purged K-fold. Частина з них — готові будівельні блоки, які ще не підключені до CLI (див. [08](08-mft-2026-vidpovidnist.md)).
- **Тести й якість**: `pytest`, `ruff`, `mypy --strict`, порог покриття 80%.

## Технічні факти одним рядком

- Python ≥ 3.12, менеджер залежностей `uv`, залежності: `nautilus-trader`, `numpy`, `pandas`, `pydantic`, `pydantic-settings`.
- Опційні extras: `ml` (LightGBM), `research` (arch — EGARCH).
- Єдина точка входу: консольна команда `lab`.
- Інструменти в симуляції: `ETH/USDT.SIM`, `BTC/USDT.SIM` (спот, венʼю `SIM`) і `ETHUSDT-PERP.SIM` (перпетуал).
- Немає WebSocket, немає реального виконання ордерів, немає колокації — це дослідницька пісочниця, а не HFT-движок.
