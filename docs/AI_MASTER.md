# ARTHAS TRADING SYSTEM — Índice Maestro para IA

> **Entry point para IA.** Lee este archivo primero. Tiempo estimado: 2 minutos.
> Última actualización: Mayo 20, 2026 (post-auditoría general + Strategy Architecture v2)

---

## 1. Qué es este sistema

Sistema de trading algorítmico 100% automatizado corriendo en un VPS Linux. Tiene agentes independientes que operan en mercados distintos. Todo es paper trading actualmente (simulado sin capital real).

**El objetivo**: validar estrategias en paper, llegar a métricas mínimas (WR ≥ 40%, Profit Factor ≥ 1.5, 3 meses consistentes), y después fondear para operar en vivo.

**Estado actual**: SESSION_011 (crypto $1,000) + STOCKS_SESSION_011 (stocks $1,000). Rumbo a validación de 3 meses para producción.

---

## 2. Infraestructura

| Componente | Detalle |
|---|---|
| VPS | `187.77.5.109` — srv1347416 — Linux |
| Python | `3.12` — SIEMPRE usar `/opt/trading/venv/bin/python3` |
| PostgreSQL | `postgresql://trading:Tr4d1ng_Ag3nt_2026!@localhost:5432/trading_agent` |
| Redis | `localhost:6379` — pub/sub, cooldowns, DirectionGuard, deduplicación |
| Directorio base | `/opt/trading/` |
| GitHub | `https://github.com/LuisColorado-tech/trading-agent.git` branch `master` |
| Dashboard Arthas | `http://187.77.5.109:3000` (Next.js) |
| Dashboard Homerun | `http://187.77.5.109:3001` (React — prediction markets) |
| Telegram | TOKEN `8179816401:AAHF3xprmPeauuOapGDD9idQrLsv8Dl2EYE`, CHAT `999936393` |
| Docker | `docker compose` para Homerun (prediction markets) |

### Variables de entorno críticas

```bash
# Cargar todas las variables:
set -a && source /opt/trading/config/.env && set +a

# Variables principales:
POSTGRES_USER=trading
POSTGRES_PASSWORD=Tr4d1ng_Ag3nt_2026!
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=trading_agent
REDIS_HOST=localhost
REDIS_PORT=6379
PAPER_TRADING=true
TELEGRAM_BOT_TOKEN=8179816401:AAHF3xprmPeauuOapGDD9idQrLsv8Dl2EYE
TELEGRAM_CHAT_ID=999936393
```

---

## 3. Agentes Activos

| Agente | Estado | Mercado | Sesión | Balance | Doc |
|---|---|---|---|---|---|
| **Trading Agent** | ✅ ACTIVO | Crypto/Metales (10 assets) | SESSION_011 | $1,000 | [AI_TRADING_AGENT.md](AI_TRADING_AGENT.md) |
| **Stocks Agent** | ✅ ACTIVO | NYSE/NASDAQ (Alpaca) | STOCKS_SESSION_011 | $1,000 | [AI_STOCKS_AGENT.md](AI_STOCKS_AGENT.md) |
| **Options Agent** | ✅ ACTIVO | BTC PUT OTM (Deribit) | OPTIONS_SESSION_001 | $1,717 | [AI_OPTIONS_AGENT.md](AI_OPTIONS_AGENT.md) |
| **PolySnipe** | ✅ ACTIVO | Up/Down 15m (Polymarket) | SNIPE_SESSION | $500 | [AI_POLYMARKET_SNIPE.md](AI_POLYMARKET_SNIPE.md) |
| **Grid Stable** | ✅ ACTIVO | ETH/BTC, LINK/BTC | SESSION_011 | — | — |
| **Pairs** | ✅ ACTIVO | GLD-SLV, BTC-ETH | — | — | — |
| **VIX** | ✅ ACTIVO | Volatilidad (SVXY) | — | — | — |
| **Homerun** | ✅ ACTIVO | Prediction markets (Docker) | Shadow mode | — | En evaluación |

### Agentes Desactivados

