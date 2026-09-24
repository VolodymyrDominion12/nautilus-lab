# 26. Деплой на VPS: paper-трейдинг 24/7, дашборд, дослідження локально

> **Навіщо.** Ноутбук засинає, а paper-сесія, яка переривається щоночі, нічого не
> доводить. VPS тримає **живий paper-термінал** і **збирач тіків** цілодобово, а
> дослідження (research, walk-forward, PBO, ML) лишається на робочій станції, де
> дані й обчислення. Код іде в один бік (станція → VPS), дані — у другий (VPS → станція).

```
 робоча станція                                 VPS (LAB_ROLE=paper)
 ───────────────                                ─────────────────────────────────────
 git commit ──scripts/deploy_vps.sh──────────▶  docker compose: api │ web (Caddy) │ collector
                                                   │                 │               │
                                                   │ live paper      │ дашборд +     │ live aggTrades
                                                   ▼ (журнал)        │ /api proxy    ▼
 data/vps/  ◀──scripts/pull_vps.sh (rsync)───── data/paper/sessions/<id>.jsonl  catalog/data/agg_trade/
     │
     └─ scripts/live_paper_report.py, ноутбуки, lab research --catalog data/vps/catalog
```

---

## 1. Що змінилося в коді (і чому без цього VPS не мав сенсу)

| Було | Стало | Де |
|---|---|---|
| Живий paper-сеанс існував лише в пам'яті процесу API: рестарт = втрата позиції, угод, кривої | Кожна угода й кожен закритий бар дописуються в append-only JSONL; незавершений сеанс **відновлюється** при старті API | `infrastructure/live_paper_journal.py`, `api/paper_streamer.py` |
| Після рестарту сеанс сам не запускався | `LIVE_PAPER_AUTOSTART=true` запускає сеанс, якщо відновлювати нічого; заданий `LIVE_PAPER_PORTFOLIO` заміняє автостарт списком сесій | `api/live_paper_boot.py` |
| Стоп, зачеплений поки процес лежав, просто «пропускався» | Бари, що закрились під час простою, один раз перевіряються проти стопа/тейку; філ — за рівнем стопа й часом того бару | `LivePaperSessionManager._settle_missed_bars` |
| API на сервері вмів запускати research, міняти `.env`, викликати LLM | `LAB_ROLE=paper`: читання й керування живим терміналом дозволені (точний allow-list — у §4), решта змінювальних викликів — 403 | `api/security.py` |
| Фронтенд знав лише `http://localhost:8000` | `VITE_API_URL=same-origin`: бандл звертається до хоста, з якого завантажений | `frontend/src/config.ts` |

Правила журналу:

* **Зупинений людиною** сеанс (кнопка Stop / `POST /api/paper/live/stop`) — остаточний,
  після рестарту не відновлюється. Сеанс, перерваний SIGTERM/крашем/ребутом, —
  відновлюється. Тому деплой **не** зупиняє торгівлю.
* Відновлений сеанс торгує з **тією конфігурацією, з якою стартував** (вона в журналі),
  а не з тим, що зараз у `.env`. Щоб змінити параметри — Stop, потім Start (новий сеанс,
  новий `session_id`). Один журнал ніколи не змішує двох роботів.
* Відновлення має пріоритет над автостартом: рестарт продовжує поточний журнал, а не
  відкриває поруч другий.
* Обірваний останній рядок (процес помер посеред запису) пропускається, а не валить старт.

Що **не** змінилося і про що варто пам'ятати:

* Живий термінал — це окремий від бектесту matcher (аудит 2026-09-23, P1). Його числа
  не можна прямо порівнювати з `lab research`/`lab paper`. Перенесення на Nautilus
  `TradingNode` (Binance data client + sandbox execution) — наступний етап.
* Запобіжник `MAX_DRAWDOWN` у терміналі не має cooldown: після спрацювання сеанс
  більше не відкриває позицій (виходи працюють). Для тижневого прогону це очікувана
  поведінка «fail closed», але її видно в `risk_refusals`.
