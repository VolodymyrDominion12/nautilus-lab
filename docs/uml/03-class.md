# Class: типи, роботи, порти

Імена збігаються з кодом. Поля — ключові, не вичерпні.

## Доменні значення й наміри

```mermaid
classDiagram
    class OhlcvBar {
        +str instrument_id
        +datetime ts_utc
        +Decimal open
        +Decimal high
        +Decimal low
        +Decimal close
        +Decimal volume
    }

    class SignalSide {
        <<enumeration>>
        BUY
        SELL
        FLAT
    }

    class Signal {
        +str instrument_id
        +SignalSide side
        +datetime bar_ts_utc
        +str reason
        +MarketRegime regime
    }

    class LegIntent {
        +str instrument_id
        +SignalSide side
        +Decimal qty_weight
    }

    class SpreadSignal {
        +LegIntent leg_a
        +LegIntent leg_b
        +datetime bar_ts_utc
        +Decimal hedge_ratio
        +Decimal z_score
    }

    class QuoteIntent {
        +Decimal bid_price
        +Decimal ask_price
        +Decimal bid_qty_weight
        +Decimal ask_qty_weight
    }

    Signal --> SignalSide
    SpreadSignal --> LegIntent
    LegIntent --> SignalSide
    Signal --> MarketRegime

    class MarketRegime {
        <<enumeration>>
        UPTREND
        DOWNTREND
        RANGE
    }

    class RobotName {
        <<enumeration>>
        REGIME
        EMA
        PAIRS
        VPIN_MOMENTUM
        FORMULAIC_LGBM
        FUNDING
        ML_OBI
        GLFT
        TRI_SCAN
    }

    class TradingMode {
        <<enumeration>>
        RESEARCH
        PAPER
        LIVE
    }
```

`Signal` / `SpreadSignal` / `QuoteIntent` **не містять розміру в грошах**.
`qty_weight` — відносна вага ноги, не лоти.

## Ризик

```mermaid
classDiagram
    class RiskLimits {
        +Decimal risk_per_trade
        +Decimal stop_pct
        +Decimal max_daily_loss
        +Decimal max_drawdown
        +int max_open_positions
        +Decimal kelly_fraction
        +Decimal max_var_99
        +Decimal atr_stop_multiplier
    }

    class AccountSnapshot {
        +Decimal equity
        +Decimal peak_equity
        +Decimal day_start_equity
        +int open_positions
        +tuple recent_returns
    }

    class RiskDecision {
        +bool allowed
        +str reason
    }

    class RiskOverlay {
        +bool use_vol_scaling
        +Decimal vol_scaling_target
        +bool use_fractional_kelly
        +int kelly_min_trades
        +bool use_cvar_breaker
        +Decimal max_cvar_99
    }

    class TradeStats {
        +int wins
        +int losses
        +Decimal gross_profit
        +Decimal gross_loss
        +win_rate()
        +reward_risk()
        +record(pnl)
    }

    evaluate_entry ..> AccountSnapshot
    evaluate_entry ..> RiskLimits
    evaluate_entry ..> RiskOverlay
    evaluate_entry --> RiskDecision
    size_position ..> RiskLimits
    resolve_risk_fraction ..> TradeStats
```

`evaluate_entry` / `size_position` живуть у `application/risk.py`; типи лімітів — у `domain/risk.py`.

## Роботи (стратегії сигналів)

```mermaid
classDiagram
    class SingleLegRobot {
        <<Protocol>>
        +on_bar(bar) Signal
    }

    class RegimeRouter {
        -RegimeClassifier classifier
        -UptrendBreakout uptrend
        -DowntrendBreakout downtrend
        -RangeMeanReversion range
        -BarVpin vpin
        +on_bar(bar) Signal
    }

    class RegimeClassifier {
        +update(close) RegimeSnapshot
        +MarketRegime regime
    }

    class EmaCrossover {
        +on_bar(bar) Signal
    }

    class VpinMomentum {
        +on_bar(bar) Signal
    }

    class FormulaicLgbmStrategy {
        +on_bar(bar) Signal
    }

    class PairsTrading {
        +on_bar(bar_a, bar_b) SpreadSignal
    }

    class GlftMarketMaker {
        +quote() QuoteIntent
    }

    class FundingCashAndCarry {
        +on_snapshot() SpreadSignal
    }

    SingleLegRobot <|.. RegimeRouter
    SingleLegRobot <|.. EmaCrossover
    SingleLegRobot <|.. VpinMomentum
    SingleLegRobot <|.. FormulaicLgbmStrategy
    RegimeRouter --> RegimeClassifier
    RegimeRouter --> UptrendBreakout
    RegimeRouter --> DowntrendBreakout
    RegimeRouter --> RangeMeanReversion
```