| Agente | Razón | Fecha |
|---|---|---|
| **Polymarket Agent** | ❌ -$985 acumulado, WR 27%, edge inexistente | May 19 |
| **Basis Trade Agent** | ❌ Bug crítico: drenó $346 en 5h (trade_monitor cerraba posiciones a $0) | May 20 |
| **Kalshi Arbitrage** | ❌ 0 trades, Kalshi API no funcional desde este VPS | May 20 |
| **BTC Direction** | ❌ WR 0%, PnL -$497 — reemplazado por PolySnipe | Legacy |

---

## 4. Estrategias Crypto Activas (strategy_engine.py)

| Estrategia | Tipo | Slots | PnL SESSION_011 | Fuente |
|---|---|---|---|---|
| **TREND_MOMENTUM** | SELL + BUY condicional | 2 | +$189 | Original v3 |
| **GRID_BOT** | Grid en RANGE/CHOPPY | 3 | +$1,142 | Original |
| **GRID_STABLE** | Grid pares estables | — | +$684 | Original |
| **SMC_ORDER_BLOCKS** | BUY+SELL ICT | 1 | +$101 (histórico) | GitHub 1590⭐ |
| **BTC_MICROSTRUCTURE** | BUY+SELL multi-indicator | 1 | +$120 (histórico) | GitHub 156⭐ |
| **EMA_RIBBON** | BUY trend-following | 1 | 0 trades | GitHub 15⭐ — incompatible con arquitectura SELL-only |

### DirectionGuard (crypto + stocks)

Sistema de auto-protección que bloquea direcciones (BUY/SELL) con WR < 30% en ≥15 trades. Redis-backed, cooldown 72h.

- **Crypto**: integrado en `strategy_engine.py` vía `crypto_is_allowed()`. Sin bloqueos activos.
- **Stocks**: integrado en `stocks_agent.py` vía `direction_guard_allowed()`. EEM/BUY bloqueado.

---

## 5. Servicios systemd

```bash
# Ver estado de todos:
systemctl status trading-agent options-agent polymarket-snipe stocks-agent dashboard-api dashboard-web trading-health grid-stable pairs-agent vix-agent

# Ver logs en tiempo real:
journalctl -u <servicio> -f
```

| Servicio | Archivo | Descripción |
|---|---|---|
| `trading-agent` | `scripts/run_trading.py` | Ciclo principal Trading (10 assets, incluye XAU/XAG reactivados) |
| `options-agent` | `scripts/run_options.py` | Theta Farming BTC PUTs |
| `polymarket-snipe` | `scripts/run_polymarket_snipe.py` | SNIPE Up/Down 15m |
| `stocks-agent` | `scripts/run_stocks.py` | NYSE/NASDAQ Momentum + Minervini |
| `dashboard-api` | `api/main.py` | FastAPI en :8000 |
| `dashboard-web` | `web/` | Next.js React en :3000 |
| `trading-health` | `scripts/health_check.py` | Health check cada 5min (15 checks, monitorea 8 agentes) |
| `grid-stable` | `agents/grid_stable_agent.py` | Grid pares estables ETH/BTC, LINK/BTC |
| `pairs-agent` | `agents/pairs_executor.py` | Pairs Trading GLD-SLV, BTC-ETH |
| `vix-agent` | `agents/vol_executor.py` | VIX Mean Reversion |

### Servicios Docker (Homerun)

```bash
cd /opt/homerun && docker compose ps      # estado
cd /opt/homerun && docker compose logs -f # logs
```

---

## 6. Comandos de diagnóstico rápido