* Один процес API = один сеанс = один робот. Тому uvicorn завжди з `--workers 1`.

---

## 2. Який VPS

* **Регіон — ЄС** (Німеччина/Фінляндія/Нідерланди). Binance блокує IP зі США.
* 2 vCPU / 4 GB RAM / 40 GB диска достатньо: сервер не рахує research. Тіки ETHUSDT —
  ~10–20 MB на добу, журнал paper — кілобайти на добу.
* Ubuntu 24.04 LTS.

## 3. Перше налаштування сервера (один раз)

```bash
# на VPS, під root
adduser lab && usermod -aG sudo lab
# SSH-ключ з робочої станції:  ssh-copy-id lab@<IP>
apt update && apt -y upgrade
curl -fsSL https://get.docker.com | sh
usermod -aG docker lab

# Tailscale: дашборд буде видно лише з ваших пристроїв
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up            # відкрийте посилання, увійдіть
tailscale ip -4         # 100.x.y.z — запам'ятайте

# базовий фаєрвол для SSH (Docker-порти він НЕ закриває — див. BIND_ADDR нижче)
ufw allow OpenSSH && ufw enable
```

> **Важливо про Docker і ufw.** Docker публікує порти в обхід правил ufw. Тому
> «фаєрвол» дашборда — це `BIND_ADDR` у `deploy/.env`: за замовчуванням `127.0.0.1`
> (ззовні недоступно), для Tailscale — ваш `100.x.y.z`, для публічного домену — `0.0.0.0`.

## 4. Конфігурація на сервері

```bash
# на VPS, під lab
mkdir -p ~/nautilus-lab && cd ~/nautilus-lab
# перший раз код можна залити тим самим скриптом (крок 5) — він зупиниться на
# відсутньому .env і підкаже; або скопіюйте шаблони вручну після першого deploy:
cp deploy/vps.env.example .env
cp deploy/compose.env.example deploy/.env
openssl rand -hex 32      # -> API_TOKEN в ОБОХ файлах
nano .env                 # API_ALLOWED_ORIGINS=http://100.x.y.z, параметри робота
nano deploy/.env          # BIND_ADDR=100.x.y.z, API_TOKEN=..., COMPOSE_PROFILES=collector,
                          # TICK_SYMBOLS=ETHUSDT, TICK_WINDOW_MINUTES=60
# теки створює і сам deploy_vps.sh; контейнер за замовчуванням збирається з uid 1001
# (типовий uid користувача lab на VPS; налаштовується через APP_UID/APP_GID у deploy/.env)
mkdir -p data reports catalog && sudo chown -R $(id -u):$(id -g) data reports catalog
```

Два файли — навмисно:

| Файл | Хто читає | Що там |
|---|---|---|
| `~/nautilus-lab/.env` | застосунок (`Settings`; у контейнер змонтований як `/app/.env:ro`) | `LAB_ROLE=paper`, `LIVE_PAPER_*` — журнал, автостарт/портфель, `LIVE_PAPER_MAX_SESSIONS`, `LIVE_PAPER_MAX_FEEDS`, **заморожені параметри робота й ризику**, `API_ALLOWED_ORIGINS`, `API_TOKEN`, `CATALOG_PATH` |
| `~/nautilus-lab/deploy/.env` | `docker compose` (не застосунок) | `BIND_ADDR`, `SITE_ADDRESS`, `API_TOKEN` (той самий, що в `.env`: він вшивається в бандл дашборда), `DASHBOARD_AUTH`/`BASIC_AUTH_USER`/`BASIC_AUTH_HASH` (замок для публічного доступу), `COMPOSE_PROFILES`, `TICK_SYMBOLS`, `TICK_WINDOW_MINUTES` |

`.env` з робочої станції на сервер **не копіюйте**: там LLM-ключ і все, що серверу не потрібно.

Що взагалі можна **змінити** на сервері з `LAB_ROLE=paper` — це рівно набір
`PAPER_ROLE_WRITES` (`src/nautilus_lab/api/security.py`); усе інше змінювальне під
`/api` дістає 403 з текстом `... is disabled on this server (LAB_ROLE=paper)`:

```text
POST /api/paper/live/start             POST /api/paper/sessions
POST /api/paper/live/stop              POST /api/paper/sessions/<id або name>/stop
POST /api/paper/live/close-position    POST /api/paper/sessions/<id або name>/pause
POST /api/paper/live/update-stops      POST /api/paper/sessions/<id або name>/resume
                                       POST /api/paper/sessions/<id або name>/close-position
                                       POST /api/paper/sessions/<id або name>/update-stops
```

`GET`/`HEAD`/`OPTIONS`, а також будь-що поза `/api` проходять завжди — тому дашборд,
`/docs` і `/static_reports/*` на такому сервері працюють, а вся решта (`POST /api/paper/run`,
`PUT /api/settings`, research, ingest, ML, `propose`) — ні.

`API_ALLOWED_ORIGINS` має **точно** збігатися з тим, що в адресному рядку браузера:
`http://100.101.102.103` (порт 80 не пишеться) або `https://lab.example.com`.

Параметри робота (`ER_PERIOD`, `RISK_PER_TRADE`, `STOP_PCT`, комісії...) переносьте з
того research-прогону, який хочете відрепетирувати. Змінюються вони тільки через
новий сеанс (Stop → Start або перезапуск із порожнім журналом).

## 5. Деплой і оновлення (з робочої станції)

```bash
git add -A && git commit -m "..."          # деплоїться лише закомічений HEAD
VPS=lab@100.101.102.103 scripts/deploy_vps.sh
```

Скрипт вимагає `VPS=user@host` і **не** поїде з незакоміченими змінами
(`git status --porcelain`; обійти — `ALLOW_DIRTY=1`, тоді поїде поточний HEAD).
Далі він:

1. `git archive HEAD | ssh $VPS tar -x` у `~/nautilus-lab` (інша тека — `REMOTE_DIR=...`):
   ні локальних правок, ні `.env`, ні каталогу;
2. пише ревізію в `DEPLOYED_REVISION` і передає повний SHA в образ як `LAB_REVISION`
   (build-arg): у контейнері немає `.git`, а кожна paper-сесія записує в журнал, яким
   кодом її ведуть (`provenance` у `session_start`/`session_resume`, docs/27 E-1.4);
3. створює `data/`, `reports/`, `catalog/` і **зупиняється**, якщо на сервері немає
   `.env` або `deploy/.env` — у повідомленні вказано, який `cp` зробити (сам він
   шаблони не копіює, це крок 4);
4. виконує `docker compose -f deploy/docker-compose.yml up -d --build --remove-orphans`.

Торгівля при цьому не зупиняється: API перезапускається, знаходить незавершені сесії
в журналах і продовжує їх (у лозі `live paper boot: resumed <name> (<session_id>)`),
а оголошені в `deploy/paper_portfolio.yaml` піднімає заново
(`live paper boot: started <name> (<session_id>)`).

CI нікуди не деплоїть: `.github/workflows/ci.yml` — це лише гейти якості (ruff, mypy,
валідатор спек, pytest, smoke-бектест, прогон ноутбука), вивантаження на VPS завжди ручне.

Корисне на сервері:

```bash
cd ~/nautilus-lab
docker compose -f deploy/docker-compose.yml ps
docker compose -f deploy/docker-compose.yml logs -f api        # торгівля
docker compose -f deploy/docker-compose.yml logs -f collector  # тіки
docker compose -f deploy/docker-compose.yml logs -f web        # Caddy: проксі й TLS
tail -q -n 3 data/paper/sessions/*.jsonl                       # останні події (файл на сесію)
```

Дашборд: `http://100.x.y.z` з будь-якого вашого пристрою в Tailscale. На сервері
відкривається одразу вкладка Paper з живим терміналом; жовтий банер нагадує, що
research тут вимкнено.

Що куди відкрито й проксіюється (`deploy/docker-compose.yml` + `deploy/Caddyfile`):

