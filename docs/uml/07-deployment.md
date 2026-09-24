# Deployment / context: що крутиться і куди ходить дані

Це **дослідницька пісочниця**, не торговий кластер. Немає колокації і live-брокера:
адаптера виконання не існує, `lab live` завжди fail closed.

Два способи працювати з одним і тим самим кодом: CLI `lab` на робочій станції і
веб-дашборд (FastAPI + React), який запускає ті самі use cases. Другий зазвичай живе
на VPS, де тримають живий paper-термінал 24/7 ([26-deploy-vps.md](../26-deploy-vps.md)).

```mermaid
flowchart TB
    subgraph workstation["Робоча станція дослідника"]
        cli["процес: uv run lab"]
        env["файл .env локальний"]
        src["пакет nautilus_lab"]
        catalog["тека catalog/ Parquet"]
        reports["reports/: tearsheet, paper-журнали"]
        tests["pytest без мережі в unit"]
    end

    subgraph vps["VPS (опційно): Docker Compose + Caddy"]
        caddy["Caddy: TLS + reverse proxy"]
        web["статика React-бандла"]
        api["процес: uvicorn api.app:app<br/>LAB_ROLE=paper"]
        sessions["data/paper/sessions/&lt;id&gt;.jsonl<br/>+ файл портфеля"]
    end

    subgraph optional["Опційні extras"]
        optuna["optuna TPE"]
        lgbm["LightGBM"]
        plotly["plotly tearsheet"]
        httpx["httpx алерти"]
        arch["arch EGARCH"]
    end

    subgraph external["Зовнішній світ"]
        binance["Binance публічний REST<br/>klines / aggTrades / funding"]
        ws["Binance публічний WebSocket<br/>закриті бари / тіки / L2"]
        telegram["Telegram Bot API"]
        webhook["довільний Webhook"]
        browser["Браузер дослідника"]
        llm["LLM API (лише lab propose)"]
    end

    cli --> src
    cli --> env
    src --> catalog
    src --> reports
    src --> optuna
    src --> lgbm
    src --> plotly
    src -.->|"лише ingest"| binance
    src -.->|"лише --notify"| telegram
    src -.->|"лише --notify"| webhook
    tests --> src

    browser -->|"HTTP + WebSocket"| caddy
    caddy --> web
    caddy --> api
    api --> src
    api --> catalog
    api --> sessions
    api -.->|"лише закриті бари"| ws
    api -.->|"лише POST /api/propose"| llm
```

Пунктир — мережа. Типовий `lab research` після ingest **не ходить в інтернет**: читає каталог.
WebSocket тут **лише читає публічні потоки** — ордерів через нього не надсилають.

## Контекст системи (C4-подібний)

```mermaid
flowchart LR
    user["Дослідник"] --> lab["nautilus-lab CLI"]
    user --> dash["Веб-дашборд (React)"]
    dash --> apisrv["FastAPI api.app"]
    apisrv --> lab
    apisrv --> livepaper["Живий paper: сесії, портфель"]
    lab --> nt["NautilusTrader BacktestEngine"]
    livepaper --> nt
    lab --> fs["Локальний Parquet catalog"]
    lab --> binance["Binance public market data"]
    lab --> notify["Alerts Telegram/Webhook"]
    nt --> sim["Venue SIM<br/>NETTING, MARGIN, 1x<br/>FillModel slippage 0.25<br/>LatencyModel 50 ms"]
```

Інструменти симуляції: `ETH/USDT.SIM`, `BTC/USDT.SIM`, `ETHUSDT-PERP.SIM`.
Живий paper використовує той самий рушій і ту саму модель філів, що й бектест, але
рахунок віртуальний — див. [24-paper-treydynh.md](../24-paper-treydynh.md).

## Потік даних (pipeline)

```mermaid
flowchart LR
    kline["Binance kline JSON"] --> parse["parse_binance_kline"]
    parse --> bar["OhlcvBar Decimal UTC"]
    bar --> validate["validate_bar"]
    validate --> parquet["ParquetDataCatalog"]
    parquet --> feed["ResearchBarFeed.load"]
    synth["synthetic_ohlcv"] --> feed
    feed --> convert["to_engine_bars"]
    convert --> engine["BacktestEngine"]
    engine --> native["нативний Bar"]
    native --> adapter["SignalRobot / SpreadRobot"]
    adapter --> domainBar["знову OhlcvBar"]
    domainBar --> signal["Signal / SpreadSignal"]
    signal --> risk["risk size + breakers"]
    risk --> order["Market order SIM"]
    order --> fills["fills / positions"]
    fills --> metrics["compute_metrics"]
    metrics --> report["BacktestReport / консоль / tearsheet"]
```

Гроші скрізь `Decimal`. Індикатори бачать лише **закритий** бар (`RollingWindow.prior()`),
щоб не було look-ahead.

## Чого немає в деплої (навмисно)

- ключів API біржі в git / обов'язковому `.env`;
- процесу live-виконання й адаптера виконання;
- спільної БД — стан дослідження в каталозі, звітах і JSONL-журналах сесій;
- другого рушія для paper: і бектест, і живий paper ідуть через той самий
  Nautilus `BacktestEngine`;
- автоматичного деплою — CI перевіряє якість (`.github/workflows/ci.yml`), а вивантаження
  на VPS завжди ручне (`scripts/deploy_vps.sh`, `scripts/pull_vps.sh`).

Що **є**, але легко пропустити: окремий API-сервер (`uvicorn nautilus_lab.api.app:app`),
публічні WebSocket-потоки лише для читання даних, і роль `LAB_ROLE=paper`, яка на
розгорнутому сервері забороняє все, крім керування живими paper-сесіями
(`api/security.py`, `PAPER_ROLE_WRITES`).