```bash
# Contexto completo del sistema (USAR SIEMPRE AL INICIAR SESIÓN IA):
cd /opt/trading && venv/bin/python3 scripts/ai_context.py

# Estado de sesiones activas:
set -a && source config/.env && set +a
venv/bin/python3 -c "
from sqlalchemy import create_engine, text; import os
e = create_engine(os.environ['DB_URL'])
with e.connect() as c:
    r = c.execute(text(\"SELECT session_name, status, total_trades, winning_trades, final_balance-initial_balance as pnl FROM paper_sessions WHERE status='ACTIVE' ORDER BY started_at DESC\")).fetchall()
    [print(row) for row in r]
"

# Trades abiertos:
venv/bin/python3 -c "
from sqlalchemy import create_engine, text; import os
e = create_engine(os.environ['DB_URL'])
with e.connect() as c:
    r = c.execute(text(\"SELECT asset, strategy, side, entry_price FROM trades WHERE status='OPEN'\")).fetchall()
    print(f'{len(r)} trades abiertos'); [print(' ', row) for row in r]
"

# Redis cooldowns/halts/guards:
redis-cli keys 'cooldown:*' ; redis-cli keys 'halt:*' ; redis-cli keys 'direction_guard:*'

# Errores de todos los agentes:
journalctl -u trading-agent --since today --no-pager | grep -i error | tail -10

# Validación Strategy v1 vs v2:
journalctl -u trading-agent --since today --no-pager | grep "STRATEGY V2"
```

---

## 7. Estructura de archivos clave

```
/opt/trading/
├── agents/
│   ├── strategy_engine.py      # Orquestador + v2 comparison
│   ├── trade_monitor.py        # Monitorea trades abiertos, aplica trailing
│   ├── execution_agent.py      # Ejecuta órdenes (paper o real)
│   ├── grid_agent.py           # Grid Bot (RANGE/CHOPPY)
│   ├── grid_stable_agent.py    # Grid Stable Bot (ETH/BTC, LINK/BTC)
│   ├── stocks_agent.py         # Stocks agent + DirectionGuard
│   ├── options_agent.py        # Options theta farming
│   ├── polymarket_snipe.py     # SNIPE Up/Down 15m
│   └── vol_executor.py         # VIX Mean Reversion
├── strategies/
│   ├── base.py                 # 🆕 BaseStrategy (contrato v2)
│   ├── trend_momentum.py       # TREND_MOMENTUM v1 (original)
│   ├── trend_momentum_v2.py    # 🆕 TREND_MOMENTUM v2 (BaseStrategy)
│   ├── smc_order_blocks.py     # SMC Order Blocks (ICT)
│   ├── btc_microstructure.py   # BTC Microstructure
│   ├── ema_ribbon.py           # EMA Ribbon (inactivo: arquitectura SELL-only)
│   ├── breakout.py             # DESACTIVADO
│   ├── mean_reversion.py       # DESACTIVADO (0 wins paper)
│   └── theta_farming.py        # Options Theta Farming
├── core/
│   ├── direction_guard.py      # 🆕 DirectionGuard (crypto + stocks)
│   ├── market_regime.py        # Clasificador de régimen
│   ├── asset_profiles.py       # SL/TP/trailing por asset (incluye XAU/XAG)
│   ├── stocks_profiles.py      # Perfiles stocks (GLD/SLV con umbrales bajados)
│   ├── performance_guard.py    # Circuit breaker por estrategia
│   ├── paper_session_manager.py
│   ├── alpaca_session_manager.py
│   └── notifications.py        # Telegram
├── risk/
│   └── risk_manager.py         # RiskManager INMUTABLE
├── data/
│   ├── market_feed.py          # OHLCV (Kraken/OKX via CCXT)
│   └── polymarket_feed.py
├── config/
│   ├── exchange_config.yaml    # XAU/XAG reactivados en OKX (swap)
│   └── .env                    # Variables de entorno (no en git)
├── scripts/
│   ├── run_trading.py          # Entry point (get_open_trades excluye BASIS_TRADE)
│   ├── run_stocks.py           # Entry point stocks
│   ├── run_options.py
│   ├── run_polymarket_snipe.py
│   ├── health_check.py         # Health check 15 checks, 8 agentes, noise filter
│   └── ai_context.py
└── docs/
    ├── AI_MASTER.md            # Este archivo
    ├── STRATEGY_ARCHITECTURE_V2.md  # 🆕 Plan de adopción arquitectura Homerun
    ├── AI_TRADING_AGENT.md
    ├── AI_OPTIONS_AGENT.md
    ├── AI_STOCKS_AGENT.md
    └── CHANGELOG.md
```

