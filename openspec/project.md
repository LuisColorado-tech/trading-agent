# Arthas Trading System v1.3

Multi-agent algorithmic trading system running on paper mode.

## Active Agents (4 systemd)
- **trading-agent** — Crypto & metals: TrendMomentum, GridBot, SMC, BTCMicrostructure
- **stocks-agent** — NYSE/NASDAQ momentum (Alpaca)
- **grid-stable** — ETH/BTC, LINK/BTC tight spread grids
- **pairs-agent** — GLD-SLV cointegration pairs

## Architecture
- **Language**: Python 3.12
- **Database**: PostgreSQL (trades, portfolio, signals, market_data)
- **Cache**: Redis (cooldowns, dedup, direction_guard, signals)
- **Market Data**: CCXT (Kraken/OKX), Alpaca (stocks)
- **Dashboard**: Next.js 14 (web) + Streamlit (legacy)
- **API**: FastAPI (:8000)
- **Alerting**: Telegram via health_check.py timer

## Key Files
- Entry point: `scripts/run_trading.py`
- Risk manager: `risk/risk_manager.py`
- Strategy engine: `agents/strategy_engine.py`
- Trade monitor: `agents/trade_monitor.py`
- Execution agent: `agents/execution_agent.py`
- Market guard: `core/market_guard.py`
- Portfolio utils: `core/portfolio_utils.py`
- Specs: `openspec/specs/`
- Council: `.council/`

## Governance
All parameter changes go through Trading Council (scripts/trading_council.py).
Decision record in AGENTS.md under "Parámetros post-council".
