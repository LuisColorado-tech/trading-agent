# grid-stable Specification

## Purpose
GRID_STABLE operates tight spread grids on stable crypto pairs (ETH/BTC, LINK/BTC). Independent systemd service (`grid-stable`), separate from the main trading-agent. Shares the `trades` table but has its own cycle, trailing, and cooldown logic. Backtested 12 months with PF=1.84 on ETH/BTC.

## Requirements

### Requirement: Independent Operation
The grid-stable agent SHALL run as an independent systemd service with its own 8-minute cycle, isolated from trading-agent failures.

#### Scenario: Trading-agent crash doesn't affect grid-stable
- GIVEN trading-agent service has crashed
- WHEN grid-stable cycle runs
- THEN grid-stable continues operating normally

### Requirement: Micro-spread Trading
The system SHALL trade pairs with tight profit targets, using small position sizes for consistent micro-gains.

#### Scenario: Profitable micro-trade
- GIVEN ETH/BTC spread is within grid range
- WHEN price touches grid level
- THEN execute BUY or SELL with target profit of ~$1.50

### Requirement: Exclusion from Main Portfolio Calculation
GRID_STABLE trades SHALL be excluded from `get_open_trades()` and `get_portfolio()` in run_trading.py to avoid inflating available_cash and blocking other strategies.

#### Scenario: GRID_STABLE trade doesn't block TM
- GIVEN GRID_STABLE has an open ETH/BTC position
- WHEN TM evaluates a new crypto signal
- THEN the GRID_STABLE position does not count toward DUPLICATE_ASSET checks

## Dependencies
- `agents/grid_stable_agent.py` — Independent grid service
- Systemd: `grid-stable.service`
