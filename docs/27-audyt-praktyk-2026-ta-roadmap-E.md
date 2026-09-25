# 27. Всебічний аудит відповідності практикам 2026 і роудмап E-серії

> **Призначення.** Доповнення до [21-roadmap-rozvytku.md](21-roadmap-rozvytku.md) і
> [22-plan-realizatsii-roadmap.md](22-plan-realizatsii-roadmap.md). Ті документи
> відповідають на питання «які роботи й моделі будувати». Цей документ — на питання
> «на чому вони стоять»: інженерна якість, безпека деплою, спостережуваність,
> відтворюваність, фронтенд, а також дослідницькі практики, яких роудмап ще не
> містить. Нові задачі мають префікс **E-** (engineering) і **R-** (research), щоб не
> перетинатися з нумерацією §8 роудмапу та спринтами S0–S7.
>
> **Метод.** Статичне читання коду й конфігурації 2026-09-24 (тести в цьому аудиті
> **не запускались**). Кожне твердження має посилання на файл. Де стан не перевірено —
> так і написано.

---

## 1. Підсумок одним екраном

| Напрям | Оцінка | Головне |
|---|:-:|---|
| Архітектура домену | 🟢 сильна | 4 шари, `Decimal`, domain без Nautilus/.env, spec-driven, fail-closed live |
| Дослідницька методологія | 🟢 сильна | walk-forward + embargo, PBO/CSCV, DSR, promotion gate, чесні «не виміряно» |
| Python-тулінг | 🟢/🟡 | uv + lock, ruff, mypy strict, CI. Є дрейф версій Python і вузький набір правил ruff |
| Тести й покриття | 🟡 | 80.50 %, але **з покриття виключено саме ті модулі, де жили P0-баги** |
| CI/CD і ланцюг постачання | 🟡 | немає фронтенд-джоби, збірки Docker, аудиту залежностей, SHA-пінів, `permissions:` |
| API-шар | 🟡 | `app.py` = 1549 рядків, 47 маршрутів, стан джобів у глобальних змінних |
| Фронтенд | 🟠 | немає жодного тесту, типи API пишуться вручну, гігантські компоненти (`strict` діяв лише як типове значення TS 6 — записано явно в E-0.4) |
| Деплой і безпека VPS | 🟠 | токен у бандлі + вимкнений `basic_auth` = відкрито на публічному домені; `LAB_UID` не використовується |
| Спостережуваність | 🟠 | немає метрик, health/ready-ендпоінтів, структурованих логів, бекапів журналу |
| Відтворюваність | 🟠 | прогони не фіксують git SHA, хеш `uv.lock`, відбиток каталогу, хеш налаштувань |
| Торговий результат | 🔴 | жоден робот не б'є buy & hold на OOS (`docs/21` §1.2) — це очікувано і чесно задокументовано |

**Висновок.** Найслабше місце проєкту зараз — не стратегії й не математика, а
«периметр»: деплой, спостережуваність, відтворюваність і фронтенд. Саме цей периметр
вирішить, чи можна буде вірити 8-тижневому paper-прогону на VPS. Тому E-хвилі 0–1 стоять
**перед** новими роботами.

---

## 2. Що з попереднього аудиту (2026-09-23) уже закрито

Звірено з кодом:

| ID | Проблема | Стан | Де видно |
|---|---|:-:|---|
| P0-1 | `_equity()` без unrealized PnL | ✅ закрито | `signal_strategy.py:523-543`, `spread_strategy.py` → `domain/marking.marked_equity` |
| P0-2 | відкрита позиція не входить у `ending_balance` | ✅ закрито | `backtest_runner.py:172-173` (`unrealized_pnl(_open_lots(...), spec.marks)`) |
| P0-3 | risk-блок робив `return` до flatten | ✅ закрито | `signal_strategy.py:334-356`: вихід ніколи не гейтиться, вхід гейтиться до відправки виходу |
| P0-4 | стоп лише для sizing | ✅ закрито | `use_protective_stop=True`, `_place_protective_stop` → `stop_market` (`signal_strategy.py:260-290`), тест `tests/integration/test_protective_stop.py` |
| API | CORS `*` + credentials, без auth | ✅ закрито | `api/security.py`: origin-гейт, токен (`hmac.compare_digest`), `LAB_ROLE` fail-closed; `allow_credentials=False` |
| P1 | прапорці `use_tick_vpin`/`use_hawkes` | 🟡 не перевірено повністю | поля є в `SignalRobotConfig`; проходження через `_single_run` цим аудитом не перевірялось |

**Відкритий ризик процесу:** за записами проєкту робота деплою (кроки 1–5) і
багатосесійного paper (етап 1) **не закомічена** і повністю не прогнана
(`uv run pytest`, `npm run build`, `docker compose build`). Це пункт E-0.1 — він
перший, бо незакомічена робота не має ревізії, а `scripts/deploy_vps.sh` шиплять лише HEAD.

---

