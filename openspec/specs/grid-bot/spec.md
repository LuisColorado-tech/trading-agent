# grid-bot Specification

## Purpose
GRID_BOT operates buy/sell grids on crypto assets in RANGE and CHOPPY regimes. Complements TREND_MOMENTUM by capturing mean-reversion movements when trends are absent. Uses trailing stops, cooldown mechanisms, and SL_COOLDOWN to prevent overtrading.

## Requirements

### Requirement: Grid Placement
The system SHALL place grid orders only when market regime is RANGE or CHOPPY.

#### Scenario: GRID_BOT skips TREND regimes
- GIVEN asset regime is TREND_UP or TREND_DOWN
- WHEN grid_agent.run_cycle evaluates the asset
- THEN skip grid placement for that asset

### Requirement: Trailing Stop on Grids
The system SHALL use trailing stops for grid positions with tp_ratio >= 1.70 to capture extended moves.

#### Scenario: Tight grid skips trailing
- GIVEN grid_tp_ratio < 1.70 for an asset
- WHEN evaluating whether to activate trailing
- THEN skip trailing (counterproductive for tight grids)

### Requirement: Cooldown After Stop Loss
The system SHALL block re-entry to the same asset for 30 minutes after a STOP_LOSS or TRAILING_STOP close.

#### Scenario: SL cooldown prevents re-entry
- GIVEN GRID_BOT closed XAG with STOP_LOSS
- WHEN next cycle evaluates XAG
- THEN reject with reason SL_COOLDOWN:{asset}

## Dependencies
- `agents/grid_agent.py` — Grid bot cycle logic
- `core/market_regime.py` — Regime-based grid filtering
- `core/asset_profiles.py` — Per-asset grid parameters (tp_ratio, sl_multiplier)
