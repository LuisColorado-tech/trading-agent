# AGENTS.md — Arthas Trading System v1.0

> Entry point para sesiones de OpenCode. Lee esto primero, luego `docs/AI_MASTER.md`.
> Cada línea responde: "¿Un agente lo ignoraría sin este aviso?"
> **Tag**: `v1.0-stable` — baseline de producción, Mayo 14 2026.

## Regla de oro v1.0

**Cualquier cambio de parámetros requiere:**
1. `git tag v1.X-stable` antes del cambio
2. 72h mínimo de observación post-cambio
3. Si PF empeora → `git checkout v1.X-stable` (revertir)
4. Si PF mejora 2 semanas → nuevo tag `v1.X+1-stable`

**Sin excepción.** La calibración v3 rompió TREND_MOMENTUM por 2 semanas porque no seguimos esto.

## Setup obligatorio al iniciar sesión

```bash
cd /opt/trading && venv/bin/python3 scripts/ai_context.py  # briefing completo del sistema
set -a && source config/.env && set +a                     # cargar env vars para cualquier DB query
```

**Python**: SIEMPRE `/opt/trading/venv/bin/python3`, NUNCA `python3` del sistema.

## Agentes activos (7)

| Agente | Servicio systemd | Entry point | DB principal |
|--------|-----------------|-------------|-------------|
| Trading (Crypto/Metales v3) | `trading-agent` | `scripts/run_trading.py` | `paper_sessions`, `trades` |
| Options (Theta Farming) | `options-agent` | `scripts/run_options.py` | `options_positions` |
| Polymarket Predictions | `polymarket-agent` | `scripts/run_polymarket.py` | `poly_positions` |
| PolySnipe (Up/Down 15m) | `polymarket-snipe` | `scripts/run_polymarket_snipe.py` | `snipe_trades` |
| Stocks (Alpaca) | `stocks-agent` | `scripts/run_stocks.py` | `stocks_trades` |
| Grid Stable Pairs | `grid-stable` | `agents/grid_stable_agent.py` | — |
| Pairs Trading | `pairs-agent` | `agents/pairs_executor.py` | `trades` (strategy='PAIRS_TRADING') |

## Dónde modificar parámetros (orden correcto)

1. **Parámetros de estrategia/riesgo**: `config/exchange_config.yaml` — NUNCA hardcodear en `.py`
2. **Perfiles por asset (SL/TP/trailing)**: `core/asset_profiles.py` (Crypto) o `core/stocks_profiles.py` (Stocks)
3. **Límites de riesgo inmutables**: `risk/risk_manager.py` — constantes al inicio del archivo
4. **Clasificador de régimen**: `core/market_regime.py`
5. **Tras cualquier cambio**: `systemctl restart <servicio>`

El RiskManager es **autoridad final**. Sus constantes (`MAX_RISK_PER_TRADE_PCT`, `MAX_DRAWDOWN_STOP`, etc.) no se sobreescriben desde YAML.

## Backtesting

Cada agente tiene su propio script. Todos requieren vars de entorno cargadas.

```bash
cd /opt/trading && set -a && source config/.env && set +a

# Crypto (TrendMomentum)
venv/bin/python3 scripts/backtest.py --help

# Stocks
venv/bin/python3 scripts/backtest_stocks.py

# Polymarket (análisis histórico + escaneo SL/TP óptimo)
venv/bin/python3 scripts/backtest_polymarket.py --all-sessions
venv/bin/python3 scripts/backtest_polymarket.py --scan-combos

# Options
venv/bin/python3 scripts/backtest_options.py

# Grid / Grid Stable
venv/bin/python3 scripts/backtest_grid.py
venv/bin/python3 scripts/backtest_grid_stable.py

# Pairs Trading (nuevo)
venv/bin/python3 scripts/backtest_pairs.py --pair GLD-SLV --years 5

# Value Zone (nuevo)
venv/bin/python3 scripts/backtest_value_zone.py
```

El backtest de Crypto usa datos locales de DB (`market_data`), no exchanges. Los demás usan datos mixtos.

## Diagnóstico rápido

```bash
# ¿Hay halt activo? (razón #1 por la que un agente no abre trades)
redis-cli get halt:trading
redis-cli keys 'cooldown:*'          # cooldowns post-SL
redis-cli keys 'guard:*'             # PerformanceGuard bloqueos

# Ver errores recientes de un agente
journalctl -u trading-agent --since today --no-pager | grep -i error | tail -20

# Trades abiertos ahora
venv/bin/python3 -c "
from sqlalchemy import create_engine, text; import os
e = create_engine(os.environ['DB_URL'])
with e.connect() as c:
    r = c.execute(text(\"SELECT asset, strategy, side, entry_price FROM trades WHERE status='OPEN'\")).fetchall()
    print(f'{len(r)} trades abiertos'); [print(' ', row) for row in r]
"

# Estado de sesión paper activa
venv/bin/python3 -c "
from sqlalchemy import create_engine, text; import os
e = create_engine(os.environ['DB_URL'])
with e.connect() as c:
    r = c.execute(text(\"SELECT session_name, status, total_trades, winning_trades, final_balance-initial_balance as pnl FROM paper_sessions ORDER BY started_at DESC LIMIT 3\")).fetchall()
    [print(row) for row in r]
"
```

