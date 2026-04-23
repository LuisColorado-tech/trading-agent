# ARTHAS TRADING SYSTEM — Índice Maestro para IA

> **Entry point para IA.** Lee este archivo primero. Tiempo estimado: 2 minutos.
> Última actualización: Abril 2026 (post-SESSION_008)

---

## 1. Qué es este sistema

Sistema de trading algorítmico 100% automatizado corriendo en un VPS Linux. Tiene 4 agentes independientes que operan en mercados distintos. Todo es paper trading actualmente (simulado sin capital real).

**El objetivo**: validar estrategias en paper, llegar a métricas mínimas (WR ≥ 40%, Profit Factor ≥ 1.5, 3 meses consistentes), y después fondear con $300 USDC para operar en vivo.

---

## 2. Infraestructura

| Componente | Detalle |
|---|---|
| VPS | `187.77.5.109` — srv1347416 — Linux |
| Python | `3.12` — SIEMPRE usar `/opt/trading/venv/bin/python3` |
| PostgreSQL | `postgresql://trading:Tr4d1ng_Ag3nt_2026!@localhost:5432/trading_agent` |
| Redis | `localhost:6379` — pub/sub, cooldowns, deduplicación |
| Directorio base | `/opt/trading/` |
| GitHub | `https://github.com/LuisColorado-tech/trading-agent.git` branch `master` |
| Dashboard | `http://187.77.5.109:8501` (Streamlit) |
| Telegram bot | TOKEN `8179816401:AAHF3xprmPeauuOapGDD9idQrLsv8Dl2EYE`, CHAT `999936393` |

### Variables de entorno críticas

```bash
# Cargar todas las variables:
set -a && source /opt/trading/config/.env && set +a

# Variables principales:
DB_URL=postgresql://trading:Tr4d1ng_Ag3nt_2026!@localhost:5432/trading_agent
POSTGRES_USER=trading
POSTGRES_PASSWORD=Tr4d1ng_Ag3nt_2026!
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=trading_agent
REDIS_HOST=localhost
REDIS_PORT=6379
PAPER_TRADING=true
DERIBIT_CLIENT_ID=<en .env>
DERIBIT_CLIENT_SECRET=<en .env>
POLYMARKET_API_KEY=<en .env>
TELEGRAM_BOT_TOKEN=8179816401:AAHF3xprmPeauuOapGDD9idQrLsv8Dl2EYE
TELEGRAM_CHAT_ID=999936393
```

---

## 3. Los 4 Agentes

| Agente | Estado | Mercado | Resultado paper | Doc completa |
|---|---|---|---|---|
| **Trading Agent** | ✅ ACTIVO | Crypto/Metales spot | SESSION_008: +$1,246 en 10 días | [AI_TRADING_AGENT.md](AI_TRADING_AGENT.md) |
| **Options Agent** | ✅ ACTIVO | BTC PUT OTM (Deribit) | paper_mode, sin resultados aún | [AI_OPTIONS_AGENT.md](AI_OPTIONS_AGENT.md) |
| **Polymarket Agent** | ✅ ACTIVO | Mercados de predicción crypto | WR 60% pero PnL -$70 | [AI_POLYMARKET_AGENT.md](AI_POLYMARKET_AGENT.md) |
| **BTC Direction** | ⚠️ VIGILANCIA | "BTC sube o baja en X min" | WR 27.6%, PnL -$329 (105 trades) | [AI_BTC_DIRECTION_AGENT.md](AI_BTC_DIRECTION_AGENT.md) |

---

## 4. Servicios systemd (7 servicios)

```bash
# Ver estado de todos:
systemctl status trading-agent options-agent polymarket-agent btc-direction trading-dashboard trading-health telegram-bot

# Reiniciar un agente:
systemctl restart trading-agent

# Ver logs en tiempo real:
journalctl -u trading-agent -f

# Ver últimas 50 líneas:
journalctl -u options-agent -n 50 --no-pager
```