* порти назовні публікує **лише** `web` (Caddy): `${BIND_ADDR}:80:80` і
  `${BIND_ADDR}:443:443`, де `BIND_ADDR` типово `127.0.0.1`;
* `api` не публікується взагалі — у нього тільки `expose: 8000`, і дістатись до нього
  можна лише через Caddy по compose-мережі;
* Caddy віддає `/srv` (SPA з `try_files {path} /index.html`) і проксіює на `api:8000`
  шляхи `/api/*`, `/static_reports/*`, `/static_hypotheses/*`, `/docs`, `/openapi.json`.
  `/api/*` покриває і WebSocket `/api/paper/live-stream` — окремих правил для нього не
  треба, `reverse_proxy` проксіює його тим самим `handle`. Токен до WebSocket їде в
  `?token=`, бо браузер не вміє ставити заголовки на handshake; дашборд робить це сам.

### Варіант із публічним доменом

DNS `A lab.example.com → IP VPS`, потім у `deploy/.env`: `BIND_ADDR=0.0.0.0`,
`SITE_ADDRESS=lab.example.com`; у `.env`: `API_ALLOWED_ORIGINS=https://lab.example.com`;
`ufw allow 80,443/tcp`. Caddy сам отримає HTTPS-сертифікат.

Замок обов'язковий: токен вшитий у JS-бандл і захищає API від чужих сторінок, а не від
людини, яка відкрила ваш дашборд. У `deploy/.env`:

```bash
docker run --rm caddy:2-alpine caddy hash-password   # введіть пароль -> $2a$14$...
# deploy/.env — хеш ОБОВ'ЯЗКОВО в одинарних лапках: у ньому є `$`, який compose розкрив би
DASHBOARD_AUTH=on
BASIC_AUTH_USER=volodymyr
BASIC_AUTH_HASH='$2a$14$...'
```

`deploy_vps.sh` перед `docker compose up` запускає `deploy/check_exposure.sh`: якщо
`BIND_ADDR` не `127.*` і не адреса Tailscale (`100.64.0.0/10`), а `DASHBOARD_AUTH=off`,
деплой зупиняється. Свідомо відкритий дашборд — лише з `ALLOW_OPEN_DASHBOARD=1`.

## 5a. Кілька роботів одночасно

Сервер тримає до `LIVE_PAPER_MAX_SESSIONS` (8) сесій. У кожної свій робот, свій
віртуальний рахунок із запобіжниками і свій журнал `data/paper/sessions/<id>.jsonl`.
Сесії на одному symbol+interval читають **один** сокет Binance (`api/market_feed.py`),
тож бачать ті самі бари. Різних ринків одночасно може бути до `LIVE_PAPER_MAX_FEEDS` (5).

Що торгує сервер, задає файл `deploy/paper_portfolio.yaml` (у git, розгортається
разом із кодом). Щоб він діяв, у `.env` сервера потрібен рядок
`LIVE_PAPER_PORTFOLIO=deploy/paper_portfolio.yaml`. На кожному старті API файл
звіряється з журналами **за іменем** сесії:

| Ситуація | Що робить сервер |
| --- | --- |
| сесія з таким `name` працює | нічого; якщо у файлі змінились `robot`/`symbol`/`interval` — пише в лог, але не застосовує. Решта полів (`risk_per_trade`, `stop_pct`, `take_profit_multiple`, `starting_equity`) не порівнюється взагалі: нові параметри = нова назва |
| сесію з таким `name` зупинили кнопкою Stop | не перезапускає (перейменуйте, щоб почати знову) |
| такого `name` ще не було | запускає |
| запис прибрали з файлу | сесія працює далі, поки її не зупинять у дашборді |

Сесія з роботом `hold` — це бенчмарк buy & hold. Інші сесії на тому самому
symbol+interval порівнюються з нею: колонка «vs hold» у дашборді та рядок
`vs hold` у звіті.