## Gotchas críticos

- **Binance bloqueado** desde este VPS (HTTP 451 geo-restriction). Usar Kraken/OKX/CCXT.
- **Mean Reversion y Prediction LLM están DESACTIVADAS** — 0 wins en paper. No reactivar sin backtest positivo.
- **BUY en TREND_MOMENTUM está BLOQUEADO** — backtest 2Y: -$6,151.
- **BREAKOUT_DOWN con `allow_trend=False`** — WR 29%, PnL -$1,590. Bloqueado en `market_regime.py`.
- **Cooldown post SL**: tras un STOP_LOSS o TRAILING_STOP, el asset entra en cooldown (60 min Crypto, 30 min Stocks). Si un agente "no hace nada", revisar `redis-cli keys 'cooldown:*'` antes de tocar código.
- **Grid Stable bloquea TrendMomentum**: `get_open_trades()` en `run_trading.py` filtra `strategy != 'GRID_STABLE'` (fix May 12). Si TrendMomentum deja de abrir trades, verificar que Grid Stable trades no se estén contando en el RiskManager.
- **TrendMomentum evalúa 10 activos**: `ASSETS = ['BTC','ETH','SOL','AVAX','INJ','LINK','AAVE','POL','XAU','XAG']` en `run_trading.py:39`.
- **Halt persistente**: el drawdown halt sobrevive reinicios (verificado desde DB en cada ciclo). `redis-cli get halt:trading`.
- **Trailing stop**: no es binario — es dinámico progresivo por escalones de R (ver `docs/TRAILING_DINAMICO.md`). Parámetros por asset en `asset_profiles.py`.
- **Polymarket edge corregido en v3**: la fórmula anterior `abs(0.50 - price)` era una tautología. La actual usa `tf_conviction * 0.15` (conteo de señales macro 1h/4h). No revertir.
- **Polymarket `max_spread`**: antes configurado en YAML pero no aplicado en código (bug corregido v3). Ahora se fuerza en `polymarket_feed.py`.
- **`DEAD_HOURS_UTC`**: horas donde WR < 31% en backtest 24m. Si un asset no opera en ciertas horas, es por esto.
- **Stocks solo opera en horario NYSE** (14:30-21:00 UTC, L-V). Fuera de ese horario espera.

## Protocolo para analizar un agente

```
1. journalctl -u <servicio> -n 100 --no-pager → ver qué está haciendo ahora
2. redis-cli keys 'halt:*' && redis-cli keys 'cooldown:*' → bloqueos activos
3. DB query de trades recientes → performance real
4. Backtest si hay cambios propuestos → validar antes de tocar código
5. Editar exchange_config.yaml o el archivo de perfil correspondiente
6. systemctl restart <servicio>
```

## Cambios que requieren backtest ANTES de aplicar

Cualquier modificación a:
- `MIN_SCORE`, umbrales RSI, zonas de entrada en estrategias
- Parámetros de SL/TP/trailing en `asset_profiles.py` o `stocks_profiles.py`
- `DEAD_HOURS_UTC`, `MAX_CONCURRENT_TRADES`, límites de exposición
- Clasificador de régimen en `market_regime.py`
- Fórmulas de edge en Polymarket o Kelly sizing

Usar los scripts de backtest listados arriba. Sin excepción.

## Servicios systemd (9)

```bash
systemctl status trading-agent options-agent polymarket-agent polymarket-snipe stocks-agent dashboard-api dashboard-web grid-stable pairs-agent
```

Dashboard: Next.js en `:3000`, FastAPI en `:8000`. Tras cambios en React: `cd /opt/trading/web && npm run build && systemctl restart dashboard-api dashboard-web`.

## Documentación por agente

Cada agente tiene su doc detallada en `docs/AI_<AGENT>.md`. Leer el doc específico antes de modificar un agente.

| Doc | Agente |
|-----|--------|
| `docs/AI_TRADING_AGENT.md` | Crypto/Metales |
| `docs/AI_OPTIONS_AGENT.md` | Options Theta |
| `docs/AI_POLYMARKET_AGENT.md` | Polymarket Predictions |
| `docs/AI_POLYMARKET_SNIPE.md` | PolySnipe Up/Down 15m |
| `docs/AI_STOCKS_AGENT.md` | Stocks Alpaca |

## GitHub Strategy Hunter

Sistema de ingeniería inversa de estrategias. Tabla `repo_strategies`. Pipeline:

```bash
cd /opt/trading && venv/bin/python3 scripts/repo_strategy_hunter.py --phase discover
venv/bin/python3 scripts/repo_strategy_hunter.py --phase analyze
venv/bin/python3 scripts/repo_strategy_hunter.py --phase backtest
venv/bin/python3 scripts/repo_strategy_hunter.py --phase report
```