| Servicio | Archivo | Descripción |
|---|---|---|
| `trading-agent` | `scripts/run_trading.py` | Ciclo principal Trading |
| `options-agent` | `scripts/run_options.py` | Ciclo Options Theta Farming |
| `polymarket-agent` | `scripts/run_polymarket.py` | Ciclo Polymarket |
| `btc-direction` | `btc_direction/run_btc_direction.py` | BTC Direction multi-TF |
| `trading-dashboard` | `dashboard/app.py` | Streamlit en :8501 |
| `trading-health` | `scripts/health_check.py` | Health check periódico |
| `telegram-bot` | — | Bot de notificaciones |

---

## 5. Comandos de diagnóstico rápido

```bash
# Contexto completo del sistema (USAR SIEMPRE AL INICIAR SESIÓN IA):
cd /opt/trading && venv/bin/python3 scripts/ai_context.py

# Estado de la DB (sesión paper activa):
set -a && source config/.env && set +a
venv/bin/python3 -c "
from sqlalchemy import create_engine, text; import os
e = create_engine(os.environ['DB_URL'])
with e.connect() as c:
    r = c.execute(text(\"SELECT session_name, status, final_balance-initial_balance as pnl FROM paper_sessions ORDER BY started_at DESC LIMIT 3\")).fetchall()
    [print(row) for row in r]
"

# Trades abiertos ahora:
venv/bin/python3 -c "
from sqlalchemy import create_engine, text; import os
e = create_engine(os.environ['DB_URL'])
with e.connect() as c:
    r = c.execute(text(\"SELECT asset, strategy, side, entry_price FROM trades WHERE status='OPEN' ORDER BY timestamp_open DESC\")).fetchall()
    print(f'{len(r)} trades abiertos'); [print(' ', row) for row in r]
"

# Redis cooldowns/halts activos:
redis-cli keys 'cooldown:*' ; redis-cli keys 'halt:*'

# Ver errores del agente principal hoy:
journalctl -u trading-agent --since today --no-pager | grep -i error | tail -20
```

---

## 6. Estructura de archivos clave

```
/opt/trading/
├── agents/
│   ├── strategy_engine.py      # Orquestador: escanea assets, evalúa señales
│   ├── trade_monitor.py        # Monitorea trades abiertos, aplica trailing
│   ├── execution_agent.py      # Ejecuta órdenes (paper o real)
│   ├── options_agent.py        # Orquestador del Options Agent
│   ├── grid_agent.py           # Grid Bot (RANGE/CHOPPY)
│   └── market_scanner.py       # Scanner de mercados para Polymarket
├── strategies/
│   ├── trend_momentum.py       # SELL en TREND_DOWN/BREAKOUT_DOWN
│   ├── breakout.py             # Breakout con vol_ratio ≥ 2.0
│   ├── mean_reversion.py       # DESACTIVADA (0 wins paper)
│   ├── prediction.py           # DESACTIVADA (ENABLED=False, sin API key)
│   ├── theta_farming.py        # Theta Farming: vender PUTs BTC OTM
│   └── signal_based_poly.py    # Polymarket: 60% edge mínimo por señal técnica
├── core/
│   ├── market_regime.py        # Clasificador de régimen (TREND_DOWN/UP/RANGE/CHOPPY)
│   ├── asset_profiles.py       # Parámetros SL/TP/trailing por asset
│   ├── performance_guard.py    # Bloqueo/probación por rendimiento
│   ├── paper_session_manager.py # Gestión de sesiones paper
│   ├── deribit_session_manager.py # Auth Deribit (mutex, deadlock fix)
│   └── notifications.py        # Telegram
├── risk/
│   └── risk_manager.py         # RiskManager INMUTABLE — autoridad final
├── data/
│   ├── market_feed.py          # Datos OHLCV (Kraken/OKX via CCXT)
│   └── polymarket_feed.py      # Feed de mercados Polymarket
├── btc_direction/
│   ├── btc_multifeed.py        # Feed multi-TF (5m/15m/4H/1H/Daily)
│   ├── btc_direction_feed.py   # Feed single-TF (legacy)
│   ├── btc_direction_strategy.py # Evaluación de señales momentum
│   └── btc_direction_executor.py # Ejecución y settlement de trades
├── config/
│   ├── exchange_config.yaml    # Todos los parámetros de los 4 agentes
│   └── .env                    # Variables de entorno (no en git)
├── scripts/
│   ├── ai_context.py           # Briefing completo → USAR AL INICIAR IA
│   ├── run_trading.py          # Entry point Trading Agent
│   ├── run_options.py          # Entry point Options Agent
│   ├── run_polymarket.py       # Entry point Polymarket Agent
│   ├── health_check.py         # Health check con alertas Telegram
│   └── backfill_btc_direction.py # Backfill de outcomes BTC Direction
└── docs/
    ├── AI_MASTER.md            # Este archivo
    ├── AI_TRADING_AGENT.md     # Doc Trading Agent
    ├── AI_OPTIONS_AGENT.md     # Doc Options Agent
    ├── AI_POLYMARKET_AGENT.md  # Doc Polymarket Agent
    ├── AI_BTC_DIRECTION_AGENT.md # Doc BTC Direction
    ├── ARCHITECTURE.md         # Arquitectura técnica general
    └── CHANGELOG.md            # Historial de cambios
```