Живих роботів рівно шість (`LIVE_PAPER_ROBOTS` у `api/paper_streamer.py`):
`regime`, `ema`, `adaptive_ema`, `vpin_momentum`, `formulaic_lgbm`, `hold`.
Невідомий робот у файлі — це помилка завантаження портфеля
(`<name>: robot '<x>' is not available live (...)`), а не тиха підстановка іншого;
у лозі це видно як `live paper boot: portfolio error: ...`, і тоді оголошений
портфель не піднімається взагалі (відновлені з журналів сесії при цьому працюють).

Дашборд, вкладка **Paper**: таблиця сесій (equity, дохідність, «vs hold»,
позиція, угоди, max DD, останній бар) і кнопки Pause (стоп нових входів;
виходи й стопи працюють) та Stop. Клік по рядку відкриває сесію в терміналі.
«New session» — форма для разового експерименту з назвою та гіпотезою.

API (для скриптів): `GET /api/paper/sessions`, `POST /api/paper/sessions`,
`POST /api/paper/sessions/<id або name>/{stop,pause,resume,close-position,update-stops}`,
`GET /api/paper/portfolio`. Старі `/api/paper/live/*` працюють із першою активною сесією.

Сесія з однофайлового `live_events.jsonl` (до цієї версії) відновлюється як є,
отримує ім'я `regime-eth`, і файл портфеля її впізнає, а не запускає другу.

## 6. Дані на робочу станцію і аналіз

```bash
VPS=lab@100.101.102.103 scripts/pull_vps.sh
uv run python scripts/live_paper_report.py data/vps/paper
uv run python scripts/live_paper_report.py data/vps/paper --csv data/vps/csv
```

У кожному блоці звіту є рядок `code=<ревізія>`. Якщо сесію пережив деплой, там буде
`code=abc -> def  (code changed during the session)`: один ледджер вели дві версії коду,
і порівнювати його з бектестом однієї ревізії вже не можна без застереження.

`pull_vps.sh` кладе все під `data/vps/` (`paper/`, `catalog/data/`, `reports/`,
`DEPLOYED_REVISION`), і звіт читає теку рекурсивно: один журнал на сесію лежить у
`data/vps/paper/sessions/<session_id>.jsonl`, а однофайловий
`data/vps/paper/live_events.jsonl` лишається тільки від сесій до багатосесійної версії.
Каталог журналів задає `LIVE_PAPER_SESSIONS_DIR` (типово — `sessions/` поряд із
`LIVE_PAPER_JOURNAL`).

У ноутбуці:

```python
from pathlib import Path

import pandas as pd

journals = sorted(Path("data/vps/paper").rglob("*.jsonl"))
ev = pd.concat([pd.read_json(path, lines=True) for path in journals], ignore_index=True)
fills = pd.json_normalize(ev[ev.type == "fill"]["fill"])
equity = pd.json_normalize(ev[ev.type == "snapshot"]["equity_point"].dropna())
```

Тіки з сервера — окремий каталог, не поверх локального:
`lab research ... --catalog data/vps/catalog` або `scripts/measure_tick_vpin.py`.

Типи подій журналу:

| `type` | Коли | Ключові поля |
|---|---|---|
| `session_start` | Start / автостарт | `config` (повна заморожена конфігурація), `started_at` |
| `fill` | кожен філ | `fill`: `side`, `qty`, `price`, `fee`, `realized_pnl`, `reason` |
| `snapshot` | кожен закритий бар, філ, зміна стопів | `balance`, `equity`, `fees_paid`, `position`, `risk_refusals`, `equity_point` |
| `session_stop` | Stop людиною | `stopped_at` |

## 7. Резервні копії

Усе цінне — три теки: `data/`, `catalog/`, `reports/`. Журнал paper-сесії — єдиний
доказ 8 тижнів прогону, а зібрані тіки не можна докачати пізніше (REST-історії немає).
Тому копій дві, і жодна не лежить лише на VPS.

### 7.1. Автоматичний бекап поза сервером (restic)