## 3. Детальні знахідки

### 3.1. Тести й покриття

1. **Покриття виключає критичні адаптери.** `pyproject.toml` → `[tool.coverage.run] omit`
   містить `backtest_runner.py`, `signal_strategy.py`, `instrument.py` — разом ~1400
   рядків, де жили всі чотири P0. Отже, 80.50 % описує код **навколо** рушія, а не сам
   рушій. Інтеграційні тести для них уже є (`tests/integration/*`) — виключення можна
   прибрати, позначивши повільні тести маркером `integration`.
2. **Крок покриття в CI не блокує** (`continue-on-error: true`). Рішення «залишити
   видимим» зрозуміле, але на практиці неблокувальний гейт регресує непомітно.
3. **Немає property-based тестів** для інваріантів, які ідеально під них лягають:
   `marking` (equity = cash + Σ unrealized), `position_plan` (вихід не блокується),
   `walk_forward` (train ∩ test = ∅, embargo дотримано), `quantiles`, `risk`
   (розмір ≤ ліміту). Hypothesis — стандарт для такого коду в 2026.
4. **Немає тесту паритету «бектест ↔ живий paper»** (див. R-1) — відома розбіжність
   з `docs/26`, яка не ловиться жодним гейтом.

### 3.2. Python-тулінг і залежності

1. **Дрейф версій Python.** Локально байткод `cpython-313` (`src/**/__pycache__`),
   у CI і Docker — 3.12, файлу `.python-version` немає. Помилка, що з'являється лише
   на 3.12 (або навпаки), пройде локально.
2. **Dev-інструменти оголошено як extra** (`[project.optional-dependencies].dev`). Extras —
   це публічні метадані пакета; для інструментів розробки з 2025 року є PEP 735
   `[dependency-groups]`, які uv підтримує нативно (`uv sync --group dev`).
3. **Вузький набір правил ruff:** `E F I N UP B SIM ANN RUF`. Для фінансового коду з
   asyncio, датами і підпроцесами варто додати `S` (bandit), `ASYNC`, `DTZ`
   (naive datetime), `PT`, `C4`, `PERF`, `BLE`, `TRY` (вибірково), `PL` (вибірково).
   Показово: у `per-file-ignores` уже є `S101` для тестів, але `S` не ввімкнено — ігнор
   мертвий.
4. **Аудиту вразливостей залежностей немає** (ні `pip-audit`, ні OSV-сканера), немає
   Renovate/Dependabot. При `uv.lock` на 420 КБ оновлення вручну не відбудуться.
5. **Nautilus у beta-циклі** (`nautilus-trader>=1.231.0`, фільтр депрекейшнів у
   `pyproject.toml`). Оновлення рушія змінює результати бектестів — його треба
   робити окремим PR із «золотим» прогоном до/після (див. E-2.6).
6. `ty` (Astral) у 2026 усе ще beta (0.0.x) — **не** заміна mypy strict, але може
   бути швидкою додатковою перевіркою в pre-commit. Рішення опційне.

### 3.3. CI і ланцюг постачання (`.github/workflows/ci.yml`)

1. **Фронтенд у CI не перевіряється взагалі:** немає `npm ci`, `tsc -b`, `oxlint`,
   `vite build`, `check:logic`. Зламаний дашборд пройде зелений CI.
2. **Docker-образи в CI не збираються** — поломку `Dockerfile.api/web` видно лише
   на VPS під час деплою.
3. **Actions запінені тегами** (`actions/checkout@v4`, `astral-sh/setup-uv@v5`), а не
   SHA; немає блоку `permissions:` (типово токен має ширші права, ніж потрібно).
   Після атак на ланцюг постачання 2025 року SHA-піни + мінімальні `permissions` +
   статичний аналіз workflow (zizmor) — базова гігієна.
4. **Немає сканування секретів** (gitleaks/trufflehog) — актуально, бо в репо є
   `.env`-файли й ключі LLM/Telegram/біржі.
5. **Немає pre-commit** — ті самі ruff/mypy/gitleaks локально до коміту.

### 3.4. API-шар (`src/nautilus_lab/api/`)

1. **Моноліт `app.py`:** 1549 рядків, 47 маршрутів, конфігурація читається під час
   імпорту (`SECURITY`, `LIVE_SESSIONS` на рівні модуля).
2. **Стан джобів у глобальних змінних:** `CURRENT_RESEARCH_PROCESS`,
   `CURRENT_INGEST_PROCESS`, `CURRENT_ML_PROCESS`, `CURRENT_PAPER_PROCESS`,
   `JOB_STARTED`, `JOBS_STARTING` + `threading.Lock` і `global` у ~10 функціях.
   Рестарт API губить знання про запущені підпроцеси (сироти), тести мусять
   монкіпатчити модуль.
3. **Відповіді без Pydantic response-моделей** у частині маршрутів → неповна OpenAPI-схема,
   що блокує генерацію типів для фронтенду (E-2.3).
