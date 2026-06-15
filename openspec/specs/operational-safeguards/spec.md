# operational-safeguards Specification

## Purpose
Defines operational safety mechanisms (P1, P2, P3) that protect the trading system from cascading failures in production. Ratified by Trading Council #10 (2-0-2).

## Requirements

### Requirement: P1 — Drawdown based on Session Capital
The system SHALL calculate drawdown relative to `max(initial_session_capital, current_balance)`, not absolute historical peak.

#### Scenario: Profit retracement does not trigger emergency
- GIVEN session started with $1,000 and current balance is $1,928
- GIVEN historical peak was $2,115 (from a previous market regime)
- WHEN calculating drawdown
- THEN DD SHALL be 0%, not 8.8%
- AND MarketGuard SHALL remain in NORMAL mode

#### Scenario: Loss below initial capital triggers DD
- GIVEN session started with $1,000 and current balance is $920
- WHEN calculating drawdown
- THEN DD SHALL be (1000-920)/1000 = 8%
- AND MarketGuard SHALL enter EMERGENCY mode

### Requirement: P2 — Circuit Breaker on Loop Crashes
The system SHALL halt the trading agent if 3 unhandled exceptions occur within a 5-minute window.

#### Scenario: Three crashes in 5 minutes halts agent
- GIVEN the main loop has crashed 2 times in the last 4 minutes
- WHEN a third crash occurs
- THEN the agent SHALL halt with reason CIRCUIT_BREAKER:{n}crashes
- AND a critical alert SHALL be sent to Telegram
- AND recovery SHALL require manual restart

#### Scenario: Successful cycle resets crash counter
- GIVEN 2 crashes have occurred
- WHEN the next cycle completes successfully
- THEN crash_count SHALL reset to 0

### Requirement: P3 — Degraded Guard Mode
The system SHALL use three levels of MarketGuard restriction: NORMAL (1.0x), DEGRADED (0.25x), and EMERGENCY (0.0x), based on drawdown percentage.

#### Scenario: Moderate drawdown triggers degraded mode
- GIVEN drawdown is between 5% and 8%
- WHEN MarketGuard evaluates portfolio
- THEN position_multiplier SHALL be 0.25x
- AND guard SHALL log "MARKETGUARD: DEGRADED"

#### Scenario: High drawdown triggers emergency
- GIVEN drawdown is >= 8%
- WHEN MarketGuard evaluates portfolio
- THEN position_multiplier SHALL be 0.0x
- AND new positions SHALL be blocked

#### Scenario: Normal operation
- GIVEN drawdown is < 5%
- WHEN MarketGuard evaluates portfolio
- THEN position_multiplier SHALL be 1.0x
- AND no restriction SHALL be applied

## Dependencies
- `core/portfolio_utils.py` — `calculate_peak_balance(floor=initial_capital)`, `build_portfolio_state(initial_capital=)`
- `core/market_guard.py` — DEGRADED_DD threshold and DEGRADED_MULT multiplier
- `scripts/run_trading.py` — Circuit breaker crash counter in main loop