Сервіс `backup` (`deploy/backup.sh`, образ `restic/restic`) щогодини робить знімок
`data/paper`, `reports`, `catalog/data/agg_trade`, `catalog/data/orderbook` у сховище
**не на цьому сервері** (S3/B2/R2, restic rest-server). Раз на добу — `forget --prune`
(типово 48 годинних, 30 денних, 26 тижневих знімків). Дані змонтовано лише для
читання. Журнали пишуться під час бекапу — у найгіршому разі останній рядок файлу
обірваний, а читач журналу такий рядок пропускає.

```bash
# deploy/.env на сервері
COMPOSE_PROFILES=collector,backup
RESTIC_REPOSITORY=b2:my-bucket:nautilus-lab
RESTIC_PASSWORD='довгий-випадковий-пароль'      # копія — у менеджері паролів, НЕ лише на VPS
B2_ACCOUNT_ID=...
B2_ACCOUNT_KEY=...
BACKUP_HEARTBEAT_URL=https://hc-ping.com/<uuid-2>   # необов'язково: алерт, коли бекапи зупинились
```

Перший запуск сам робить `restic init`. Без `RESTIC_REPOSITORY`/`RESTIC_PASSWORD` сервіс
завершується з поясненням у лозі (`docker compose logs backup`), а не мовчки.

**Відновлення — перевірте один раз одразу після налаштування** (бекап, з якого ніхто
не відновлювався, — це припущення, а не бекап):

```bash
cd ~/nautilus-lab
docker compose -f deploy/docker-compose.yml run --rm --entrypoint restic backup snapshots
docker compose -f deploy/docker-compose.yml run --rm -v "$PWD/restore:/restore" \
    --entrypoint restic backup restore latest --target /restore
ls restore/backup/data/paper/sessions/          # ті самі *.jsonl, що й у data/paper
uv run python scripts/live_paper_report.py restore/backup/data/paper   # на станції
```

### 7.2. Копія на робочій станції (`pull_vps.sh`)

`pull_vps.sh` теж є бекапом
(rsync копіює тільки зміни), але тягне не все підряд, а рівно те, що сервер продукує:
`data/paper/` → `data/vps/paper/`, `catalog/data/` → `data/vps/catalog/data/`,
`reports/` → `data/vps/reports/`, плюс `DEPLOYED_REVISION` сервера. Куди складати —
`DEST=data/vps`. Для надійності — cron на станції:

```cron
0 * * * *  cd ~/PycharmProjects/nautilus-lab && VPS=lab@100.101.102.103 scripts/pull_vps.sh >/dev/null 2>&1
```

## 7a. Моніторинг: здоров'я, алерти, метрики

Код — `src/nautilus_lab/api/health.py` (docs/27 E-1.5/E-1.6).

| Що | Де | Для кого |
|---|---|---|
| `GET /healthz` | без токена | «процес відповідає» — і все |
| `GET /readyz` | без токена, 200/503 | Docker health check і зовнішній монітор: чи сервер **працює** |
| `GET /api/metrics` | за токеном | Prometheus-текст: вік останнього повідомлення й закритого бару кожного фіду, реконекти, equity і помилки журналу кожної сесії |
| watchdog | у процесі API | повідомлення в Telegram/webhook при зміні стану |

`/readyz` повертає 503, коли:

* фід мовчить довше `LIVE_PAPER_FEED_TIMEOUT_SECONDS` (90 с; Binance шле оновлення
  свічки кожні ~2 с) — навіть якщо сокет формально «connected»;
* закритий бар запізнюється більше ніж на інтервал + `LIVE_PAPER_CLOSED_BAR_SLACK_SECONDS`;
* новий фід не дав жодного повідомлення за `LIVE_PAPER_FEED_GRACE_SECONDS`;
* остання спроба запису журналу запущеної сесії впала (повний диск, права) — у
  ледджері вже є дірка.

Сервер без сесій — `ready`: простій не є поломкою. Контейнер із 503 стає `unhealthy`
(`docker compose ps`); сам Docker його **не** перезапускає — сигнал іде через алерти.

