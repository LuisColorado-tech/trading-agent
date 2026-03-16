# AI Trading Agent — Paper Trading System

Sistema autónomo de trading algorítmico con IA para análisis de mercados crypto y metales preciosos.
Opera en modo **paper trading** (simulado) las 24/7 como servicio systemd en VPS Ubuntu.

## Estado Actual

| Componente | Estado | Versión |
|------------|--------|---------|
| Market Scanner | ✅ Operativo | Fase 2 |
| Strategy Engine | ✅ Operativo | Fase 3 |
| Risk Manager | ✅ Operativo | Fase 4 |
| Execution Agent | ✅ Operativo | Fase 4 |
| Trade Monitor (SL/TP) | ✅ Operativo | Post-Fase 6 |
| Dashboard Streamlit | ✅ Operativo | Fase 5 |
| Daily Briefing | ✅ Operativo | Fase 5 |
| Paper Trading Loop | ✅ 24/7 systemd | Fase 6 |
| Arthas/Telegram CLI | ✅ Integrado | Post-Fase 6 |
| LLM (GPT-4o-mini) | ✅ Activo | Post-Fase 6 |

## Arquitectura

```
┌─────────────────────────────────────────────────────────┐
│                   run_trading.py (Loop 24/7)            │
│                                                         │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │  Market   │→│   Strategy   │→│  Risk Manager     │  │
│  │  Scanner  │  │   Engine     │  │  (7 reglas)       │  │
│  └──────────┘  └──────────────┘  └──────────────────┘  │
│       ↓              ↓                    ↓              │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │  Market   │  │   LLMBridge  │  │  Execution Agent │  │
│  │  Feed     │  │ (GPT-4o-mini)│  │  (Paper mode)    │  │
│  └──────────┘  └──────────────┘  └──────────────────┘  │
│                                         ↓                │
│                                  ┌──────────────────┐   │
│                                  │  Trade Monitor    │   │
│                                  │  (SL/TP/Trailing) │   │
│                                  └──────────────────┘   │
└─────────────────────────────────────────────────────────┘
         ↕               ↕                ↕
    PostgreSQL         Redis          Exchanges
    (trades,        (pub/sub)      (Kraken, OKX)
     portfolio,                     via ccxt
     signals)
```

## Activos Monitoreados

| Activo | Exchange | Par | Timeframes |
|--------|----------|-----|------------|
| BTC | Kraken | BTC/USDT | 15m, 1h |
| ETH | Kraken | ETH/USDT | 15m, 1h |
| SOL | Kraken | SOL/USDT | 15m, 1h |
| XAU | OKX | XAUT/USDT | 15m, 1h |
| XAG | OKX | XAG/USDT:USDT | 15m, 1h |

## Estrategias

1. **Trend Momentum** — EMA20/50 crossover + RSI + Volumen
2. **Mean Reversion** — Bollinger Bands extremos (preferido para metales)
3. **Breakout** — Ruptura de resistencia con volumen >2x (BTC/ETH)

## Gestión de Riesgo (Inmutable)

| Parámetro | Valor |
|-----------|-------|
| Riesgo máximo por trade | 1% del portfolio |
| Exposición máxima total | 5% |
| Max drawdown (halt) | 10% |
| Max trades simultáneos | 3 |
| Stop Loss | 1.5 × ATR |
| Take Profit | 2.5 × ATR |
| Trailing Stop | Break-even al 1.5×ATR de ganancia |
| R:R mínimo | 1.5:1 |

## LLM — Análisis con IA

El sistema usa un LLM para 3 tareas por evaluación de estrategia:

| Tarea | Módulo | Propósito |
|-------|--------|-----------|
| `signal_interpretation` | StrategyEngine | Evaluar consistencia de señales |
| `anomaly_check` | RiskManager | Detectar anomalías antes de ejecutar |
| `explain_trade` | ExecutionAgent | Documentar razonamiento post-trade |

**Provider actual**: OpenAI GPT-4o-mini ($0.15/$0.60 por 1M tokens)
**Costo estimado**: ~$0.03-0.05/día