---

## 7. Base de datos — Tablas principales

```sql
-- Tablas del Trading Agent:
paper_sessions          -- sesiones paper (ACTIVE/CLOSED)
portfolio               -- estado del portafolio (balance, DD, PnL)
trades                  -- todos los trades (OPEN/CLOSED)

-- Tablas del Options Agent:
options_sessions        -- sesiones options paper
options_positions       -- posiciones options (31 columnas)
options_market_data     -- snapshots de IVs y precios

-- Tablas del Polymarket Agent:
poly_sessions           -- sesiones polymarket
poly_positions          -- posiciones polymarket
poly_markets            -- mercados indexados

-- Tablas compartidas:
signals                 -- señales técnicas (escribe Trading, leen Poly y BTC Direction)
btc_direction_trades    -- trades específicos del BTC Direction Agent

-- Queries útiles:
SELECT session_name, status, total_trades, winning_trades,
       final_balance - initial_balance as pnl
FROM paper_sessions ORDER BY started_at DESC LIMIT 5;

SELECT asset, strategy, side, pnl, close_reason, timestamp_close
FROM trades WHERE status='CLOSED'
ORDER BY timestamp_close DESC LIMIT 20;
```

---

## 8. Historial de decisiones importantes

| Fecha | Decisión | Razón |
|---|---|---|
| Feb 2026 | BUY bloqueado en TREND_UP | Backtest 2Y: -$6,151 |
| Mar 2026 | Binance → Kraken+OKX | HTTP 451 geo-restriction en este VPS |
| Mar 2026 | MEAN_REVERSION desactivada paper | 8 trades, 0 wins, -$569 |
| Abr 2026 | PREDICTION_LLM desactivado | 43 trades, 0 wins, -$582, sin OpenAI API key |
| Abr 2026 | Polymarket edge 10% → 15% | Mejorar R:R, filtrar mercados ajustados |
| Abr 2026 | Polymarket max_position 4% → 2.5% | Reducir DD mientras se valida edge |
| Abr 2026 | Options IV Rank 30d → 252d | 30d era demasiado corto, 252d estándar del sector |
| Abr 2026 | BTC Direction bug fix settlement | `/markets?conditionId=` → `/events?slug=` (endpoint correcto) |
| Abr 2026 | Deadlock fix deribit_session_manager | `_update_peak_and_drawdown(conn=None)` reutiliza tx |

---

## 9. Estado actual (Abril 2026)

- **SESSION_008**: ACTIVA desde ~12 Abr. +$1,246 en 10 días pero **concentrado**: 74% del PnL vino de solo 2 días (Apr 18-19). Profit Factor real: 1.46. EV: $5.49/trade. 7/11 días positivos.
- **Fortalezas**: el edge de TREND_MOMENTUM SELL es real. RiskManager funciona (peor día: -$134 = -1.3%).
- **Expectativa realista**: 2-4%/mes consistente, con spikes 8-10% en mercados tendenciales.
- **Camino a fondeo**: $300 USDC cuando 3 meses consecutivos con Profit Factor ≥ 1.5.

