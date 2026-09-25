# Документація nautilus-lab

Повний посібник з лабораторії торгових роботів на [NautilusTrader](https://nautilustrader.io/docs/latest/getting_started/).
Написано так, щоб людина **без досвіду в алгоритмічній торгівлі** могла пройти весь шлях:
від встановлення до власної стратегії, перевіреної на історії.

> **Головне правило цього проєкту.** Тут нічого не торгує реальними грошима.
> `lab live` завжди падає з помилкою (fail closed), `lab research` — це симуляція на
> історії, а `lab paper` проганяє робота вперед і пише повний журнал угод, позицій і
> комісій, не надсилаючи жодного ордера. Живий адаптер виконання не підключений.
>
> «Живий paper» (термінал, що читає закриті бари з публічного WebSocket) — це те саме:
> реальні **дані**, віртуальний рахунок, нуль ордерів на біржі. WebSocket тут лише
> читає публічні потоки.

## З чого почати

| Якщо ти... | Читай у такому порядку |
|------------|------------------------|
| Бачу цей проєкт уперше, не знаю слів «бектест», «спред», «walk-forward» | [01-osnovy.md](01-osnovy.md) → [02-vstanovlennya.md](02-vstanovlennya.md) → [04-tsykl-doslidzhennya.md](04-tsykl-doslidzhennya.md) |
| Хочу просто запустити і побачити результат | [02-vstanovlennya.md](02-vstanovlennya.md) → розділ «Швидкий старт» |
| Хочу зрозуміти, як влаштований код | [03-arhitektura.md](03-arhitektura.md) → [uml/README.md](uml/README.md) → [12-karta-fayliv.md](12-karta-fayliv.md) |
| Хочу написати свою стратегію | [07-yak-stvoryty-strategiyu.md](07-yak-stvoryty-strategiyu.md) |
| Хочу зрозуміти, що з «Стратегій MFT Криптоторгівлі 2026.md» уже є в коді | [08-mft-2026-vidpovidnist.md](08-mft-2026-vidpovidnist.md) |
| Хочу застосувати ідеї з «Алгоритми ШІ У Криптоторгівлі 2026» | [13-ai-2026-vidpovidnist.md](13-ai-2026-vidpovidnist.md) |
| Хочу застосувати ідеї з «ML Ансамблі У Криптотрейдингу» (ансамблі, TBM, мета-маркування, DSR, FFD) | [17-ml-ansambli-vidpovidnist.md](17-ml-ansambli-vidpovidnist.md) |
| Хочу зрозуміти, чи варто брати Transformer / Mamba (SSM) / xLSTM / Kronos | [18-transformery-ssm-vidpovidnist.md](18-transformery-ssm-vidpovidnist.md) |
| Хочу зрозуміти, чи стекінг (Wolpert) щось дає поверх мета-маркування | [19-ml-steking-vidpovidnist.md](19-ml-steking-vidpovidnist.md) |
| Хочу зрозуміти, як LLM/LRM-модель реально допомагає в торгівлі (і де їй не місце) | [14-llm-model-u-torhivli.md](14-llm-model-u-torhivli.md) |
| Хочу працювати через веб-дашборд та генерувати гіпотези в Alpha Proposer | [20-veb-dashbord-ta-alpha-proposer.md](20-veb-dashbord-ta-alpha-proposer.md) |
| Хочу знати, які помилки знайшли в коді та чи їх виправлено | [15-audit-vypravlennya.md](15-audit-vypravlennya.md) |
| Шукаю стратегічний роудмап розвитку та покращення результатів | [21-roadmap-rozvytku.md](21-roadmap-rozvytku.md) |
| Хочу знати, що з роудмапу вже зроблено, а що в ньому застаріло | [22-plan-realizatsii-roadmap.md](22-plan-realizatsii-roadmap.md) |
| Хочу запустити робота в paper-режимі та побачити журнал угод | [24-paper-treydynh.md](24-paper-treydynh.md) |
| Хочу, щоб paper-торгівля йшла 24/7 на VPS, а аналіз — локально | [26-deploy-vps.md](26-deploy-vps.md) |
| Хочу знати, що виправити в інженерії й безпеці перед наступними дослідженнями | [27-audyt-praktyk-2026-ta-roadmap-E.md](27-audyt-praktyk-2026-ta-roadmap-E.md) |
| Хочу підняти веб-дашборд і зрозуміти його вкладки (`frontend/` + `api/`) | [../frontend/README.md](../frontend/README.md) → [20-veb-dashbord-ta-alpha-proposer.md](20-veb-dashbord-ta-alpha-proposer.md) |
| Хочу навчити ML-модель і підключити її до робота (`lab ml train`) | [19-ml-steking-vidpovidnist.md](19-ml-steking-vidpovidnist.md) → [10-cli-dovidnyk.md](10-cli-dovidnyk.md) |
| Хочу одним поглядом побачити стан кожного робота й пороги гейта | [STATUS.md](STATUS.md) (генерується з коду) |
| Хочу знати, чому ухвалено ключові архітектурні рішення | [adr/README.md](adr/README.md) |
| Хочу знати, за якими порогами робот допускають до paper | [STATUS.md](STATUS.md) → [25-xsmom-ta-vorota-dopusku.md](25-xsmom-ta-vorota-dopusku.md) |
| Хочу знати, які зовнішні дані варто підключати, а які ні | [23-infrastruktura-danyh-plan.md](23-infrastruktura-danyh-plan.md) |
| Хочу використати MFT-модулі (VPIN, Хоукс, Келлі, GLFT...) у своєму коді | [09-mft-moduli-pryklady.md](09-mft-moduli-pryklady.md) |
| Шукаю точний синтаксис команд | [10-cli-dovidnyk.md](10-cli-dovidnyk.md) |
| Щось упало з помилкою | [11-troubleshooting-faq.md](11-troubleshooting-faq.md) |

> **Про документи-«відповідності».** Файли `08`, `13`, `16`–`19` і `23` — це мапи
> «зовнішній огляд → модуль коду → статус». Самі огляди (книги й рев'ю про MFT, ШІ, LLM,
> ML-ансамблі, трансформери, стекінг, джерела даних) **не входять у репозиторій**, тому
> посилання на них у тих документах ведуть на шляхи поза цим деревом. Кожна мапа
> самодостатня: вона цитує потрібне твердження й одразу вказує файл коду, тож читати її
> можна без першоджерела.

## Перелік документів

| Файл | Про що |
|------|--------|
| [01-osnovy.md](01-osnovy.md) | Що це за лабораторія, базові поняття трейдингу та бектесту, глосарій термінів |
| [02-vstanovlennya.md](02-vstanovlennya.md) | Встановлення, `.env`, усі змінні налаштування, швидкий старт за 5 команд |
| [03-arhitektura.md](03-arhitektura.md) | Чотири шари (domain / application / infrastructure / interfaces) і повний ланцюг даних |
| [uml/](uml/README.md) | UML: use case, пакети, класи, sequence, activity, стани, deployment |
| [04-tsykl-doslidzhennya.md](04-tsykl-doslidzhennya.md) | Повний цикл дослідження: ingest → walk-forward → стрес-слайси → чутливість → висновок |
| [05-roboty.md](05-roboty.md) | Кожен робот детально: логіка, параметри, статус (`candidate` / `rejected` / `blocked`) і коли він працює, а коли ні |
| [06-ryzyk-metryky.md](06-ryzyk-metryky.md) | Ризик-менеджмент (розмір позиції, стопи, circuit breakers, Келлі, VaR) і як читати метрики |
| [07-yak-stvoryty-strategiyu.md](07-yak-stvoryty-strategiyu.md) | Покроковий рецепт створення нової стратегії + готовий приклад коду й тестів |
| [08-mft-2026-vidpovidnist.md](08-mft-2026-vidpovidnist.md) | Мапа: розділ MFT-документа → модуль коду → статус (готово / частково / немає) |
| [09-mft-moduli-pryklady.md](09-mft-moduli-pryklady.md) | Робочі приклади коду для MFT-модулів, які не підключені до CLI |
| [10-cli-dovidnyk.md](10-cli-dovidnyk.md) | Довідник CLI: усі команди, прапорці (зокрема `--optuna`, `--tearsheet`, `--notify`, `--pbo`), коди виходу, змінні середовища |
| [11-troubleshooting-faq.md](11-troubleshooting-faq.md) | Типові помилки та їх причини, часті питання |
| [12-karta-fayliv.md](12-karta-fayliv.md) | Карта всіх модулів проєкту: файл → що робить → ключові функції |
| [13-ai-2026-vidpovidnist.md](13-ai-2026-vidpovidnist.md) | Мапа ШІ-дослідження 2026 → код (LLM, DRL, overlays, нові роботи) |
| [14-llm-model-u-torhivli.md](14-llm-model-u-torhivli.md) | Як LLM/LRM-модель допомагає в криптоторгівлі: 9 ролей, два контури, шаблони промптів, пастки (зокрема temporal leakage) |
| [15-audit-vypravlennya.md](15-audit-vypravlennya.md) | Аудит коректності: 9 знайдених помилок логіки, як кожну виправлено, і що перевірили та визнали правильним |
| [16-llm-vidpovidnist.md](16-llm-vidpovidnist.md) | Мапа LLM-огляду → код: які ролі LLM реалізовані (офлайн-контур `lab propose`), які ні і чому |
| [17-ml-ansambli-vidpovidnist.md](17-ml-ansambli-vidpovidnist.md) | Мапа ML-огляду (ансамблі GBDT, інформаційні бари, TBM, мета-маркування, CPCV/DSR/PBO, ONNX) → код: що є, що додано (DSR), що свідомо не беремо |
| [18-transformery-ssm-vidpovidnist.md](18-transformery-ssm-vidpovidnist.md) | Мапа огляду «Трансформери проти SSM» → код: чому жодна з архітектур не береться, що переноситься дешево (breakeven-cost, відбір ознак, адаптивне згладжування) і вимір геометрії свічки з Kronos |
| [19-ml-steking-vidpovidnist.md](19-ml-steking-vidpovidnist.md) | Мапа огляду «ML стекінг»: мета-маркування ≠ стекінг; три дірки в навчанні моделей (purging, повний каталог, accuracy vs precision); TabPFN/ONNX/HMM свідомо не беруться |
| [20-veb-dashbord-ta-alpha-proposer.md](20-veb-dashbord-ta-alpha-proposer.md) | Веб-дашборд лабораторії (React + FastAPI) та посібник з генератора гіпотез Alpha Proposer (offline LLM) |
| [21-roadmap-rozvytku.md](21-roadmap-rozvytku.md) | Стратегічний роудмап розвитку: аудит результатів, 5 фаз еволюції (cost-aware відбір, Келлі, funding, Калман, L2/таймфрейми, ансамблі), матриця пріоритетів та критерії валідації |
| [22-plan-realizatsii-roadmap.md](22-plan-realizatsii-roadmap.md) | План реалізації Фази 1, звірений із кодом: які пункти роудмапу вже виконані, який запропонований код був би регресією (подвійний облік комісій), 6 спринтів із критеріями та чесний статус виконаного |
| [23-infrastruktura-danyh-plan.md](23-infrastruktura-danyh-plan.md) | Інфраструктура даних: аудит зовнішнього огляду «Дані для криптотрейдингу та джерела» проти коду — що лабораторії потрібно, а що інституційне і свідомо не береться |
| [24-paper-treydynh.md](24-paper-treydynh.md) | Paper-сесії: як запускати, які роботи реально торгують, виміряні числа, чому тікові дані поки не основа, живий paper на WebSocket |
| [25-xsmom-ta-vorota-dopusku.md](25-xsmom-ta-vorota-dopusku.md) | Крос-секційний momentum (`lab xsmom`) і ворота допуску `promotion_gate`: пороги, зафіксовані до прогону, і результат гіпотези |
| [26-deploy-vps.md](26-deploy-vps.md) | Деплой на VPS: живий paper 24/7 із журналом і відновленням, `LAB_ROLE=paper`, Docker + Caddy + Tailscale, збирач тіків, `pull_vps.sh` |
| [27-audyt-praktyk-2026-ta-roadmap-E.md](27-audyt-praktyk-2026-ta-roadmap-E.md) | Аудит відповідності практикам 2026 (тести, CI, безпека деплою, спостережуваність, відтворюваність, фронтенд) і роудмап E/R-серії з хвилями 0–4 та критеріями готовності |
| [План багатороботний paper-термінал.md](План%20багатороботний%20paper-термінал.md) | План багатороботного paper-терміналу: 3–5 незалежних сесій із власними рахунками, екран «Портфель», один WS-фід на пару символ+інтервал |
| [../frontend/README.md](../frontend/README.md) | Фронтенд: як запускати, вкладки, що UI відмовляється робити (ті самі дослідницькі правила, виражені в інтерфейсі) |
| [../specs/README.md](../specs/README.md) | Spec-Driven Development: специфікація робота як контракт, який звіряється з кодом машиною |
| [research/](research/) | Дослідницькі матеріали: промпти для LLM, гіпотези, журнал досліджень |

## Що вміє проєкт (коротко)

- **Завантаження даних** з публічного Binance (без API-ключів) у Nautilus Parquet-каталог: klines, агреговані угоди (тіки), розрахунки фінансування USD-M і живі L2-снапшоти стакану.
- **Бектест** на реальному рушії NautilusTrader: комісії maker/taker, затримка 50 мс, імовірнісне проковзування.
- **Walk-forward дослідження**: підбір параметрів на першій частині історії (in-sample) і звіт на тій, яку стратегія «не бачила» (out-of-sample), з розривом-embargo.
- **Підбір параметрів двома способами**: невелика сітка (типово) або байєсівська оптимізація Optuna TPE (`--optuna --trials N`).
- **Аудит перенавчання**: `--pbo` рахує ймовірність backtest overfitting (PBO/CSCV) — як часто переможець in-sample провалюється out-of-sample — і **DSR** (дефльований Sharpe) — чи не є Sharpe переможця наслідком самого перебору конфігурацій. Вимірює те, що раніше було неформальним припущенням «сітка мала, отже безпечно» (див. [17](17-ml-ansambli-vidpovidnist.md)).
- **Ворота допуску** (`application/promotion_gate.py`): робот мусить пройти заздалегідь зафіксовані пороги (фолди, частка прибуткових OOS-фолдів, кількість фолів, PBO, DSR) до paper. Неперевірена умова читається як `not measured` — не як пройдена (див. [25](25-xsmom-ta-vorota-dopusku.md)).
- **Звітність і моніторинг**: інтерактивний HTML-тиршит Nautilus (`--tearsheet`), сповіщення в Telegram/Webhook (`--notify`) і **breakeven-cost** (`breakeven_cost_bps` / `paid_cost_bps`) — максимальна комісія на одиницю обороту, за якої PnL прогону дорівнював би нулю (див. [18](18-transformery-ssm-vidpovidnist.md) §3 і [06](06-ryzyk-metryky.md) §7).
- **Роботи**: у домені **11** назв (`RobotName`), до рушія підключено **8** (`BACKTEST_WIRED_ROBOTS`: `regime`, `ema`, `pairs`, `vpin_momentum`, `formulaic_lgbm`, `meta_label`, `adaptive_ema`, `ml_obi`). Решта три (`funding`, `glft`, `tri_scan`) — доменні будівельні блоки й падають fail closed. Статуси — [05](05-roboty.md), специфікації — `specs/strategies/`.
- **Крос-секційний momentum** (`lab xsmom`): ротація кошика спот-монет за минулою доходністю, з ковзним walk-forward і опційним аудитом PBO/DSR.
- **ML-конвеєр** (`lab ml train`): навчання LightGBM-класифікаторів (formulaic / meta_label / obi) з purged K-fold і потрійним бар'єром.
- **Ризик-шар**: розмір позиції від стопу, ATR-стопи, денний ліміт збитку, ліміт просадки, VaR-запобіжник, дробовий Келлі.
- **Paper-режим**: `lab paper` проганяє заморожену конфігурацію вперед і пише повний журнал угод, позицій і комісій, не надсилаючи ордерів; живий paper-термінал читає закриті бари з публічного WebSocket (див. [24](24-paper-treydynh.md)).
- **Веб-дашборд** (React + FastAPI, `frontend/` + `src/nautilus_lab/api/`): запускає ті самі use cases, що й CLI; `LAB_ROLE=paper` обмежує сервер лише живим paper-терміналом (див. [20](20-veb-dashbord-ta-alpha-proposer.md), [26](26-deploy-vps.md)).
- **MFT-модулі** зі «Стратегій MFT Криптоторгівлі 2026.md»: VPIN, процеси Хоукса, коінтеграція + O-U, GLFT-маркет-мейкінг, funding cash-and-carry, трикутний арбітраж Беллмана-Форда, HAR-RV, EGARCH, purged K-fold. Частина з них — готові будівельні блоки, які ще не підключені до CLI (див. [08](08-mft-2026-vidpovidnist.md)).
- **Тести й якість**: `pytest`, `ruff`, `mypy --strict`, поріг покриття 80%, плюс валідатор специфікацій проти коду. Знайдені під час аудиту помилки логіки та регресійні тести на них — [15](15-audit-vypravlennya.md).
- **Офлайн-контур ШІ-дослідження**: `lab propose` питає модель про гіпотези альф (шаблони в `research/prompts/`, артефакти з provenance у `research/hypotheses/`), а `--journal` дописує рядок рішення в `research/journal.md` + машинний лог `research/journal.jsonl`. Модель працює **поза** гарячим шляхом, ключ не потрапляє в артефакт. Див. [14](14-llm-model-u-torhivli.md) і [research/README.md](../research/README.md).

## Технічні факти одним рядком

- Python ≥ 3.12, менеджер залежностей `uv`, залежності: `nautilus-trader`, `numpy`, `pandas`, `pydantic`, `pydantic-settings`.
- Опційні extras: `dev` (pytest, ruff, mypy, coverage), `api` (fastapi, uvicorn, websockets, pyyaml, python-dotenv), `ml` (LightGBM), `research` (arch, optuna, polars), `visualization` (plotly, kaleido), `alerts` (httpx).
- Дві точки входу в **один і той самий** код: консольна команда `lab` (`interfaces/cli.py`) і FastAPI-додаток (`api/app.py`, запускається через `uvicorn nautilus_lab.api.app:app`). Use cases, ризик-шар і рушій у них спільні — другого бектесту не існує.
- Інструменти в симуляції: `ETH/USDT.SIM`, `BTC/USDT.SIM` (спот, венʼю `SIM`) і `ETHUSDT-PERP.SIM` (перпетуал).
- WebSocket є, але **лише для читання публічних даних** (живі закриті бари, aggTrades, L2-снапшоти) і для стріму стану paper-терміналу в UI. Реального виконання ордерів і колокації немає — це дослідницька пісочниця, а не HFT-движок.
- `lab live` fail closed: адаптера виконання не існує, `LIVE_ENABLED=true` нічого не змінює.