4. Добре: `api/security.py` — чистий, документований, з `hmac.compare_digest` і
   fail-closed ролями.

### 3.5. Фронтенд (`frontend/`)

1. **`strict` не був записаний у `tsconfig.app.json`.** *(Уточнено 2026-09-24 під час
   E-0.4: TypeScript 6.0 вмикає `strict` за замовчуванням, і код його вже проходив —
   початкове твердження «строгість вимкнена» було хибним.)* Ризик був у тому, що
   гарантія трималася на версії компілятора, а не на конфігурації. Тепер `strict` записано
   явно й додано `noUncheckedIndexedAccess`, який знайшов 2 реальні місця доступу за межі
   масиву (зокрема застарілий `hoverIndex` у `EquityCurveChart`).
2. **Жодного тесту** (немає vitest, немає e2e). `check:logic` — лише скрипт.
3. **`services/api.ts` (28 КБ) написано вручну** паралельно з FastAPI → той самий клас
   дрейфу, який `docs/22` §2 фіксує для документації. Рішення 2026: генерувати типи з
   `/openapi.json` (`openapi-typescript`) і перевіряти в CI, що згенероване = закомічене.
4. **Гігантські компоненти:** `ResearchLab.tsx` 56 КБ, `LiveTradingTerminal.tsx` 49 КБ,
   `CatalogManager.tsx` 26 КБ. Розбити на контейнер + презентаційні частини + хуки.
5. **Ручний polling/кеш** — стандартно замінюється TanStack Query (кеш, інвалідація,
   зупинка polling на прихованій вкладці, повтори), що заодно закриває залишок
   «нескінченного polling» з аудиту 09-23.
6. Стек сучасний (React 19, Vite 8, TS 6, Tailwind 4, oxlint) — оновлювати не треба,
   треба дотягнути строгість і тести.

### 3.6. Деплой і безпека VPS (`deploy/`, `scripts/deploy_vps.sh`)

1. **Токен у бандлі.** `Dockerfile.web` компілює `VITE_API_TOKEN` у JS; `config.ts`
   чесно це визнає. На Tailscale/127.0.0.1 (типове `BIND_ADDR`) це прийнятно. Але
   на публічному домені `basic_auth` у `Caddyfile` **закоментований** → будь-хто, хто
   відкрив сторінку, має токен і може керувати paper-сесіями. Потрібен обов'язковий
   зовнішній замок (див. E-0.3).
2. **Токен WebSocket у `?token=`** потрапляє в access-логи Caddy та історію браузера.
   Краще HttpOnly-cookie сесії, яку ставить той самий зовнішній замок, або
   автентифікація першим повідомленням WS.
3. *(Закрито — див. E-0.2: власник обрав uid 1000 + явну відмову API без журналу.)*
   **`LAB_UID`/`LAB_GID` не використовувались.** `deploy_vps.sh` дописує їх у
   `deploy/.env` з коментарем «containers run as the owner of data/…», але
   `docker-compose.yml` не має `user:`, а образ жорстко створює `uid 1000`. Якщо
   SSH-користувач на VPS має інший UID — `permission denied` на `data/`, тобто журнал
   paper не пишеться. Фікс — один рядок.
4. **Немає заголовків безпеки** CSP, HSTS, `Permissions-Policy`, `frame-ancestors`
   у Caddy (є лише `nosniff` і `Referrer-Policy`).
5. **Хардинг контейнерів:** базові образи не запінені digest-ом; немає
   `read_only: true`, `cap_drop: [ALL]`, `security_opt: no-new-privileges`, лімітів
   пам'яті/CPU. Для процесу, що тримає 8 сесій і 5 WS, OOM-kill без ліміту зачепить
   увесь VPS.
6. **Healthcheck на `/`** доводить лише, що uvicorn живий, а не що фіди отримують бари.
7. **Бекапи журналу** — лише ручний `scripts/pull_vps.sh`. Журнал paper — єдине
   джерело правди про 8 тижнів прогону; його втрата = втрата експерименту.

### 3.7. Спостережуваність

У всьому `src/` лише 7 викликів `logging.getLogger`, немає `/metrics`, немає
`/healthz`/`/readyz`, немає структурованих логів. Для 24/7 paper-контуру потрібні
щонайменше: вік останнього бару на кожному фіді, кількість реконектів WS, помилки
запису журналу, equity/позиція кожної сесії, спрацювання breakers — і алерт у Telegram
(`infrastructure/alerts.py` уже є) при застарілому фіді. Плюс «dead man's switch»:
зовнішній пінг, який кричить, коли VPS **мовчить**.

### 3.8. Відтворюваність і походження результатів

Пошук `rev-parse|git_sha|revision|data_hash` у `src/` — порожній. Тобто звіт,
рядок журналу досліджень чи `session_start` у paper-журналі не знають, яким кодом,
яким lock-файлом, якими даними й якими налаштуваннями їх отримано
(`DEPLOYED_REVISION` пишеться лише у файл на VPS). Для проєкту, чия культура
побудована на «вимір або чесне не виміряно», це головна методологічна прогалина:
результат без маніфесту неможливо переперевірити через місяць.

