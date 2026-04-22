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
