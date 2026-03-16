# Arquitectura Técnica — AI Trading Agent

## Visión General

El sistema opera como un pipeline de 5 etapas que se ejecuta cada 60 segundos:

```
Monitor → Scan → Evaluate → Risk Check → Execute
  ↓                                          ↓
Cerrar trades          Abrir trades nuevos
(SL/TP/Trailing)       (Paper mode)
```

Cada ciclo (~20s de procesamiento + ~40s de espera):

1. **Trade Monitor** revisa trades abiertos contra precios actuales
2. **Market Scanner** descarga candles OHLCV y genera señales técnicas
3. **Strategy Engine** evalúa 3 estrategias por cada asset/timeframe
4. **Risk Manager** aplica 7 reglas inmutables de riesgo
5. **Execution Agent** ejecuta trades aprobados en modo paper

---

## Módulos

### 1. MarketFeed (`data/market_feed.py`)

Descarga datos OHLCV de exchanges via ccxt y persiste en PostgreSQL.

```
Kraken → BTC, ETH, SOL, XAU (via XAUT)
OKX    → XAG (metales no disponibles en Kraken)
```

- Descarga 500 candles por activo/timeframe
- Guarda en tabla `market_data` con deduplicación por timestamp
- Mapeo dinámico desde `config/exchange_config.yaml`

### 2. MarketScanner (`agents/market_scanner.py`)

Analiza indicadores técnicos y genera señales.

**Indicadores calculados** (por `agents/indicators.py`):
- EMA 20/50 (tendencia)
- RSI 14 (momentum)
- Bollinger Bands 20,2 (volatilidad)
- ATR 14 (rango/riesgo)
- Volumen vs media 20

**Señales generadas**:
| Señal | Dirección | Condición |
|-------|-----------|-----------|
| EMA_CROSS_BULL | BUY | EMA20 > EMA50 |
| EMA_CROSS_BEAR | SELL | EMA20 < EMA50 |
| RSI_OVERSOLD | BUY | RSI < 30 |
| RSI_OVERBOUGHT | SELL | RSI > 70 |
| BB_LOWER_TOUCH | BUY | Close < BB lower |
| BB_UPPER_TOUCH | SELL | Close > BB upper |
| VOLUME_SPIKE | NEUTRAL | Vol > 2× promedio |

Señales persistidas en tabla `signals` y publicadas en Redis `signals:new`.

### 3. StrategyEngine (`agents/strategy_engine.py`)

Orquesta 3 estrategias y selecciona la mejor oportunidad:

#### Trend Momentum (`strategies/trend_momentum.py`)
- **Entrada BUY**: EMA20 > EMA50 + RSI entre 40-70 + precio < BB_upper
- **Entrada SELL**: EMA20 < EMA50 + RSI < 45
- **SL**: Entry - 1.5×ATR14 | **TP**: Entry + 2.5×ATR14
- **Trailing**: Break-even al 1.5×ATR de ganancia

#### Mean Reversion (`strategies/mean_reversion.py`)
- **Entrada BUY**: Precio ≤ BB_lower + RSI < 35
- **Entrada SELL**: Precio ≥ BB_upper + RSI > 65
- Preferido para metales (XAU, XAG)

#### Breakout (`strategies/breakout.py`)
- **Entrada**: Ruptura de BB con volumen > 2× promedio
- Preferido para crypto (BTC, ETH)

Cada estrategia devuelve un score 0-100. El LLM evalúa consistencia (`signal_interpretation`).
Sólo oportunidades con score ≥ 65 y aprobación del LLM pasan al Risk Manager.

### 4. RiskManager (`risk/risk_manager.py`)

**Punto de autoridad final. 7 reglas inmutables:**

```
1. Drawdown ≥ 10%            → HALT (detener todo)
2. Exposición ≥ 5%           → REJECT
3. Trades abiertos ≥ 3       → REJECT
4. Risk per unit = 0         → REJECT
5. R:R ratio < 1.5           → REJECT
6. Claude CRITICAL (≥85%)    → REJECT
7. Todo OK                   → APPROVE + position sizing
```

**Position sizing**:
```
risk_amount = total_balance × 0.01    (1%)
position_size = risk_amount / |entry - stop_loss|
```

El LLM ejecuta `anomaly_check` antes de aprobar.

### 5. ExecutionAgent (`agents/execution_agent.py`)

Ejecuta trades aprobados por el RiskManager.

**Flujo**:
1. Recibe signal + decision aprobada
2. Paper mode: genera orden simulada `PAPER_xxxxxxxx`
3. Guarda trade en DB (status='OPEN')
4. LLM genera `explain_trade`
5. Publica en Redis `trades:executed`

### 6. TradeMonitor (`agents/trade_monitor.py`)

**Módulo crítico**: monitorea trades abiertos y cierra al alcanzar SL/TP.

**Evaluación por trade (cada ciclo)**:
```
BUY trade:
  - Precio ≤ SL → Cerrar STOP_LOSS
  - Precio ≥ TP → Cerrar TAKE_PROFIT
  - Precio ≥ Entry + 1.5×risk → Mover SL a break-even (trailing)

SELL trade:
  - Precio ≥ SL → Cerrar STOP_LOSS
  - Precio ≤ TP → Cerrar TAKE_PROFIT
  - Precio ≤ Entry - 1.5×risk → Mover SL a break-even (trailing)
```

**Al cerrar un trade**:
1. UPDATE trades → status='CLOSED', exit_price, pnl, pnl_pct, close_reason
2. Recalcular portfolio (balance, exposure, drawdown)
3. INSERT portfolio snapshot
4. PUBLISH Redis `trades:closed`