### 3.9. Гігієна репозиторію й документації

1. `Claude outputs/` і `models/` лежать у корені, є в `.dockerignore`, але **не** в
   `.gitignore` → ризик закомітити великі бінарники/чернетки. Перевірити
   `git ls-files models "Claude outputs"`; моделі — або ігнорувати, або git-lfs.
2. **Статуси дублюються** в `docs/21` §1.1.1, §2, §8, `docs/22` §2, §3, §5.1, §7, §8.3,
   `docs/README.md` — кожна звірка оновлює 5–7 таблиць. Це вже породило розбіжність
   порогів: `promotion_gate.py` (фолди ≥ 6, PBO ≤ 0.3, DSR ≥ 0.95) проти `docs/21`
   §10 (фолди ≥ 4, PBO < 0.25, DSR p < 0.05). Джерелом правди має бути код + одна
   згенерована таблиця стану (E-2.8), а рішення — у коротких ADR.
3. `docs/21` — 65 КБ, `docs/22` — 49 КБ. Для людини це вже довідник, а не план.

### 3.10. LLM-контур (`infrastructure/llm_client.py`)

Архітектурно правильно (офлайн, fail-closed, OpenAI-сумісний). Відповідно до практик
2026 бракує: structured outputs / JSON-schema (замість парсингу тексту), повторів із
backoff (є готовий `http_resilience.py`), запису `model` + версії промпта + хешу
відповіді в кожну гіпотезу, і **евал-набору** для proposer-а (яка частка пропозицій
проходить AST-guard, яка — промо-гейт). Без евалу неможливо сказати, чи зміна моделі
чи промпта щось покращила.

---

## 4. Дослідницькі практики, яких немає в `docs/21`

- **R-1. Паритет бектест ↔ paper.** Прогнати ті самі закриті бари через `BacktestEngine`
  і через `paper_streamer` (записаний WS-потік → replay) і вимагати однакових сигналів,
  входів, стопів і equity в межах допуску. Поки паритету немає, 8 тижнів paper
  перевіряють **інший** код, ніж той, що пройшов walk-forward.
- **R-2. Попередня реєстрація.** Перед OOS-прогоном фіксувати в спеці гіпотезу, сітку,
  OOS-період, пороги гейта; хеш цього блоку йде в маніфест прогону (E-1.4). Прогін,
  чий хеш не збігся з зареєстрованим, не може отримати `PROMOTE`.
- **R-3. Глобальний облік кількості спроб для DSR.** DSR має використовувати
  *усі* конфігурації, коли-небудь випробувані на цьому OOS (з `research/journal.md`),
  а не лише сітку поточного прогону — інакше повторні прогони «відмивають» перенавчання.
- **R-4. Бенчмарк із поправкою на ризик.** Поряд із «vs buy & hold» показувати
  vol-matched buy & hold (той самий середній експозиційний ризик). Інакше робот із
  експозицією 30 % завжди програватиме B&H на бичачому OOS і це не є інформацією.
- **R-5. Критерій виходу з paper.** Мінімум 8 тижнів і ≥ 30 угод на сесію; реальні
  paper-метрики мають лягти всередину розподілу, передбаченого бектестом
  (tracking-error, частка угод, середній slippage). Інакше — `REJECT` з причиною.
- **R-6. Калібрування витрат із власних даних.** Коли колектор тіків/книги набере
  4+ тижні, оцінити реальний slippage/spread за годинами доби та замінити константи
  `MAKER_FEE/TAKER_FEE` + фіксоване проковзування на емпіричну модель.
- **R-7. Funding у рушії — спершу перевірити Nautilus.** Перед написанням власного
  P&L-оверлея (роудмап §4.1) перевірити, чи поточна версія NautilusTrader уже
  підтримує дані й нарахування фандингу для перпетуалів у бектесті — власний оверлей
  при наявності нативного = ще один розрив паритету.

---

## 5. Роудмап E/R-серії

Позначення: 🟢 ≤ 1 день · 🟠 2–5 днів · 🔴 > 1 тижня. Дати — орієнтир для однієї
людини з AI-асистентом; кожна хвиля закінчується «зеленими» гейтами.

### Хвиля 0 — стабілізація (28.09 – 04.10.2026)

