# stocks Specification

## Purpose
Stocks agent trades NYSE/NASDAQ equities using momentum strategies (Minervini SEPA BUY-only, GLD mean-reversion, QQQ momentum). Operates only during NYSE hours (14:30-20:59 UTC, Mon-Fri).

## Requirements

### Requirement: NYSE Hours Only
The system SHALL only execute trades during NYSE market hours.

#### Scenario: Weekend no-trade
- GIVEN current day is Saturday or Sunday
- WHEN stocks agent evaluates signals
- THEN return zero executions with no error

#### Scenario: Outside market hours
- GIVEN UTC hour is outside 14:30-21:00
- WHEN stocks agent attempts to trade
- THEN log reason and skip

### Requirement: Stale Feed Detection
The system SHALL detect stale market data (>5 min old) and skip trading on affected symbols.

#### Scenario: Stale data warning
- GIVEN last price update for QQQ is > 5 minutes old
- WHEN evaluating trade signals for QQQ
- THEN log "STOCKS FEED: stale" warning and skip QQQ

### Requirement: Anti-Loop Detection
The system SHALL detect and prevent price repetition loops (same entry_price appearing > 5 times in 4 hours).

#### Scenario: Loop detection
- GIVEN QQQ has 6+ trades with identical entry_price in 4 hours
- WHEN health check runs
- THEN flag as loop detected and alert

## Dependencies
- `data/stocks_feed.py` — Alpaca market data feed
- `agents/stocks_agent.py` — Strategy evaluation and execution
