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
 data/vps/  ◀──scripts/pull_vps.sh (rsync)───── data/paper/live_events.jsonl   catalog/data/agg_trade/
     │
     └─ scripts/live_paper_report.py, ноутбуки, lab research --catalog data/vps/catalog
```

---

## 1. Що змінилося в коді (і чому без цього VPS не мав сенсу)

| Було | Стало | Де |
|---|---|---|
| Живий paper-сеанс існував лише в пам'яті процесу API: рестарт = втрата позиції, угод, кривої | Кожна угода й кожен закритий бар дописуються в append-only JSONL; незавершений сеанс **відновлюється** при старті API | `infrastructure/live_paper_journal.py`, `api/paper_streamer.py` |
| Після рестарту сеанс сам не запускався | `LIVE_PAPER_AUTOSTART=true` запускає сеанс, якщо відновлювати нічого | `api/live_paper_boot.py` |
| Стоп, зачеплений поки процес лежав, просто «пропускався» | Бари, що закрились під час простою, один раз перевіряються проти стопа/тейку; філ — за рівнем стопа й часом того бару | `LivePaperSessionManager._settle_missed_bars` |
| API на сервері вмів запускати research, міняти `.env`, викликати LLM | `LAB_ROLE=paper`: читання й керування живим терміналом дозволені, решта змінювальних викликів — 403 | `api/security.py` |
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
nano deploy/.env          # BIND_ADDR=100.x.y.z, API_TOKEN=..., TICK_SYMBOLS=ETHUSDT
mkdir -p data reports catalog && sudo chown -R 1000:1000 data reports catalog
```

Два файли — навмисно:

| Файл | Хто читає | Що там |
|---|---|---|
| `~/nautilus-lab/.env` | застосунок (`Settings`) | `LAB_ROLE=paper`, журнал, автостарт, **заморожені параметри робота й ризику**, токен, дозволені origin |
| `~/nautilus-lab/deploy/.env` | `docker compose` | адреса прив'язки, адреса сайту, токен для збірки фронтенду, профіль збирача |

`.env` з робочої станції на сервер **не копіюйте**: там LLM-ключ і все, що серверу не потрібно.

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

Скрипт робить `git archive HEAD | ssh ... tar -x`, пише ревізію в
`DEPLOYED_REVISION`, і виконує `docker compose up -d --build`. API перезапускається,
знаходить незавершений сеанс у журналі і продовжує його (у лозі:
`live paper boot: resumed`).

Корисне на сервері:

```bash
cd ~/nautilus-lab
docker compose -f deploy/docker-compose.yml ps
docker compose -f deploy/docker-compose.yml logs -f api        # торгівля
docker compose -f deploy/docker-compose.yml logs -f collector  # тіки
tail -n 3 data/paper/live_events.jsonl                         # останні події
```

Дашборд: `http://100.x.y.z` з будь-якого вашого пристрою в Tailscale. На сервері
відкривається одразу вкладка Paper з живим терміналом; жовтий банер нагадує, що
research тут вимкнено.

### Варіант із публічним доменом

DNS `A lab.example.com → IP VPS`, потім у `deploy/.env`: `BIND_ADDR=0.0.0.0`,
`SITE_ADDRESS=lab.example.com`; у `.env`: `API_ALLOWED_ORIGINS=https://lab.example.com`;
`ufw allow 80,443/tcp`. Caddy сам отримає HTTPS-сертифікат. Обов'язково увімкніть
`basic_auth` у `deploy/Caddyfile` (інструкція в коментарі): токен вшитий у JS-бандл і
захищає API від чужих сторінок, а не від людини, яка відкрила ваш дашборд.

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
| сесія з таким `name` працює | нічого; якщо параметри у файлі змінились — пише в лог, але не застосовує |
| сесію з таким `name` зупинили кнопкою Stop | не перезапускає (перейменуйте, щоб почати знову) |
| такого `name` ще не було | запускає |
| запис прибрали з файлу | сесія працює далі, поки її не зупинять у дашборді |

Сесія з роботом `hold` — це бенчмарк buy & hold. Інші сесії на тому самому
symbol+interval порівнюються з нею: колонка «vs hold» у дашборді та рядок
`vs hold` у звіті.

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

У ноутбуці:

```python
import pandas as pd
ev = pd.read_json("data/vps/paper/live_events.jsonl", lines=True)
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

Усе цінне — три теки: `data/`, `catalog/`, `reports/`. `pull_vps.sh` і є бекапом
(rsync копіює тільки зміни). Для надійності — cron на станції:

```cron
0 * * * *  cd ~/PycharmProjects/nautilus-lab && VPS=lab@100.101.102.103 scripts/pull_vps.sh >/dev/null 2>&1
```

## 8. Якщо щось не так

| Симптом | Причина / що робити |
|---|---|
| Дашборд: `origin ... is not allowed` | `API_ALLOWED_ORIGINS` у `.env` не збігається з адресою в браузері; після зміни — `docker compose ... restart api` |
| Дашборд: `missing or invalid API token` | `API_TOKEN` у `.env` і `deploy/.env` різні; змінили токен — треба `up -d --build` (він вшивається в бандл) |
| `... is disabled on this server (LAB_ROLE=paper)` | Так і задумано: research/ingest/ML — на станції |
| У лозі `live paper boot: resume_failed` | Журнал посилається на робота, якого термінал не вміє будувати; Start нового сеансу з UI |
| Контейнер `api` не стартує, `unknown LAB_ROLE` | Опечатка в `LAB_ROLE` (дозволено `full`, `paper`) — навмисно fail closed |
| `.env` виявився текою | `docker compose up` запустили до створення `.env`; `rmdir .env && cp deploy/vps.env.example .env` |
| Permission denied у `data/` | `sudo chown -R 1000:1000 data reports catalog` |