Підключені до бектесту (`BACKTEST_WIRED_ROBOTS`): `RegimeRouter`, `EmaCrossover`, `PairsTrading`,
`VpinMomentum`, `FormulaicLgbmStrategy`. `GlftMarketMaker` і `FundingCashAndCarry` — будівельні блоки без адаптера.

## Application DTO і порти

```mermaid
classDiagram
    class BacktestRequest {
        +TradingMode mode
        +str instrument_id
        +RobotName robot
        +RiskLimits risk
        +BarOrigin source
        +FeeSchedule fee_schedule
    }

    class BacktestReport {
        +int fills
        +int positions
        +Decimal ending_balance
        +BacktestMetrics metrics
        +str tearsheet_path
    }

    class WalkForwardRequest {
        +BacktestRequest backtest
        +WalkForwardWindow window
        +Decimal in_sample_fraction
        +int embargo_bars
        +bool use_optuna
        +int folds
    }

    class WalkForwardReport {
        +SelectedParams selected
        +int candidates_tried
        +BacktestReport in_sample
        +BacktestReport out_of_sample
    }

    class MultiWindowReport {
        +tuple folds
        +mean_oos_return
        +beats_buy_and_hold()
    }

    class ResearchBacktestPort {
        <<Protocol>>
        +run(request, bars) BacktestReport
        +run_spread(request, bars_by_id) BacktestReport
    }

    class BarFeed {
        <<Protocol>>
        +load(request) list
        +load_multi(request) dict
    }

    class RunWalkForward {
        -ResearchBacktestPort engine
        -BarFeed feed
        +execute(request) WalkForwardReport
        +execute_multi(request) MultiWindowReport
    }

    class RunResearchBacktest {
        -ResearchBacktestPort engine
        -BarFeed feed
        +execute(request) BacktestReport
    }

    WalkForwardRequest --> BacktestRequest
    WalkForwardReport --> BacktestReport
    RunWalkForward --> ResearchBacktestPort
    RunWalkForward --> BarFeed
    RunResearchBacktest --> ResearchBacktestPort
    RunResearchBacktest --> BarFeed
    NautilusResearchBacktest ..|> ResearchBacktestPort
    ResearchBarFeed ..|> BarFeed
```

## Порти домену й адаптери даних

```mermaid
classDiagram
    class PublicBarFeed {
        <<Protocol>>
        +fetch(...) list~OhlcvBar~
    }

    class BarCatalog {
        <<Protocol>>
        +write(bars) int
        +load(...) list~OhlcvBar~
    }

    class FundingRateFeed {
        <<Protocol>>
        +fetch_history(...) list~FundingSnapshot~
    }

    class JsonHttpClient {
        <<Protocol>>
        +get_json(url, params) object
    }

    class BinancePublicKlines {
        +fetch(...) list~OhlcvBar~
    }

    class NautilusParquetCatalog {
        +write(bars) int
        +load(...) list~OhlcvBar~
    }

    class BinancePublicFunding {
        +fetch_history(...) list~FundingSnapshot~
    }

    class UrllibJsonClient {
        +get_json(url, params) object
    }

    PublicBarFeed <|.. BinancePublicKlines
    BarCatalog <|.. NautilusParquetCatalog
    FundingRateFeed <|.. BinancePublicFunding
    JsonHttpClient <|.. UrllibJsonClient
    IngestHistoricalBars --> PublicBarFeed
    IngestHistoricalBars --> BarCatalog
```