### Homerun (prediction markets)

```
/opt/homerun/                    # Plataforma de prediction markets (Docker)
├── docker-compose.yml           # 7 contenedores (postgres, redis, backend, frontend, 3 workers)
├── .env                         # Puertos 3001/8001/5433/6380 (sin conflicto con Arthas)
└── backend/services/strategies/ # 15+ estrategias (basic, crypto, cross-platform, etc.)
```

---

## 8. Base de datos — Tablas principales

```sql
-- Trading Agent:
paper_sessions          -- sesiones paper (ACTIVE/CLOSED)
portfolio               -- estado del portafolio (balance, DD, PnL)
trades                  -- todos los trades (OPEN/CLOSED)
market_data             -- velas OHLCV cacheadas

-- Stocks Agent:
stocks_sessions         -- sesiones stocks paper
stocks_trades           -- trades individuales

-- Options Agent:
options_sessions        -- sesiones options
options_positions       -- posiciones (31 columnas)

-- Polymarket SNIPE:
snipe_trades            -- trades SNIPE 15m
snipe_sessions          -- sesiones snipe

-- Kalshi Arbitrage (legacy, sin uso):
kalshi_arbitrage        -- señales de arbitraje (0 trades)

-- Señales:
signals                 -- señales técnicas
```

---

## 9. Historial de decisiones importantes

| Fecha | Decisión | Razón |
|---|---|---|
| May 19 | **Polymarket Agent desactivado** | -$985 acumulado, WR 27%, edge inexistente |
| May 19 | **Basis Trade Agent desactivado** | Bug crítico: trade_monitor cerraba posiciones a $0, drenó $346 en 5h |
| May 19 | **Kalshi Arb Agent desactivado** | 0 trades, Kalshi API no funcional desde este VPS |
| May 19 | **XAU/XAG reactivados en crypto** | +$4,447 paper real en SESSION_008. Removidos por error basado en backtest con símbolo equivocado. Reactivados en OKX (swap): XAU/USD:USD, XAG/USDT:USDT |
| May 19 | **GLD/SLV umbrales bajados** | confluence_min 3→2, min_atr reducido. Solo 3 trades en 30 días. |
| May 19 | **DirectionGuard creado** | Bloqueo automático de direcciones con WR < 30% en ≥15 trades. Crypto + Stocks. |
| May 19 | **Health check expandido** | Monitorea 8 agentes (antes solo trading-agent). Noise filter para APIs externas. |
| May 19 | **Sesiones reseteadas a $1,000** | SESSION_011 (crypto) + STOCKS_SESSION_011 (stocks). Capital de validación pre-producción. |
| May 19 | **pnl_pct columna ampliada** | NUMERIC(8,6)→NUMERIC(10,6). Evita overflow con PnL ≥ 100%. |
| May 19 | **get_open_trades() excluye BASIS_TRADE** | Prevención de bug que causó el drenaje de $346. |
| May 19 | **Homerun desplegado** | Plataforma prediction markets en Docker. Shadow mode. Puerto 3001. |
| May 20 | **Strategy Architecture v2 — Etapa 1** | BaseStrategy + TrendMomentumStrategyV2 corriendo en paralelo. Validación 48h. |
| May 20 | **Alpaca API errores downgradeados** | ERROR→WARNING para 422/403 (manejados con fallback). |
| May 20 | **Stocks balance fix** | NameError `balance` corregido en fallback de ejecución SELL. |
| Abr 2026 | BUY bloqueado en TREND_UP | Backtest 2Y: -$6,151 |
| Mar 2026 | Binance → Kraken+OKX | HTTP 451 geo-restriction en este VPS |
| Mar 2026 | MEAN_REVERSION desactivada | 8 trades, 0 wins, -$569 |
| Abr 2026 | PREDICTION_LLM desactivado | 43 trades, 0 wins, -$582 |

---

## 10. Estado actual (Mayo 20, 2026 — Post-auditoría)