Configuración en `config/.env`:
```env
OPENAI_API_KEY=sk-proj-...
LLM_MODEL=gpt-4o-mini
```

Fallback: si no hay API key, opera en **dry-run** (confidence=0, result=NEUTRAL).

## Estructura del Proyecto

```
/opt/trading/
├── agents/
│   ├── market_scanner.py      # Escaneo de señales técnicas
│   ├── strategy_engine.py     # Orquestador de 3 estrategias
│   ├── execution_agent.py     # Ejecución de trades (paper mode)
│   ├── trade_monitor.py       # Monitoreo SL/TP/Trailing de trades abiertos
│   └── indicators.py          # Indicadores técnicos (EMA, RSI, BB, ATR)
├── core/
│   └── claude_bridge.py       # LLMBridge multi-provider (OpenAI/Anthropic)
├── data/
│   └── market_feed.py         # Descarga OHLCV de Kraken/OKX via ccxt
├── risk/
│   └── risk_manager.py        # 7 reglas inmutables de riesgo
├── strategies/
│   ├── trend_momentum.py      # Estrategia de tendencia
│   ├── mean_reversion.py      # Estrategia de reversión a la media
│   └── breakout.py            # Estrategia de ruptura
├── scripts/
│   ├── run_trading.py         # Loop principal 24/7
│   ├── arthas_trading.py      # CLI para Arthas/Telegram
│   ├── daily_briefing.py      # Briefing diario de mercado
│   ├── test_claude.py         # Test de conexión LLM
│   └── test_exchange.py       # Test de exchanges
├── dashboard/
│   └── app.py                 # Dashboard Streamlit (puerto 8501)
├── tests/
│   └── paper/
│       └── metrics.py         # Métricas de graduación a producción
├── config/
│   ├── .env                   # Variables de entorno (NO commitear)
│   └── exchange_config.yaml   # Configuración de exchanges
├── logs/                      # Logs rotativos diarios
└── db/
    └── migrations/            # Migraciones SQL
```

## Base de Datos (PostgreSQL)

| Tabla | Propósito |
|-------|-----------|
| `trades` | Registro de trades (OPEN/CLOSED/CANCELLED) |
| `portfolio` | Snapshots periódicos del portfolio |
| `market_data` | Candles OHLCV históricos |
| `signals` | Señales técnicas detectadas |
| `paper_sessions` | Sesiones de paper trading |
| `claude_explanations` | Explicaciones del LLM por trade |

## Servicio systemd

```bash
# Estado del servicio
sudo systemctl status trading-agent

# Reiniciar
sudo systemctl restart trading-agent

# Ver logs en vivo
sudo journalctl -u trading-agent -f

# Archivo de servicio
/etc/systemd/system/trading-agent.service
```

## Arthas (Telegram)

El bot Arthas puede consultar el trading agent via `/root/trading.sh`:

```bash
bash /root/trading.sh status      # Balance, trades, señales
bash /root/trading.sh portfolio   # Historial del portfolio
bash /root/trading.sh trades      # Trades abiertos y cerrados
bash /root/trading.sh prices      # Precios actuales
bash /root/trading.sh metrics     # Win rate, Sharpe, PF
bash /root/trading.sh report      # Reporte completo
bash /root/trading.sh scan        # Forzar scan
```

## Criterios de Graduación a Producción

| Métrica | Target mínimo | Target óptimo |
|---------|--------------|---------------|
| Win Rate | ≥ 55% | ≥ 62% |
| Profit Factor | ≥ 1.5 | ≥ 2.0 |
| Max Drawdown | < 12% | < 8% |
| Sharpe Ratio | ≥ 1.2 | ≥ 1.8 |
| Total trades | ≥ 30 | ≥ 60 |
| Semanas estables | ≥ 4 | ≥ 6 |

## Desarrollo

```bash
# Activar entorno virtual
cd /opt/trading && source venv/bin/activate

# Ejecutar manualmente
python3 scripts/run_trading.py

# Dashboard
streamlit run dashboard/app.py --server.port 8501

# Tests de métricas
python3 tests/paper/metrics.py
```