### 7. LLMBridge (`core/claude_bridge.py`)

Bridge multi-provider con LangChain + Pydantic structured output.

**Providers** (prioridad):
1. `OPENAI_API_KEY` → ChatOpenAI (gpt-4o-mini por defecto)
2. `ANTHROPIC_API_KEY` → ChatAnthropic (claude-opus-4-5 por defecto)
3. Sin key → dry-run (confidence=0, result=NEUTRAL)

**5 task types**, cada uno con Pydantic model:
| Task | Output Model | Campos clave |
|------|-------------|--------------|
| sentiment_analysis | SentimentResult | result, confidence, reasoning, flags |
| signal_interpretation | SignalInterpretationResult | consistency, recommendation, confidence |
| anomaly_check | AnomalyResult | anomaly_detected, severity, confidence |
| explain_trade | ExplainTradeResult | result, confidence, reasoning |
| daily_briefing | DailyBriefingResult | result, confidence, reasoning |

**Principio**: el LLM nunca bloquea la operación. Si falla, retorna resultado neutral.

---

## Flujo de Datos

```
Exchange (Kraken/OKX)
    ↓ ccxt
MarketFeed.fetch_ohlcv()
    ↓ PostgreSQL: market_data
MarketScanner.scan()
    ↓ PostgreSQL: signals  |  Redis: signals:new
StrategyEngine.evaluate()
    ↓ LLM: signal_interpretation
RiskManager.evaluate()
    ↓ LLM: anomaly_check
ExecutionAgent.execute()
    ↓ PostgreSQL: trades  |  Redis: trades:executed
    ↓ LLM: explain_trade
TradeMonitor.check_open_trades()
    ↓ PostgreSQL: trades (update)  |  portfolio (insert)
    ↓ Redis: trades:closed
```

---

## Infraestructura

| Componente | Tecnología | Ubicación |
|------------|-----------|-----------|
| Servidor | Ubuntu 24.04 LTS | VPS srv1347416 |
| Python | 3.12.3 + venv | /opt/trading/venv/ |
| Base de datos | PostgreSQL 16.13 | localhost:5432, db=trading_agent |
| Cache/PubSub | Redis 7.0.15 | localhost:6379 |
| Exchanges | Kraken + OKX | via ccxt (API keys en .env) |
| LLM | GPT-4o-mini | via OpenAI API |
| Dashboard | Streamlit | puerto 8501 |
| Servicio | systemd | trading-agent.service |
| Bot | Arthas (OpenClaw) | Telegram via /root/trading.sh |
| Logs | Loguru | /opt/trading/logs/ (rotación diaria, 30 días) |

---

## Schema PostgreSQL

### trades
```sql
id              UUID PRIMARY KEY DEFAULT uuid_generate_v4()
asset           VARCHAR NOT NULL
side            VARCHAR CHECK(IN ('BUY','SELL'))
strategy        VARCHAR NOT NULL
entry_price     NUMERIC NOT NULL
exit_price      NUMERIC              -- NULL mientras OPEN
stop_loss       NUMERIC NOT NULL
take_profit     NUMERIC NOT NULL
position_size   NUMERIC NOT NULL
position_pct    NUMERIC NOT NULL
pnl             NUMERIC              -- calculado al cerrar
pnl_pct         NUMERIC              -- calculado al cerrar
fees            NUMERIC DEFAULT 0
status          VARCHAR DEFAULT 'OPEN' CHECK(IN ('OPEN','CLOSED','CANCELLED'))
close_reason    VARCHAR              -- STOP_LOSS, TAKE_PROFIT, MANUAL
exchange        VARCHAR DEFAULT 'kraken'
paper_trade     BOOLEAN DEFAULT true
timestamp_open  TIMESTAMPTZ NOT NULL DEFAULT now()
timestamp_close TIMESTAMPTZ          -- NULL mientras OPEN
metadata        JSONB DEFAULT '{}'   -- trailing_activated, etc.
```

### portfolio
```sql
id              UUID PRIMARY KEY
total_balance   NUMERIC
available_cash  NUMERIC
exposure_pct    NUMERIC
pnl_day         NUMERIC
drawdown_pct    NUMERIC
peak_balance    NUMERIC
positions       JSONB
timestamp       TIMESTAMPTZ
```

### signals
```sql
id              UUID PRIMARY KEY
asset           VARCHAR
signal_type     VARCHAR
direction       VARCHAR
strength        NUMERIC
indicators      JSONB
timeframe       VARCHAR
timestamp       TIMESTAMPTZ
```

---

## Configuración

### Variables de Entorno (`config/.env`)

```env
# LLM
OPENAI_API_KEY=sk-proj-...
LLM_MODEL=gpt-4o-mini          # o gpt-4o, claude-opus-4-5, etc.

# Exchanges
KRAKEN_API_KEY=...
KRAKEN_SECRET=...
OKX_API_KEY=...
OKX_SECRET=...
OKX_PASSPHRASE=...

# Database
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=trading_agent
POSTGRES_USER=trading
POSTGRES_PASSWORD=...

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# System
PAPER_TRADING=true
LOG_LEVEL=INFO
```

### Systemd (`/etc/systemd/system/trading-agent.service`)

```ini
[Unit]
Description=AI Trading Agent - Paper Trading Loop
After=postgresql.service redis-server.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/trading
ExecStart=/opt/trading/venv/bin/python3 /opt/trading/scripts/run_trading.py
Restart=always
RestartSec=10
Environment=PYTHONPATH=/opt/trading

[Install]
WantedBy=multi-user.target
```