| ID | Задача | Зусилля | Definition of Done |
|---|---|:-:|---|
| E-0.1 | Закомітити роботу деплою та multi-session окремими комітами; повна локальна перевірка | 🟢 | `uv run pytest` 0 failed, `npm run build` зелений, `docker compose -f deploy/docker-compose.yml build` зелений, push |
| E-0.2 | `user: "${LAB_UID:-1000}:${LAB_GID:-1000}"` для `api` і `collector` у compose | 🟢 | ✅ **вирішено інакше** (рішення власника, 2026-09-24): `LAB_UID` прибрано з `deploy_vps.sh`; теки належать uid 1000 (`sudo chown`), а API відмовляється стартувати без журналу, доступного для запису — неправильний власник більше не мовчить |
| E-0.3 | Обов'язковий зовнішній замок для публічного домену | 🟢 | або лише Tailscale (`BIND_ADDR=100.x`), або `DASHBOARD_AUTH=on`; `deploy_vps.sh` відмовляє, якщо `BIND_ADDR` публічний, а замка немає. ✅ код 2026-09-24: `deploy/check_exposure.sh` + `tests/unit/test_deploy_exposure.py`, Caddy-сніпет `auth_on`; ⏳ `caddy validate` і перевірка на VPS |
| E-0.4 | Явний `"strict": true` + `noUncheckedIndexedAccess`, `noImplicitReturns`, `noImplicitOverride` у `tsconfig.app.json`; виправлення знайденого | 🟢 | `tsc -b` зелений ✅ (зроблено 2026-09-24) |
| E-0.5 | `.python-version` = 3.12 (або перехід на 3.13 скрізь) | 🟢 | локально, CI і Docker — одна версія. ✅ `.python-version`=3.12; ⏳ CI читає його після патча (`uv python install` без версії); ⏳ локально перестворити `.venv` |
| E-0.6 | `permissions: contents: read` у `ci.yml`; `Claude outputs/`, `models/` у `.gitignore` | 🟢 | ✅ `Claude outputs/` у `.gitignore`; ⏳ `permissions: contents: read`, `persist-credentials: false` — у патчі `e1-e19-ci.patch` (замінює `ci-e0.patch`), `.github/`, `Makefile` і `.pre-commit-config.yaml` застосовує власник (захищені від запису інструментом) |

### Хвиля 1 — довіра до paper-прогону (05.10 – 25.10.2026)

