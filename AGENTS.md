# AGENTS.md — Arthas Trading System v1.1

> Entry point para sesiones de OpenCode. Lee esto primero, luego `docs/AI_MASTER.md`.
> **Tag**: `v1.1` — post-auditoría Mayo 20, 2026. Sesiones reseteadas a $1,000. DirectionGuard activo. Polymarket + Basis + Kalshi desactivados.

## Regla de oro v1.1

**Cualquier cambio de parámetros requiere:**
1. `git tag v1.X-stable` antes del cambio
2. 72h mínimo de observación post-cambio
3. Si PF empeora → `git checkout v1.X-stable` (revertir)
4. Si PF mejora 2 semanas → nuevo tag `v1.X+1-stable`

**NUEVO**: DirectionGuard aplica auto-bloqueo de direcciones perdedoras (WR < 30% en ≥15 trades). Editar `core/direction_guard.py` si se requiere ajustar thresholds. No desactivar sin validar.

**NUEVO**: `get_open_trades()` en `run_trading.py` excluye estrategias con risk management independiente (GRID_STABLE, BASIS_TRADE). Si una estrategia nueva abre trades en la tabla compartida, DEBE agregarse a esta lista de exclusión o sufrirá cierres forzados por el trade_monitor.

## Setup obligatorio al iniciar sesión

```bash
cd /opt/trading && venv/bin/python3 scripts/ai_context.py  # briefing completo del sistema
set -a && source config/.env && set +a                     # cargar env vars para cualquier DB query
```

**Python**: SIEMPRE `/opt/trading/venv/bin/python3`, NUNCA `python3` del sistema.

## Agentes activos (8)

| Agente | Servicio systemd | Entry point | DB principal | Sesión |
|--------|-----------------|-------------|-------------|--------|
| Trading (Crypto/Metales) | `trading-agent` | `scripts/run_trading.py` | `paper_sessions`, `trades` | SESSION_011 ($1,000) |
| Stocks (Alpaca) | `stocks-agent` | `scripts/run_stocks.py` | `stocks_trades` | STOCKS_SESSION_011 ($1,000) |
| Options (Theta Farming) | `options-agent` | `scripts/run_options.py` | `options_positions` | OPTIONS_SESSION_001 |
| PolySnipe (Up/Down 15m) | `polymarket-snipe` | `scripts/run_polymarket_snipe.py` | `snipe_trades` | SNIPE_SESSION |
| Grid Stable Pairs | `grid-stable` | `agents/grid_stable_agent.py` | `trades` | Compartida |
| Pairs Trading | `pairs-agent` | `agents/pairs_executor.py` | `trades` | Compartida |
| VIX Mean Reversion | `vix-agent` | `agents/vol_executor.py` | `trades` | — |
| Homerun (Docker) | `docker compose` | `/opt/homerun/` | PostgreSQL propio | Shadow mode |

### Agentes desactivados (Mayo 19-20)

| Agente | Razón |
|--------|-------|
| Polymarket Agent | -$985, WR 27%, edge inexistente |
| Basis Trade Agent | Bug: trade_monitor cerraba posiciones a $0 |
| Kalshi Arbitrage | 0 trades, API no funcional |

## Estrategias crypto activas

| Estrategia | Tipo | Slots | Fuente |
|-----------|------|-------|--------|
| TREND_MOMENTUM | SELL + BUY condicional | 2 | Original v3 |
| GRID_BOT | Grid en RANGE/CHOPPY | 3 | Original |
| GRID_STABLE | Grid pares estables | — | Original |
| SMC_ORDER_BLOCKS | BUY+SELL ICT | 1 | GitHub 1590⭐ |
| BTC_MICROSTRUCTURE | BUY+SELL multi-indicator | 1 | GitHub 156⭐ |
| EMA_RIBBON | BUY trend-following | 1 | GitHub 15⭐ — incompatible con SELL-only |

### DirectionGuard

Sistema de auto-protección en `core/direction_guard.py`:
- **Crypto**: `crypto_is_allowed(asset, direction)` — integrado en `strategy_engine.py`
- **Stocks**: `direction_guard_allowed(symbol, direction)` — integrado en `stocks_agent.py`
- Threshold: WR < 30% en ≥15 trades → bloqueo 72h
- Redis keys: `direction_guard:*` (stocks), `direction_guard_crypto:*` (crypto)

## Strategy Architecture v2

Plan de migración a patrón `BaseStrategy` (Homerun-inspired). Ver `docs/STRATEGY_ARCHITECTURE_V2.md`.

**Etapa 1 (ACTIVA)**: `TrendMomentumStrategyV2` corriendo en paralelo con v1. Comparación automática de señales. Buscar divergencias en logs:
```bash
journalctl -u trading-agent --since today --no-pager | grep "STRATEGY V2 DIVERGENCE"
```

## Dónde modificar parámetros (orden correcto)

1. **Parámetros de estrategia/riesgo**: `config/exchange_config.yaml` (crypto) o `core/stocks_profiles.py` (stocks)
2. **Perfiles por asset (SL/TP/trailing)**: `core/asset_profiles.py` (Crypto) o `core/stocks_profiles.py` (Stocks)
3. **Límites de riesgo inmutables**: `risk/risk_manager.py`
4. **Clasificador de régimen**: `core/market_regime.py`
5. **DirectionGuard thresholds**: `core/direction_guard.py`
6. **Tras cualquier cambio**: `systemctl restart <servicio>`

## Backtesting