---

## 10. Flujo de trabajo para nueva IA

```
1. Lee este archivo (AI_MASTER.md)
2. Ejecuta: cd /opt/trading && venv/bin/python3 scripts/ai_context.py
3. Lee el doc específico del agente que te interesa (AI_*.md)
4. Para modificar parámetros: edita config/exchange_config.yaml
5. Para cambios de código: edita el archivo específico indicado en el doc
6. Para ver logs: journalctl -u <servicio> -n 50 --no-pager
7. Para reiniciar tras cambios: systemctl restart <servicio>
8. Siempre usar: /opt/trading/venv/bin/python3 (NUNCA python3 del sistema)
```

---

## 11. ⚡ ACTIVACIÓN LIVE TRADING — Instrucciones para IA

> **LEER ESTO si Lucho dice que ya fondeó y quiere activar el trading real.**
> Plan acordado: ~$300 USD iniciales en mitad de 2026. $220 → Kraken, $80 → Polymarket.

### Prerequisitos — verificar ANTES de activar

```bash
# 1. Confirmar que hay 3 meses de paper con Profit Factor ≥ 1.5:
cd /opt/trading && set -a && source config/.env && set +a
venv/bin/python3 -c "
from sqlalchemy import create_engine, text; import os
e = create_engine(os.environ['DB_URL'])
with e.connect() as c:
    r = c.execute(text('''
        SELECT session_name, total_trades, winning_trades,
               ROUND((winning_trades::numeric/NULLIF(total_trades,0))*100,1) as wr_pct,
               final_balance - initial_balance as pnl
        FROM paper_sessions WHERE status=\'CLOSED\' ORDER BY started_at DESC LIMIT 5
    ''')).fetchall()
    [print(row) for row in r]
"

# 2. Confirmar que las API keys de Kraken están en .env (no CHANGE_ME):
grep 'KRAKEN_API_KEY' /opt/trading/config/.env
```

### Pasos de activación (en orden exacto)

**Paso 1 — Agregar API keys de Kraken al .env:**
```bash
nano /opt/trading/config/.env
# Cambiar:
#   KRAKEN_API_KEY=CHANGE_ME  →  KRAKEN_API_KEY=<key real de Kraken>
#   KRAKEN_SECRET=CHANGE_ME   →  KRAKEN_SECRET=<secret real de Kraken>
```

**Paso 2 — Activar live trading:**
```bash
# En /opt/trading/config/.env, cambiar:
#   PAPER_TRADING=true  →  PAPER_TRADING=false
#   ENVIRONMENT=development  →  ENVIRONMENT=production
#   INITIAL_CAPITAL=220  (agregar esta línea — el balance real depositado en Kraken)
```

**Paso 3 — Verificar parámetros del RiskManager para $220:**
```
El RiskManager en /opt/trading/risk/risk_manager.py tiene estos parámetros inmutables:
  MAX_RISK_PER_TRADE_PCT = 0.005   → 0.5% de $220 = $1.10 por trade (adecuado)
  MAX_PORTFOLIO_EXPOSURE = 0.05    → 5% de $220 = $11 en posiciones abiertas (adecuado)
  MAX_DRAWDOWN_STOP      = 0.10    → 10% de $220 = $22 de pérdida → parar todo
  MAX_CONCURRENT_TRADES  = 3       → máximo 3 trades a la vez
NO cambiar estos parámetros — están calibrados con backtest 2Y.
```

**Paso 4 — Reiniciar el agente principal:**
```bash
systemctl restart trading-agent
sleep 5
journalctl -u trading-agent -n 20 --no-pager
# Confirmar que no dice PAPER MODE en los logs
```

**Paso 5 — Verificar primera orden:**
```bash
# El agente tomará la primera señal que aparezca (puede tardar minutos u horas)
journalctl -u trading-agent -f
# Buscar: "LIVE ORDER PLACED" o "Executing trade" sin "[PAPER]"
```