Watchdog кожні `LIVE_PAPER_WATCHDOG_SECONDS` (30 с) перевіряє те саме й пише в
`TELEGRAM_*`/`ALERT_WEBHOOK_URL` лише **зміни**: «problem: …», а потім «recovered: …»;
довгий збій Binance — два повідомлення, а не двісті. Окремо — коли в сесії **вперше**
спрацьовує circuit breaker (денний збиток, max drawdown, VaR/CVaR), і одне повідомлення
на кожен старт процесу з ревізією коду та списком піднятих сесій. Збій самого
Telegram торгівлю не зупиняє.

Перевірити руками:

```bash
curl -s http://100.x.y.z/readyz | python3 -m json.tool      # через Caddy
docker compose -f deploy/docker-compose.yml ps                # STATUS: healthy / unhealthy
curl -s -H "X-Lab-Token: $API_TOKEN" http://100.x.y.z/api/metrics | head -30
```

**Коли мовчить сам VPS** (вимкнений, без мережі, процес мертвий), зсередини ніхто не
повідомить. Для цього — dead-man's switch: push-перевірка в зовнішньому сервісі
(healthchecks.io, Uptime Kuma «push», Cronitor) і її URL у `LIVE_PAPER_HEARTBEAT_URL`.
Watchdog звертається до нього раз на `LIVE_PAPER_HEARTBEAT_SECONDS` (300 с), **лише поки
`/readyz` зелений**; перестав — сервіс сам надсилає алерт (період 5 хв, grace 10 хв).
Необов'язковий `LIVE_PAPER_HEARTBEAT_FAIL_URL` (для healthchecks.io — той самий URL із
`/fail`) робить перевірку червоною одразу, а не після grace. Потрібен увімкнений
watchdog; URL маскується в API налаштувань, у лог не пишеться.

## 7b. Мінімальні права контейнерів

Кожен сервіс у `deploy/docker-compose.yml` отримує спільний блок `x-hardening`
(docs/27 E-1.8), і `tests/unit/test_deploy_compose.py` падає, якщо новий сервіс його
не має:

* **корінь файлової системи лише для читання** (`read_only`): записувати можна тільки в
  змонтовані `data/`, `reports/`, `catalog/`, іменовані томи й `/tmp` (tmpfs, 64 MB);
* **жодних capabilities** (`cap_drop: [ALL]`) і `no-new-privileges`. Повертаються лише
  дві, і тест знає, які: `NET_BIND_SERVICE` для Caddy (порти 80/443) і
  `DAC_READ_SEARCH` для restic (читати файли користувача застосунку, `APP_UID`);
* **ліміти** пам'яті й процесів: OOM або fork-бомба лишаються всередині свого
  контейнера, а не кладуть VPS разом із paper-сесіями. Типові значення — у
  `deploy/.env`: `API_MEM_LIMIT=1536m`, `COLLECTOR_MEM_LIMIT=768m`, `WEB_MEM_LIMIT=256m`,
  `BACKUP_MEM_LIMIT=1g`;
* порт публікує **тільки** Caddy, і тільки на `BIND_ADDR`.

Заголовки безпеки дашборда (Caddy): HSTS (браузер враховує лише через HTTPS),
`X-Frame-Options`, `Permissions-Policy`, `Cross-Origin-Opener-Policy` і
**Content-Security-Policy**. CSP стартує в режимі `Report-Only` (`CSP_MODE` у
`deploy/.env`): нічого не блокує, лише пише порушення в консоль браузера. Відкрийте
дашборд, пройдіть усі вкладки (Paper, Research, каталог, звіт у iframe) з відкритою
консоллю DevTools; якщо рядків `Content-Security-Policy` немає — поставте
`CSP_MODE=Content-Security-Policy` і передеплойте. На `/api/*` і звіти CSP не діє:
tearsheet — самодостатній HTML із вбудованими скриптами.

Перевірити на сервері:

```bash
docker inspect nautilus-lab-api-1 --format '{{.HostConfig.ReadonlyRootfs}} {{.HostConfig.CapDrop}} {{.HostConfig.Memory}}'
curl -sI http://<BIND_ADDR>/ | grep -iE "content-security|strict-transport|x-frame"
```

## 8. Якщо щось не так

| Симптом | Причина / що робити |
|---|---|
| Дашборд: `origin ... is not allowed` | `API_ALLOWED_ORIGINS` у `.env` не збігається з адресою в браузері; після зміни — `docker compose ... restart api` |
| Дашборд: `missing or invalid API token` | `API_TOKEN` у `.env` і `deploy/.env` різні; змінили токен — треба `up -d --build` (він вшивається в бандл) |
| `... is disabled on this server (LAB_ROLE=paper)` | Так і задумано: research/ingest/ML — на станції; дозволені write-и перелічені в §4 |
| У лозі `live paper boot: resume_failed` | Журнал посилається на робота, якого термінал не вміє будувати; Start нового сеансу з UI |
| У лозі `live paper boot: skipped <name>: stopped by a person` | Так і задумано: Stop остаточний, і портфель таку сесію не піднімає — перейменуйте, щоб почати знову |
| У лозі `live paper boot: portfolio error: ...` | `deploy/paper_portfolio.yaml` не розібрався (найчастіше — робот або ключ, яких термінал не знає): поки помилка не зникне, оголошений портфель не піднімається |
| Сервісу `collector` немає в `docker compose ps` | Він під профілем: потрібен `COMPOSE_PROFILES=collector` у `deploy/.env` |
| `deploy_vps.sh`: `Uncommitted changes. Commit first ...` | Скрипт везе лише закомічене: `git commit` — або свідомо `ALLOW_DIRTY=1 VPS=lab@<IP> scripts/deploy_vps.sh` |
| `deploy_vps.sh`: `missing .env on the server` / `missing deploy/.env` | Шаблони скопіюйте самі (крок 4) — скрипт лише підказує команду і виходить |
| Контейнер `api` не стартує, `unknown LAB_ROLE` | Опечатка в `LAB_ROLE` (дозволено `full`, `paper`) — навмисно fail closed |
| `.env` виявився текою | `docker compose up` запустили до створення `.env`; `rmdir .env && cp deploy/vps.env.example .env` |
| У лозі `Read-only file system: '/...'` | Бібліотека пише поза змонтованими теками. Якщо це кеш — спрямуйте його в `/tmp` змінною середовища сервісу (як `XDG_CACHE_HOME`); якщо дані — додайте том у `docker-compose.yml`. Знімати `read_only` не треба |
| Контейнер перезапускається, `docker inspect ... --format '{{.State.OOMKilled}}'` → `true` | Упирається в ліміт пам'яті: підніміть `API_MEM_LIMIT` (чи відповідний) у `deploy/.env` і `docker compose up -d` |
| `docker compose ps` показує `unhealthy` | `curl -s http://<BIND_ADDR>/readyz` — у полі `problems` написано, який фід мовчить або яка сесія не пише журнал; те саме прийшло в Telegram, якщо його налаштовано |
| Permission denied у `data/` (у лозі `Live paper journal write failed (...)`) | `data/` належить комусь іншому, ніж uid 1000 контейнера: `sudo chown -R 1000:1000 data reports catalog`. Поки це не зроблено, сесії йдуть у пам'ять, і після рестарту починаються з нуля |
| Контейнер `api` не стартує: `live paper journal is not writable` | Той самий chown `data/`. Навмисно fail closed: паперовий термінал без журналу — це не «деградований режим», а порожній ledger при здоровому дашборді. Режим спостереження без журналу — порожній `LIVE_PAPER_JOURNAL` |
| `deploy_vps.sh`: `check_exposure: refusing — BIND_ADDR=...` | Дашборд був би відкритий без замка: прив'яжіть до Tailscale (`BIND_ADDR=100.x.y.z`) або ввімкніть `DASHBOARD_AUTH=on` (розділ «Варіант із публічним доменом») |
