# trend-momentum Specification

## Purpose
TrendMomentum is the primary crypto trading strategy. It detects directional momentum using EMA crosses, RSI, MACD, and volume confirmation, executing SELL trades in TREND_DOWN regimes. BUY is blocked because 2Y backtesting showed -$6,151 in losses.

## Requirements

### Requirement: Signal Generation
The system SHALL generate trading signals with a minimum score of 65, combining EMA crossover, RSI range [25-45], MACD confirmation, and volume ratio > 1.2.

#### Scenario: Valid SELL signal in TREND_DOWN
- GIVEN asset regime is TREND_DOWN
- WHEN EMA crossover is bearish AND RSI is between 25-45 AND MACD is below signal line
- THEN generate a SELL opportunity with score >= 65

#### Scenario: CHOPPY regime blocks all signals
- GIVEN asset regime does not have allow_trend flag
- WHEN evaluating strategies
- THEN return early without evaluating any strategy

### Requirement: Risk Pipeline
Every signal SHALL pass through a 7-step pipeline before execution: Score, Market Regime, DirectionAllowed, DirectionGuard, Confluence, RiskManager, Execution.

#### Scenario: DUPLICATE_ASSET rejection
- GIVEN an open position exists for the same asset
- WHEN a new signal for that asset is evaluated
- THEN the RiskManager SHALL reject with reason DUPLICATE_ASSET:{asset}

#### Scenario: MAX_CONCURRENT limit
- GIVEN TREND_MOMENTUM already has 2 open trades
- WHEN a new TM signal is generated
- THEN the RiskManager SHALL reject with reason MAX_CONCURRENT_TREND_MOMENTUM:2/2

### Requirement: Performance Metrics
TM SHALL maintain WR >= 45%, PF >= 1.20, trades/week >= 15, and DD < 10% in a 7-day rolling window.

#### Scenario: Performance degradation
- GIVEN TM WR drops below 35% in 7 days
- WHEN health check runs
- THEN mark agent as RED and recommend Council intervention

### Requirement: Post-Council Parameters
The system SHALL operate with parameters approved by Trading Council sessions.

| Parameter | Value | Council |
|-----------|-------|---------|
| MIN_SCORE | 65 | #1 (4-0) |
| _TREND_STRENGTH_MIN | 0.08 | #2 (3-0-1) |
| confluence_min | 2-3 por asset | #5 (4-0) |
| MAX_CONCURRENT | 2 | Original |

## Dependencies
- `core/market_regime.py` — regime classification
- `risk/risk_manager.py` — risk evaluation and slot management
- `core/asset_profiles.py` — per-asset confluence thresholds
- `agents/indicators.py` — EMA, RSI, MACD calculation