```bash
cd /opt/trading && set -a && source config/.env && set +a

# Crypto (TrendMomentum)
venv/bin/python3 scripts/backtest.py --help

# Stocks
venv/bin/python3 scripts/backtest_stocks.py

# Options
venv/bin/python3 scripts/backtest_options.py

# Grid / Grid Stable
venv/bin/python3 scripts/backtest_grid.py
venv/bin/python3 scripts/backtest_grid_stable.py

# Pairs Trading
venv/bin/python3 scripts/backtest_pairs.py --pair GLD-SLV --years 5

# Minervini SEPA
venv/bin/python3 scripts/backtest_minervini.py --years 3
```

## Diagnóstico rápido

```bash
# ¿Hay halt activo?
redis-cli get halt:trading
redis-cli keys 'cooldown:*'
redis-cli keys 'direction_guard:*'

# Errores recientes
journalctl -u trading-agent --since today --no-pager | grep -i error | tail -20

# Validación Strategy v2
journalctl -u trading-agent --since today --no-pager | grep "STRATEGY V2"

# Trades abiertos
venv/bin/python3 -c "
from sqlalchemy import create_engine, text; import os
e = create_engine(os.environ['DB_URL'])
with e.connect() as c:
    r = c.execute(text(\"SELECT asset, strategy, side, entry_price FROM trades WHERE status='OPEN'\")).fetchall()
    print(f'{len(r)} trades abiertos'); [print(' ', row) for row in r]
"

# Sesiones activas
venv/bin/python3 -c "
from sqlalchemy import create_engine, text; import os
e = create_engine(os.environ['DB_URL'])
with e.connect() as c:
    r = c.execute(text(\"SELECT session_name, status, total_trades, winning_trades, final_balance-initial_balance as pnl FROM paper_sessions WHERE status='ACTIVE' ORDER BY started_at DESC\")).fetchall()
    [print(row) for row in r]
    r = c.execute(text(\"SELECT session_name, status, current_balance-initial_balance as pnl FROM stocks_sessions WHERE status='ACTIVE'\")).fetchall()
    [print(row) for row in r]
"

# Homerun
cd /opt/homerun && docker compose ps
```

## Gotchas críticos

- **Binance bloqueado** desde este VPS (HTTP 451). Usar Kraken/OKX/CCXT.
- **Mean Reversion y Prediction LLM están DESACTIVADAS** — 0 wins en paper.
- **BUY en TREND_MOMENTUM está BLOQUEADO** — backtest 2Y: -$6,151.
- **BREAKOUT_DOWN con `allow_trend=False`** — WR 29%, PnL -$1,590. Bloqueado.
- **XAU/XAG**: Reactivados en OKX como swaps (XAU/USD:USD, XAG/USDT:USDT). NO están en Kraken. Solo OKX.
- **get_open_trades() excluye GRID_STABLE y BASIS_TRADE**. Si un nuevo agente abre trades en la tabla `trades`, DEBE agregarse a esta exclusión.
- **DirectionGuard**: bloquea direcciones perdedoras automáticamente. Si un activo deja de operar, verificar `redis-cli keys 'direction_guard:*'`.
- **Cooldown post SL**: 60 min Crypto, 30 min Stocks. `redis-cli keys 'cooldown:*'`.
- **Halt persistente**: sobrevive reinicios (verificado desde DB). `redis-cli get halt:trading`.
- **Stocks solo opera en horario NYSE** (14:30-21:00 UTC, L-V).
- **PolySnipe: solo UP, solo BTC/ETH**. DOWN desactivado May 15.
- **Homerun puertos**: 3001 (frontend), 8001 (API), 5433 (PG), 6380 (Redis). Sin conflicto con Arthas.

## Protocolo para analizar un agente

```
1. journalctl -u <servicio> -n 100 --no-pager → ver qué está haciendo
2. redis-cli keys 'halt:*' && redis-cli keys 'cooldown:*' && redis-cli keys 'direction_guard:*'
3. DB query de trades recientes → performance real
4. Backtest si hay cambios propuestos → validar antes de tocar código
5. Si es cambio de parámetros: editar config → systemctl restart
6. Si es cambio de estrategia: editar .py → reiniciar
```

## Cambios que requieren backtest ANTES de aplicar

Cualquier modificación a:
- `MIN_SCORE`, umbrales RSI, zonas de entrada
- Parámetros de SL/TP/trailing
- `DEAD_HOURS_UTC`, `MAX_CONCURRENT_TRADES`
- Clasificador de régimen
- DirectionGuard thresholds
- Fórmulas de edge o Kelly sizing

## Servicios systemd

```bash
systemctl status trading-agent options-agent polymarket-snipe stocks-agent dashboard-api dashboard-web grid-stable pairs-agent vix-agent trading-health
```

Dashboard: `:3000` (Arthas) + `:3001` (Homerun). Tras cambios en React: `cd /opt/trading/web && npm run build && systemctl restart dashboard-api dashboard-web`.

## Documentación por agente

| Doc | Agente |
|-----|--------|
| `docs/AI_MASTER.md` | Índice maestro |
| `docs/STRATEGY_ARCHITECTURE_V2.md` | Plan de migración arquitectónica |
| `docs/AI_TRADING_AGENT.md` | Crypto/Metales |
| `docs/AI_OPTIONS_AGENT.md` | Options Theta |
| `docs/AI_POLYMARKET_SNIPE.md` | PolySnipe |
| `docs/AI_STOCKS_AGENT.md` | Stocks Alpaca |
| `docs/CHANGELOG.md` | Historial de cambios |