- **SESSION_011**: ACTIVA. $1,000. 10 assets incluyendo XAU/XAG reactivados. DirectionGuard activo en crypto.
- **STOCKS_SESSION_011**: ACTIVA. $1,000. DirectionGuard activo (EEM/BUY bloqueado). GLD/SLV con umbrales reducidos.
- **Homerun**: Desplegado en Docker. Shadow mode. Evaluando estrategias para posible adopción.
- **Strategy v2**: TrendMomentumStrategyV2 en validación paralela con v1. 0 divergencias de dirección.
- **Fortalezas**: 8 agentes activos. GRID_BOT y GRID_STABLE son los pilares (+$1,826 combinados). DirectionGuard protege de direcciones perdedoras. Health check monitorea todos los agentes.
- **Rumbo a producción**: Validar 3 meses con PF ≥ 1.5. SESSION_011 inició May 20.
- **Plan arquitectónico**: [STRATEGY_ARCHITECTURE_V2.md](STRATEGY_ARCHITECTURE_V2.md) — 4 etapas para adoptar patrones de Homerun.

---

## 11. Flujo de trabajo para nueva IA

```
1. Lee este archivo (AI_MASTER.md)
2. Ejecuta: cd /opt/trading && venv/bin/python3 scripts/ai_context.py
3. Revisa docs/STRATEGY_ARCHITECTURE_V2.md para el plan de migración
4. Para modificar parámetros: edita config/exchange_config.yaml o Redis keys
5. Para cambios de código: edita el archivo específico indicado en el doc
6. Para ver logs: journalctl -u <servicio> -n 50 --no-pager
7. Para reiniciar tras cambios: systemctl restart <servicio>
8. Siempre usar: /opt/trading/venv/bin/python3 (NUNCA python3 del sistema)
9. Homerun: cd /opt/homerun && docker compose ps / logs
```

---

## 12. ⚡ ACTIVACIÓN LIVE TRADING

> **LEER ESTO cuando se haya fondeado y se quiera activar trading real.**
> Capital objetivo: ~$300-500 USD. $220 → Kraken, resto → Alpaca.

### Prerequisitos

```bash
# 1. Confirmar 3 meses de paper con PF ≥ 1.5:
cd /opt/trading && set -a && source config/.env && set +a
venv/bin/python3 -c "
from sqlalchemy import create_engine, text; import os
e = create_engine(os.environ['DB_URL'])
with e.connect() as c:
    r = c.execute(text('''
        SELECT session_name, total_trades, winning_trades,
               ROUND((winning_trades::numeric/NULLIF(total_trades,0))*100,1) as wr_pct,
               final_balance - initial_balance as pnl
        FROM paper_sessions WHERE status=''CLOSED'' ORDER BY started_at DESC LIMIT 5
    ''')).fetchall()
    [print(row) for row in r]
"

# 2. Confirmar API keys de Kraken:
grep 'KRAKEN_API_KEY' /opt/trading/config/.env
```

### Pasos de activación

```bash
# Paso 1 — API keys en .env:
#   KRAKEN_API_KEY=<key real>  |  KRAKEN_SECRET=<secret real>

# Paso 2 — Activar live:
#   PAPER_TRADING=true  →  PAPER_TRADING=false
#   ENVIRONMENT=development → production
#   INITIAL_CAPITAL=220

# Paso 3 — Reiniciar agente:
systemctl restart trading-agent
journalctl -u trading-agent -n 20 --no-pager
# Confirmar que NO dice PAPER MODE

# Paso 4 — Verificar primera orden:
journalctl -u trading-agent -f
# Buscar: "LIVE ORDER PLACED"
```

### ⚠️ Qué NO hacer
- NO cambiar parámetros del RiskManager — calibrados con backtest 2Y
- NO activar OKX ni Deribit con capital insuficiente
- NO borrar paper_sessions — historial de validación del edge
- NO ejecutar estrategias no validadas en live

### Revertir a paper
```bash
sed -i 's/PAPER_TRADING=false/PAPER_TRADING=true/' /opt/trading/config/.env
systemctl restart trading-agent
```