| ID | Задача | Зусилля | Definition of Done |
|---|---|:-:|---|
| E-1.1 | CI-джоба `frontend`: `npm ci`, `tsc -b`, `oxlint`, `vite build`, `check:logic` | 🟢 | ✅ код 2026-09-24: `.github/workflows/frontend.yml` (Node з `frontend/.nvmrc` = мажор образу, `npm ci --ignore-scripts`, oxlint, `npm run build` = `tsc -b` + vite, `check:logic`), `make ci-frontend`. ⏳ застосувати патч і побачити зелений прогін |
| E-1.2 | CI-джоба `docker`: збірка обох образів (без push), кеш buildx | 🟢 | ✅ код 2026-09-24: `.github/workflows/images.yml` (buildx-збірка api/web з кешем GHA, без push; `docker compose config` з обома профілями; `check_exposure.sh`; `caddy validate` для auth off/on), фільтр шляхів, `make ci-images`. ⏳ застосувати патч |
| E-1.3 | Ланцюг постачання: SHA-піни actions, Renovate (групи: python, npm, actions, docker; Nautilus — окремо), `pip-audit`/OSV, gitleaks, pre-commit | 🟠 | ✅ код 2026-09-24: `renovate.json` (групи python/npm/actions/docker, NautilusTrader — окремий PR з приміткою про золотий бектест, SHA-піни actions і digest-піни образів, `minimumReleaseAge` 3 дні, щотижня + вразливості одразу, gitleaks через regex-manager); `.github/workflows/security.yml` (pip-audit по `uv.lock`, `npm audit` runtime, gitleaks по всій історії з перевіркою checksum, zizmor — неблокуючий до першого PR Renovate); `.pre-commit-config.yaml` (ruff/mypy через `uv run`, gitleaks, базові хуки); `make audit`, `make precommit-install`; тест `tests/unit/test_ci_workflows.py`. ⏳ встановити Renovate App, застосувати патч, після PR-пінів зробити zizmor блокуючим |
| E-1.4 | **`RunManifest`**: git SHA + dirty, хеш `uv.lock`, версія Nautilus, хеш налаштувань, відбиток каталогу (перелік файлів + розміри + mtime або sha256), seed-и; пишеться в кожен звіт, рядок журналу досліджень і `session_start` | 🟠 | ✅ код 2026-09-24: `domain/provenance.py` (`RunManifest`), `infrastructure/provenance.py` (git → `LAB_REVISION` → `DEPLOYED_REVISION`; хеш налаштувань без секретів; відбиток каталогу = шлях+розмір); друкується першим у `lab research`/`lab xsmom` і в лозі дашборд-джоби, лягає в `journal.jsonl`, `last_run.json`, `session_start`/`session_resume` paper-журналу; `live_paper_report.py` показує `code=` і зміну коду посеред сесії; `LAB_REVISION` у `Dockerfile.api`/compose/`deploy_vps.sh`. Тести `tests/unit/test_provenance.py` (22). Seed-и й хеш передреєстрації — у R-2 |
| E-1.5 | `/healthz` (процес) і `/readyz` (кожен фід отримав бар не пізніше 2 × інтервал); Docker healthcheck → `/readyz` | 🟢 | ✅ код 2026-09-24: `api/health.py`; фід оцінюється за віком останнього повідомлення й закритого бару (`MarketFeed` записує час), сесія — за останнім записом журналу; `/healthz`, `/readyz` (200/503), Docker `HEALTHCHECK` → `/readyz`, обидва проксіюються Caddy для зовнішнього монітора. ⏳ перевірити на VPS |
| E-1.6 | Метрики Prometheus (`/metrics`, за токеном) + JSON-логи; алерт у Telegram на застарілий фід, помилку журналу, спрацювання breaker (це заодно закриває S3 для живого контуру) | 🟠 | ✅ код 2026-09-24: watchdog (лише зміни стану) → Telegram/webhook для завислого фіду, збою журналу, першого спрацювання circuit breaker у сесії, плюс повідомлення на старт; `/api/metrics` (Prometheus-текст без залежностей). ⏳ JSON-логи не зроблено; ⏳ перевірка обривом WS на VPS |
| E-1.7 | Бекап `data/paper/` щогодини (restic/rsync поза VPS) + dead-man's switch | 🟢 | ✅ код 2026-09-24: сервіс `backup` (profile, `restic/restic`, `deploy/backup.sh`: init, щогодинний знімок, prune раз на добу, heartbeat після успіху; дані `:ro`), тести `tests/unit/test_deploy_backup.py` зі stub-restic; heartbeat API (`Heartbeat` у `api/health.py`, `LIVE_PAPER_HEARTBEAT_URL`, пінг лише поки ready, `FAIL_URL` необов'язковий). ⏳ налаштувати сховище, **один раз відновитися вручну** (docs/26 §7.1) |
| E-1.8 | Хардинг compose: `read_only`, `tmpfs`, `cap_drop: [ALL]`, `no-new-privileges`, `mem_limit`; CSP/HSTS у Caddy; базові образи за digest (оновлює Renovate) | 🟢 | ✅ код 2026-09-24: `x-hardening` для всіх 4 сервісів (read_only, tmpfs /tmp, cap_drop ALL + 2 задокументовані cap_add, no-new-privileges, pids_limit, mem_limit через `*_MEM_LIMIT`); Caddy: CSP (`CSP_MODE`, стартує Report-Only, лише на SPA), HSTS, X-Frame-Options, Permissions-Policy, COOP; тест `tests/unit/test_deploy_compose.py`. ⏳ digest-піни базових образів — разом із Renovate (E-1.3); ⏳ `caddy validate`, `docker compose config` і перевірка на VPS; ⏳ перемкнути CSP в enforce після чистої консолі |
| E-1.9 | Покриття: прибрати `omit` для `backtest_runner`/`signal_strategy`/`instrument`, маркер `integration`; зробити крок `--cov` блокуючим | 🟠 | ✅ код 2026-09-24: `omit` для адаптерів рушія прибрано (`pyproject.toml`); у CI тести йдуть один раз під покриттям і блокують (`continue-on-error` прибрано), `coverage.xml` — артефакт; тест `test_ci_workflows.py` стежить за обома. Оцінка з наявного `.coverage` (до E-1.4): адаптери — ~735 інструкцій (~6% обсягу), тож TOTAL, імовірно, опиниться близько 80 %. ⏳ **виміряти** `uv run pytest --cov` і записати в `fail_under` фактичне значення, округлене вниз |
| — | **Запуск 8-тижневого paper-портфеля на VPS** після E-1.4 – E-1.7 | — | кожна сесія має маніфест, бекап і алерти |

### Хвиля 2 — підтримуваність (26.10 – 29.11.2026)

