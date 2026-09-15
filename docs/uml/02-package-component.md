# Package / component: шари й залежності

Правило: **стрілки лише всередину**, до `domain`. Домен не імпортує Nautilus, `.env` і мережу.
Збірка адаптерів — лише в `interfaces/composition.py`.

```mermaid
flowchart TB
    subgraph interfaces["interfaces — точка входу"]
        cli["cli.py<br/>argparse lab"]
        composition["composition.py<br/>composition root"]
    end

    subgraph application["application — сценарії"]
        ingest_uc["IngestHistoricalBars"]
        research_uc["RunResearchBacktest"]
        wf_uc["RunWalkForward"]
        paper_uc["RunPaperResearch"]
        scan_uc["scan_triangular_opportunities"]
        risk_app["risk.py: size / stop / evaluate_entry"]
        grid["param_grid / OptunaParamOptimizer"]
        dtos["dtos: Request / Report / ports"]
    end

    subgraph domain["domain — чиста логіка"]
        types["OhlcvBar, Signal, RiskLimits"]
        robots["RegimeRouter, EmaCrossover, PairsTrading, ..."]
        methods["walk_forward, metrics, align"]
        ports["ports.Protocol: PublicBarFeed, BarCatalog, ..."]
    end

    subgraph infrastructure["infrastructure — адаптери"]
        settings["Settings .env"]
        klines["BinancePublicKlines"]
        catalog["NautilusParquetCatalog"]
        feed["ResearchBarFeed"]
        engine["NautilusResearchBacktest"]
        signal_robot["SignalRobot / SpreadRobot"]
        alerts["AlertNotifier"]
    end

    cli --> composition
    composition --> ingest_uc
    composition --> research_uc
    composition --> wf_uc
    composition --> settings
    composition --> klines
    composition --> catalog
    composition --> feed
    composition --> engine
    composition --> alerts

    ingest_uc --> ports
    research_uc --> dtos
    wf_uc --> dtos
    wf_uc --> grid
    research_uc --> robots
    wf_uc --> methods
    risk_app --> types
    paper_uc --> types
    scan_uc --> robots

    klines -.->|реалізує| ports
    catalog -.->|реалізує| ports
    feed -.->|реалізує| dtos
    engine -.->|реалізує| dtos
    signal_robot --> robots
    signal_robot --> risk_app
    settings --> types
```

Суцільні стрілки — виклик / імпорт. Пунктир — реалізація Protocol (adapter).

## Компоненти всередині інфраструктури Nautilus

```mermaid
flowchart LR
    feed["ResearchBarFeed"] --> catalog["ParquetDataCatalog"]
    feed --> synth["synthetic_bars / synthetic_pairs"]
    engine["NautilusResearchBacktest"] --> convert["bar_convert"]
    engine --> instrument["instrument SIM"]
    engine --> signal["SignalRobot"]
    engine --> spread["SpreadRobot"]
    engine --> nt["BacktestEngine<br/>venue SIM, fees, latency 50ms"]
    signal --> domain["domain robot.on_bar"]
    spread --> pairs["PairsTrading"]
```

`SignalRobot` і `SpreadRobot` — тонкі адаптери: нативний `Bar` → `OhlcvBar` → доменний сигнал
→ `evaluate_entry` / `size_position` → `submit_order`. Стратегія не знає лотів.
