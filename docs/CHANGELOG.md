# Changelog — AI Trading Agent

Todos los cambios notables del proyecto documentados por fase.

## [Post-Fase 6] — 2026-03-16

### LLM: Migración a GPT-4o-mini (`c5b7f25`)
- **Refactorizado** `core/claude_bridge.py` de single-provider (Anthropic) a multi-provider
- **Prioridad**: OpenAI (`OPENAI_API_KEY`) > Anthropic (`ANTHROPIC_API_KEY`) > dry-run
- **Modelo**: `gpt-4o-mini` — $0.15/$0.60 por 1M tokens (100x más barato que Opus)
- **Costo estimado**: ~$0.03-0.05/día vs ~$5+/día con Claude Opus
- Usa la misma API key de OpenClaw (no requiere gasto adicional)
- Imports lazy: solo carga `langchain-openai` o `langchain-anthropic` según provider activo
- Variable `LLM_MODEL` en `.env` para cambiar modelo sin tocar código
- Instalado `langchain-openai` + `openai` en venv

### Trade Monitor — Cierre de Trades SL/TP (`79e35ac`)
- **Nuevo módulo** `agents/trade_monitor.py`
  - `TradeMonitor.check_open_trades()` evalúa cada trade abierto cada ciclo
  - Cierre por **Stop Loss**, **Take Profit** o **Trailing Stop**
  - Trailing: mueve SL a break-even cuando precio supera 1.5×ATR de ganancia
  - Soporta trades BUY y SELL
  - Al cerrar: actualiza DB, recalcula portfolio, publica en Redis `trades:closed`
- **Integrado** en `scripts/run_trading.py` como paso 0 del loop principal
- **Portfolio snapshots** periódicos cada 5 ciclos (~5 min) para cálculo de Sharpe
- **Fix** `get_portfolio()`: ahora calcula exposición real desde trades abiertos en DB
- Primer trade cerrado: ETH TAKE_PROFIT +$166.67 (+0.80%)

### Arthas/Telegram Integration (`cafc25a`)
- Nuevo `scripts/arthas_trading.py` — CLI con 8 comandos (status, portfolio, trades, signals, prices, metrics, scan, report)
- `/root/trading.sh` — wrapper bash que activa venv antes de ejecutar
- Registrado en TOOLS.md y RULES.md de OpenClaw con triggers automáticos

### Systemd Service 24/7 (`ab07e48`)
- Creado `/etc/systemd/system/trading-agent.service`
- Fix: portfolio INSERT sin `available_cash` y `timestamp` (NOT NULL violation)
- Servicio enabled, Restart=always, After=postgresql+redis

---

## [Fase 6] Paper Trading — 2026-03-16 (`1b61032`)

- `scripts/run_trading.py` — loop principal while True con scan cada 60s
- `tests/paper/metrics.py` — cálculo de win_rate, profit_factor, max_drawdown, Sharpe, expectancy
- Tabla `paper_sessions` creada (PAPER_SESSION_001, balance $10,000)
- Criterios de graduación definidos (55% WR, 1.5 PF, <12% DD, ≥30 trades)
- Test E2E pasado: scan → strategy → risk → execute → DB → Redis

## [Fase 5] Dashboard + Briefing — 2026-03-16 (`76a8228`)

- `dashboard/app.py` — Streamlit dashboard en puerto 8501
  - Secciones: Portfolio, Open Trades, Signals, Market Data, Performance
- `scripts/daily_briefing.py` — briefing diario automático vía LLM
  - Resumen de mercado, posiciones, alertas
  - Persistido en `claude_explanations`

## [Fase 4] Risk Manager + Execution — 2026-03-16 (`4f6e1a2`)

- `risk/risk_manager.py` — 7 reglas inmutables de riesgo
  - 1% risk per trade, 5% max exposure, 10% drawdown halt
  - Max 3 concurrent trades, min R:R 1.5
  - Claude anomaly_check integrado
- `agents/execution_agent.py` — paper trading con simulación
  - Genera PAPER_xxxxxxxx order IDs
  - Persistencia en PostgreSQL, Redis pub/sub
  - Claude explain_trade post-ejecución
- 3 paper trades ejecutados: BTC @73799, ETH @2263, SOL @93.99

## [Fase 3] Strategy Engine — 2026-03-16 (`1b8c9ed`)

- `agents/strategy_engine.py` — orquestador de estrategias
- `strategies/trend_momentum.py` — EMA crossover + RSI + volumen
- `strategies/mean_reversion.py` — Bollinger Bands + RSI extremos
- `strategies/breakout.py` — ruptura con volumen > 2x
- Score 0-100 por oportunidad, Claude signal_interpretation

## [Fase 2] Market Scanner — 2026-03-16 (`efd7437`)

- `data/market_feed.py` — descarga OHLCV via ccxt, persiste en PostgreSQL
- `agents/indicators.py` — EMA, RSI, Bollinger, ATR, Volume
- `agents/market_scanner.py` — genera señales, persiste en DB, publica Redis
- Mapeo dinámico asset→exchange desde YAML config

## [Fase 1] Infraestructura — 2026-03-16 (`ec8bc1d`)

- venv Python 3.12.3 + requirements.txt (18 dependencias)
- PostgreSQL schema: market_data, signals, trades, portfolio, paper_sessions, claude_explanations
- Redis configurado (pub/sub channels: signals:new, strategies:opportunity, trades:executed)
- `core/claude_bridge.py` — bridge LangChain + Pydantic structured output
- `scripts/test_claude.py` + `scripts/test_exchange.py`

## [Fase 0] Inicialización — 2026-03-16 (`7225bcf`)

- Estructura de directorios /opt/trading/
- `config/exchange_config.yaml` — Kraken (primario) + OKX (secundario)
- Binance descartado (HTTP 451 bloqueado desde VPS)