| ID | Задача | Зусилля | Definition of Done |
|---|---|:-:|---|
| E-2.1 | Розбити `app.py` на `APIRouter`-и (`research`, `catalog`, `ml`, `paper`, `settings`, `status`) + `create_app(settings)` | 🟠 | ✅ 2026-09-25: `app.py` 123 рядки (`create_app(cfg, root=, jobs=)` + middleware + lifespan); 8 роутерів у `api/routes/` (`status`, `catalog`, `research`, `library`, `ml`, `paper`, `live`, `settings`); стан процесу — `LabContext` (`api/context.py`, `app.state.lab`, залежність `Lab`); тіла запитів — `api/requests.py`. Тести більше не патчать модуль: `test_api_app_factory.py` фіксує всі 51 маршрут (зникнення будь-якого валить тест), окремі app не ділять слоти джобів, токен і роль беруться з переданих налаштувань. Прогін у пісочниці (FastAPI-шим поверх Starlette): 111 passed, ті самі 5 падінь середовища, що й до рефакторингу (немає `specs/strategies`, промптів, маркерів репо) |
| E-2.2 | `JobManager` замість глобальних `CURRENT_*_PROCESS`; стан джобів у SQLite (`data/jobs.sqlite`), усиновлення/прибирання сиріт при старті | 🟠 | ✅ 2026-09-25: `JobManager` (`api/jobs.py`) замість `CURRENT_*_PROCESS`/`JOBS_STARTING`/`global` (слот резервується в запиті, звільняється в `finally`); `JobStore` (`api/job_store.py`, `data/jobs.sqlite`, створюється при першому використанні): кожен старт і завершення записуються; при старті API `adopt()` усиновлює живу дитину попереднього процесу (перевірка pid **і** командного рядка з `/proc`, зомбі = завершений), а зниклу записує як `lost` — `/api/status` показує `last_run.status`, а не «idle». Сироту ніколи не вбиває: pid, що тепер належить іншій програмі, не чіпається. Тести `test_api_job_store.py` на справжніх підпроцесах (усиновлення + блок другого запуску + скасування, втрачений, чужий pid) |
| E-2.3 | Pydantic response-моделі для всіх маршрутів → `openapi-typescript` → `frontend/src/services/api.gen.ts`; CI перевіряє дрейф | 🟠 | 🟡 крок 1 2026-09-25: `api/responses.py` (Pydantic, `extra="allow"` — жодне поле не губиться) для `/healthz`, `/api/status` (+`JobState` з `adopted`/`last_run`), `/api/catalogs`, логу ingest і всіх start/cancel джобів (`ActionResult`, `response_model_exclude_none` — формат відповіді не змінився); `scripts/gen_api_types.py` генерує `frontend/src/services/api.gen.ts` із JSON-схем моделей (відповіді — serialization mode, запити — validation mode). Замість `openapi-typescript`: без Node і npm-залежності, а перевірка дрейфу — у `pytest` (`test_api_types.py`: файл актуальний + кожна модель збігається з тим, що маршрут реально шле). ✅ крок 2 2026-09-25: + `/api/reports`, `/api/ml/models`; `api.ts` імпортує з `api.gen.ts` і реекспортує `StatusResponse`, `JobState`, `JobKey`, `StressSliceInfo`, `ActionResult`, `CatalogSummary`, `CatalogsResponse`, `ReportItem`, `MlModelInfo`, `JobLogResponse` — 9 ручних інтерфейсів видалено, `tsc` чистий. ⏳ крок 3: маршрути, що віддають дані з файлів (research log/summary, ML/paper summary, live state, sessions, command center, journal, hypotheses, strategies, catalog detail, data health) — спершу нормалізувати на сервері, бо строга модель на неперевірених даних дала б 500 |
| E-2.4 | vitest + Testing Library для `lib/*` і ключових компонентів; Playwright-smoke (дашборд відкривається, сесії видно, WS підключився) проти `uvicorn` з синтетикою | 🟠 | обидва в CI |
| E-2.5 | Розбити `ResearchLab`, `LiveTradingTerminal`, `CatalogManager`; TanStack Query для запитів/polling | 🔴 | жоден компонент > 15 КБ; polling зупиняється на прихованій вкладці |
| E-2.6 | «Золотий» регресійний бектест: фіксований синтетичний датасет + фіксований seed → знімок ключових метрик у репо; CI порівнює | 🟢 | ✅ код 2026-09-25: `scripts/golden_backtest.py` (5 випадків: regime, ema, adaptive_ema, vpin_momentum на 3000 синтетичних барах + walk-forward regime 2 фолди; налаштування лише з дефолтів коду — ні `.env`, ні змінних оболонки), знімок `tests/golden/backtests.json` з версією NautilusTrader, `tests/integration/test_golden_backtest.py` друкує кожне змінене число. ⏳ **створити знімок** `--update` локально й закомітити (у пісочниці без NautilusTrader не запускалось) |
| E-2.7 | Property-based тести (Hypothesis) для `marking`, `position_plan`, `walk_forward`, `risk`, `quantiles` | 🟠 | ✅ код 2026-09-25: `tests/unit/test_domain_properties.py` — 17 властивостей: equity = баланс + Σ відкритого PnL (лоти без марки = 0, порядок не важить, шорт дзеркалить лонг); план позиції завжди доводить до цілі сигналу, а вихід не залежить від дозволу на вхід; квантиль у [min, max], монотонний за p, зсувається разом із вибіркою; walk-forward: IS завжди раніше OOS, ембарго рівно `embargo_bars` барів, OOS-блоки стикуються, останній бар у звіті; розмір позиції ≤ ризик-частки й ≤ 1x, кратний кроку, максимальний, монотонний за equity; дозволений вхід усередині всіх запобіжників. Мутаційна перевірка: 4 внесені помилки (ембарго −1, без обмеження 1x, лоти без марки, зсув індексу квантиля) — усі впіймані. `hypothesis` у `dev`. ⏳ `uv lock` (інакше в CI `uv sync --frozen` не поставить пакет і тести тихо пропустяться) |
| E-2.8 | Одна згенерована таблиця стану (`docs/STATUS.md` зі спек + `BACKTEST_WIRED_ROBOTS` + `GateCriteria`); `docs/21/22` посилаються на неї замість дублювання; ADR-тека для рішень | 🟠 | ✅ 2026-09-25: `scripts/gen_status.py` → `docs/STATUS.md` (роботи: статус spec, бектест, адаптер, tick VPIN/Hawkes, paper, live paper, вимір, причина; пороги `GateCriteria`; компоненти; розбіжності spec↔код). `tests/unit/test_status_doc.py` падає, якщо файл застарів або spec суперечить коду. `docs/21` §10 більше не називає порогів (фолди 4→`GateCriteria` 6, PBO 0.25→0.3 — ADR 0003); `docs/21` §1.1.1, `docs/22` §5.1/§7 позначено як історичні зрізи з посиланням на STATUS. ADR-тека `docs/adr/` (0001 ADR, 0002 таблиця стану, 0003 пороги з коду, 0004 типи з Pydantic, 0005 стан джобів у SQLite) |
| E-2.9 | Розширити ruff (`S`, `ASYNC`, `DTZ`, `PT`, `C4`, `PERF`, `BLE`); dev-інструменти → `[dependency-groups]` | 🟠 | `ruff check` зелений; CI використовує `--group dev` |