### Capital de Polymarket ($80)
- Polymarket NO usa las API keys de Kraken — usa la wallet CLOB configurada en .env
- Para activar: cambiar `PAPER_TRADING=false` ya lo activa también en Polymarket
- Verificar saldo en la wallet antes de reiniciar polymarket-agent

### ⚠️ Qué NO hacer
- NO cambiar los parámetros del RiskManager — están calibrados
- NO activar OKX ni Deribit todavía — capital insuficiente
- NO subir `LLM_CALL_SAMPLE_RATE` por encima de 0.20 — el costo sube exponencialmente
- NO borrar las paper_sessions — son el historial de validación del edge

### Si algo sale mal
```bash
# Revertir a paper inmediatamente:
sed -i 's/PAPER_TRADING=false/PAPER_TRADING=true/' /opt/trading/config/.env
systemctl restart trading-agent
# Notificar a Lucho por Telegram automáticamente via health_check
```

---

## 12. 📈 STOCKS AGENT — Agente de Acciones NYSE/NASDAQ

**Estado**: Paper trading (pendiente claves Alpaca)

### Arquitectura

| Componente | Archivo | Descripción |
|---|---|---|
| Broker client | `core/alpaca_session_manager.py` | API REST Alpaca (paper/live) |
| Data layer | `data/stocks_feed.py` | OHLCV via Alpaca+yfinance fallback |
| Perfiles | `core/stocks_profiles.py` | 8 activos calibrados |
| Estrategia | `strategies/stocks_momentum.py` | Momentum + xsignal boost |
| Agente | `agents/stocks_agent.py` | Orquestador principal |
| Entry point | `scripts/run_stocks.py` | CLI y loop |
| Servicio | `stocks-agent.service` | systemd |

### Universo de activos
`NVDA`, `TSLA`, `AAPL`, `META`, `AMZN`, `SPY`, `QQQ`, `GLD`

SPY y QQQ actúan también como indicadores de **macro bias**: si ambos están en tendencia bajista, el agente bloquea BUY en acciones individuales.

### xsignals Integration
- Tabla: `xsignals_signals` en PostgreSQL (mismo DB)
- Lookback: últimas 48h por ticker + perfil
- @aguti00: WR=71.4% a 48h (21 señales validadas con yfinance) → **boost real**
- Boost: +15 puntos al score de StocksMomentumStrategy si señal alineada con conf≥55

### Tablas DB nuevas
```sql
stocks_sessions  -- sesiones paper/live
stocks_trades    -- trades individuales
stocks_ohlcv     -- cache de velas OHLCV
```

### Comandos systemd
```bash
systemctl start stocks-agent    # iniciar
systemctl stop stocks-agent     # detener
systemctl status stocks-agent   # estado
journalctl -u stocks-agent -f   # logs en tiempo real
```

### Comandos Telegram
```
/stocks        → estado actual (sesión, balance, trades abiertos, macro bias)
/stocks_status → igual que /stocks
```

### Activación (cuando tengas claves Alpaca)
```bash
# 1. Crear cuenta en https://alpaca.markets → gratis
# 2. Ir a Paper Trading → API Keys → Generate
# 3. Añadir a /opt/trading/config/.env:
ALPACA_API_KEY=<tu key>
ALPACA_SECRET_KEY=<tu secret>

# 4. Verificar acceso:
cd /opt/trading && set -a && source config/.env && set +a
venv/bin/python3 scripts/run_stocks.py --status

# 5. Iniciar en paper:
systemctl enable stocks-agent
systemctl start stocks-agent

# 6. Ver logs:
journalctl -u stocks-agent -f
```

### Parámetros de riesgo
```
MAX_RISK_PER_TRADE_PCT  = 1.0%   → $2.20 por trade con $220
MAX_PORTFOLIO_EXPOSURE  = 8.0%   → $17.60 en stocks simultáneos
MAX_CONCURRENT_TRADES   = 3
MAX_DRAWDOWN_STOP       = 10%    → parar si pierde $22
```

### Criterios para live con Alpaca
- 4 semanas en paper con PF ≥ 1.3
- Al menos 20 trades cerrados
- Máximo drawdown ≤ 8% en paper
- Macro bias BULL o NEUTRAL en SPY/QQQ

