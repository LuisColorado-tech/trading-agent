# Trading Agent — 🟢

## Servicio
- **systemctl**: `trading-agent`
- **Entry point**: `scripts/run_trading.py`
- **Sesión**: `SESSION_011` — $1,000
- **Activos**: BTC, ETH, SOL, AVAX, INJ, LINK, AAVE, POL, XAU, XAG

## Pipeline de ejecución (TM)

```
1. IndicatorEngine.calculate()   → OHLCV → indicadores
2. classify_market_regime()      → ¿TREND/BREAKOUT/CHOPPY?
3. strategy.score()              → ¿Score ≥ MIN_SCORE(65)?
4. direction_allowed()           → ¿Perfil permite dirección?
5. crypto_is_allowed()           → ¿DirectionGuard OK?
6. count_confluence()            → ¿≥ 2-3 indicadores alineados?
7. risk_manager.evaluate()       → ¿Cash? ¿Slots? ¿DD?
8. execution_agent.execute()     → Ejecutar orden (paper/live)
```

## Estrategias

| Estrategia | Tipo | Slots | Estado |
|-----------|------|-------|--------|
| [[TREND_MOMENTUM]] | SELL + BUY condicional | 2 | 🟡 Operando (post-fixes) |
| [[GRID_BOT]] | Grid en RANGE/CHOPPY | 3 | 🟢 Rentable |
| [[GRID_STABLE]] | Grid pares ETH/BTC LINK/BTC | — | 🟢 PF=3.97 |
| [[SMC_ORDER_BLOCKS]] | BUY+SELL ICT | 2 | 🟡 Bajo volumen |
| [[BTC_MICROSTRUCTURE]] | BUY+SELL multi | 2 | 🟡 Bajo volumen |
| EMA_RIBBON | BUY trend-following | 1 | ⚫ Inactivo |

## Comandos de diagnóstico

```bash
# Diagnóstico rápido TM
cd /opt/trading && venv/bin/python3 scripts/tm_pulse.py

# Ver señales generadas
journalctl -u trading-agent --since "30 min ago" --no-pager | grep "Opportunity:"

# Ver motivos de rechazo ← 👈 ESTO es lo más importante
journalctl -u trading-agent --since "30 min ago" --no-pager | grep "REJECTED:"

# Ver ejecuciones
journalctl -u trading-agent --since "30 min ago" --no-pager | grep "Executed trade"

# Ver trades TM hoy
venv/bin/python3 -c "
from sqlalchemy import create_engine, text; import os
e = create_engine(os.environ['DB_URL'])
r = e.execute(text(\"SELECT asset, side, ROUND(pnl::numeric,2), close_reason FROM trades WHERE strategy='TREND_MOMENTUM' AND status='CLOSED' AND timestamp_close::date = CURRENT_DATE\")).fetchall()
for row in r: print(row)
"
```

## Parámetros clave (NO tocar sin [[Trading Council]])

| Parámetro | Archivo | Valor |
|-----------|---------|-------|
| MIN_SCORE | trend_momentum.py | 65 |
| _TREND_STRENGTH_MIN | market_regime.py | 0.08 |
| confluence_min | asset_profiles.py | 2-3/activo |
| MAX_CONCURRENT TM | risk_manager.py | 2 |
| SL_COOLDOWN | execution_agent.py | 60 min |

## Gotchas

- **GRID_BOT excluido** de get_open_trades() y portfolio query (fix May 27)
- **GRID_STABLE excluido** de get_open_trades() (fix May 12)
- **BASIS_TRADE excluido** de get_open_trades() (fix May 20)
- **available_cash** puede ser negativo si los Grids no están excluidos → TM no opera
- **SL_COOLDOWN** bloquea reentrada 60 min post-SL
- **CHOPPY** bloquea TM si el régimen no detecta tendencia
- **XAU/XAG** en OKX swap (no en Kraken)

## SPEC

[[SPEC_TREND_MOMENTUM]]