### Хвиля 3 — дослідження на надійному фундаменті (грудень 2026 – січень 2027)

| ID | Задача | Зусилля | Зв'язок із `docs/21` | Definition of Done |
|---|---|:-:|---|---|
| R-1 | Тест паритету бектест ↔ paper (replay записаного потоку) | 🔴 | передумова «етапу 6» (TradingNode) | розбіжність сигналів = 0, equity у межах допуску |
| R-2 | Попередня реєстрація + хеш у маніфесті | 🟠 | §10 DoD | `PROMOTE` неможливий без збігу хешу |
| R-3 | Глобальний лічильник спроб для DSR | 🟢 | §10 п.4 | DSR у звіті вказує `n_trials_total` |
| R-4 | Vol-matched buy & hold у всіх звітах і гейті | 🟢 | §1.2 | колонка в фолд-таблиці |
| R-7 → §4.1 | Funding cash-and-carry: перевірка нативної підтримки Nautilus → адаптер | 🔴 | §4.1, матриця #3 | `funding.yaml` виходить з `blocked`, є OOS-вимір |
| S5 | Вимір фракційного Келлі (вже в `docs/22`) | 🟠 | §3.2 | рядок у `research/journal.md` |
| E-3.1 | LLM-proposer: structured outputs, повтори, версія промпта/моделі в гіпотезі, евал-набір | 🟠 | §5 (заборона LLM у бектесті лишається) | метрика «частка пропозицій, що пройшли guard/гейт» по версіях |
| — | Етап 6: Nautilus `TradingNode` + sandbox execution для paper | 🔴 | `docs/26` | запускається лише після R-1 |

### Хвиля 4 — розширення (I квартал 2027, лише за результатами хвилі 3)

- R-5: рішення по кожній paper-сесії за критерієм виходу (8 тижнів / 30 угод / tracking-error).
- R-6: емпірична модель витрат із власних тіків/книги.
- Далі — пункти `docs/21` у їхньому порядку: 5m/15m (#5), Калман (#4), ансамбль (#10, лише якщо ≥ 2 роботи пройшли гейт), Johansen (#14). GLFT і DRL лишаються заблокованими правилами §9.

---

## 6. Що свідомо не пропонується

| Не робимо | Чому |
|---|---|
| Kubernetes, мікросервіси, черги (Celery/Kafka) | один VPS, один процес — SQLite + `JobManager` покривають потребу |
| Заміна mypy на `ty` | `ty` у beta; можна додати як швидку додаткову перевірку, не замість |
| Переписування фронтенду на інший фреймворк | стек уже актуальний; бракує строгості й тестів, а не фреймворку |
| Live-адаптер | `docs/21` §9.1 — лишається fail-closed |
| Підняття `--trials` чи нові роботи до E-1.4/R-1 | без маніфесту й паритету нові результати неперевірні |

---

## 7. Метрики успіху E-серії

| Метрика | Зараз | Ціль після хвилі 2 |
|---|---|---|
| Покриття (з адаптерами, блокуюче) | 80.50 % без адаптерів, не блокує | фактичне з адаптерами, блокує, не падає |
| TS strict | лише як типове значення TS 6 | явно + `noUncheckedIndexedAccess` ✅ |
| Фронтенд-тести | 0 | vitest + Playwright smoke у CI |
| Прогонів із маніфестом | 0 % | 100 % |
| Час виявлення завислого фіду | невідомо (немає моніторингу) | ≤ 1 бар |
| Таблиць стану, які треба оновлювати вручну | 5–7 | 1 згенерована |
| Розмір `app.py` | 1549 рядків | < 200 |
