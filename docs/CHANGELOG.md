# Changelog — AI Trading Agent

Todos los cambios notables del proyecto documentados por fase.

## [Post-Fase 6] Bug Fix: Re-entry Loop + Halt Persistente — 2026-03-17

### Risk: Cooldown post SL (Bug #7 — CRÍTICO)
- **Bug**: Tras un cierre por SL, el sistema re-entraba al MISMO trade en ~20 segundos porque las señales seguían válidas. Creó loops destructivos: BTC@75634 (4 trades, -$448), BTC@75199 (3 trades, -$315), SOL@95.17 (3 trades, -$313). Pérdidas evitables: ~$750.
- **Fix**: `SL_COOLDOWN_MINUTES = 30`. Tras SL/TRAILING_STOP, `register_sl_close(asset)` bloquea re-entrada 30 minutos. Nueva regla 3c en `evaluate()`.
- **Archivos**: `risk/risk_manager.py`, `scripts/run_trading.py`
- **Tests**: 3 nuevos (cooldown bloquea, solo mismo asset, expira)

### Risk: Halt persistente (Bug #8 — ALTO)
- **Bug**: `_trading_halted` era variable de instancia, se reseteaba a `False` al reiniciar servicio. Drawdown real 11.44% > límite 10%, pero el sistema no se detuvo.
- **Fix**: `check_persistent_halt(portfolio)` verifica drawdown desde DB al arranque y en cada ciclo.
- **Archivos**: `risk/risk_manager.py`, `scripts/run_trading.py`
- **Tests**: 2 nuevos (activa halt, noop si DD bajo)

## [Post-Fase 6] Trailing Dinámico — 2026-03-17

### TradeMonitor: Trailing stop progresivo por escalones de R
- **Bug #6**: El trailing solo movía SL a break-even (1 movimiento). No capturaba ganancias parciales.
- **Fix**: Trailing dinámico con escalones progresivos:
  - Activación: profit ≥ 1.0R → SL a break-even
  - Cada +0.5R de profit → SL avanza +0.5R adicional
  - SL solo avanza, nunca retrocede
  - R se persiste en metadata como `initial_risk` (inmutable por trade)
- **Nuevo close_reason**: `TRAILING_STOP` — diferencia cierres por trailing vs SL original
- **Nuevo canal Redis**: `trades:trailing` — notifica avances de trailing al dashboard
- **Compatibilidad**: Trades legacy (pre-implementación) no se rompen
- **Parámetros**: `TRAILING_ACTIVATION_R=1.0`, `TRAILING_STEP_R=0.5`, `TRAILING_OFFSET_R=1.0`
- **Archivos**: `agents/trade_monitor.py`, `config/exchange_config.yaml`
- **Tests**: 24 tests (16 nuevos) — escalones BUY/SELL, gaps, SL irreversible, legacy, close reasons
- **Documentación**: `docs/TRAILING_DINAMICO.md` (flujo técnico completo con modelo matemático)

## [Post-Fase 6] Pipeline Audit — 2026-03-17

### Risk: Límite de concentración por activo
- **Bug**: El sistema abría múltiples trades del mismo activo (ej. 2 BTC idénticos vía 15m + 1h), concentrando riesgo y desperdiciando slots de `MAX_CONCURRENT_TRADES`.
- **Fix**: Nueva regla en `risk_manager.py` (paso 3b): máximo 1 trade abierto por activo. Rechaza con `DUPLICATE_ASSET:{asset}`.
- **Impacto**: Fuerza diversificación entre BTC, ETH, SOL, XAU, XAG.

### Portfolio: Cálculo de `available_cash` corregido
- **Bug**: `get_portfolio()` restaba exposición de riesgo (~$337) pero `_close_trade()` sumaba valor nocional (~$22K). El campo `available_cash` oscilaba entre -$22K y +$42K, valores sin sentido.
- **Fix**: Ambos puntos ahora usan `balance - Σ(entry × size)` para cash. Exposición sigue siendo risk-based.
- **Archivos**: `scripts/run_trading.py`, `agents/trade_monitor.py`

### Data: Detección de datos obsoletos
- **Riesgo**: Si un exchange falla, `get_latest()` devolvía datos stale sin advertencia, generando señales sobre precios viejos.
- **Fix**: `market_feed.py` ahora verifica que el dato más reciente no supere 3× el timeframe. Emite `WARNING: STALE DATA` si se detecta.

## [Post-Fase 6] Exposure Fix — 2026-03-17

### Risk: Exposición nocional → risk-based
- **Bug**: Position sizing basado en riesgo (1% del balance) generaba posiciones con valor nocional alto (~$11K para BTC con balance $10K). El exposure check medía valor nocional ($entry × size / balance$ = 105%), bloqueando TODOS los trades nuevos tras abrir uno solo.
- **Fix**: Exposición ahora se calcula como riesgo real: $\sum |entry - SL| × size / balance$. Con 3 trades al 1% de riesgo cada uno, exposición = ~3%.
- **Archivos**: `risk/risk_manager.py`, `scripts/run_trading.py`, `agents/trade_monitor.py`
- **Check adicional**: Post-sizing verification — verifica que exposición_actual + nuevo_riesgo ≤ 5%

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
  - 1% risk per trade, 5% max risk-based exposure, 10% drawdown halt
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
