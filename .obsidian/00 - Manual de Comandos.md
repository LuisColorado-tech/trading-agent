# 00 — Manual de Comandos

## 📋 Diagnóstico rápido

```bash
# Verificar TODO el sistema (ejecutar siempre al empezar)
cd /opt/trading && venv/bin/python3 scripts/spec_check.py

# Diagnóstico específico de TrendMomentum
venv/bin/python3 scripts/tm_pulse.py

# Contexto completo del sistema
venv/bin/python3 scripts/ai_context.py

# Trading Council (decisiones por comité)
venv/bin/python3 scripts/trading_council.py "tema a debatir"
```

## 🔧 Sistema

```bash
# Estado de todos los agentes
systemctl status trading-agent options-agent polymarket-snipe stocks-agent dashboard-api dashboard-web grid-stable pairs-agent vix-agent

# Reiniciar un agente
systemctl restart <servicio>

# Ver logs en vivo
journalctl -u <servicio> -f

# Últimos errores
journalctl -u <servicio> --since today --no-pager | grep -i error | tail -20

# Ver motivo de rechazo de señales (TM/Stocks)
journalctl -u <servicio> --since "30 min ago" --no-pager | grep "REJECTED:"
```

## 📊 Base de datos

```bash
# Cargar variables de entorno
set -a && source config/.env && set +a

# Sesiones activas
venv/bin/python3 -c "
from sqlalchemy import create_engine, text; import os
e = create_engine(os.environ['DB_URL'])
with e.connect() as c:
    r = c.execute(text(\"SELECT session_name, status, total_trades, final_balance-initial_balance as pnl FROM paper_sessions WHERE status='ACTIVE'\")).fetchall()
    [print(row) for row in r]
"

# Trades abiertos
venv/bin/python3 -c "
from sqlalchemy import create_engine, text; import os
e = create_engine(os.environ['DB_URL'])
with e.connect() as c:
    r = c.execute(text(\"SELECT asset, strategy, side, entry_price FROM trades WHERE status='OPEN'\")).fetchall()
    print(f'{len(r)} trades abiertos'); [print(row) for row in r]
"

# Portfolio
venv/bin/python3 -c "
from sqlalchemy import create_engine, text; import os
e = create_engine(os.environ['DB_URL'])
r = e.execute(text('SELECT total_balance, available_cash, drawdown_pct FROM portfolio ORDER BY timestamp DESC LIMIT 1')).fetchone()
print(f'Balance: \${float(r[0]):,.2f} | Cash: \${float(r[1]):,.2f} | DD: {float(r[2])*100:.1f}%')
"
```

## 🔴 Redis

```bash
# Halts activos
redis-cli get halt:trading

# Cooldowns post-SL
redis-cli keys 'cooldown:*'

# DirectionGuard bloqueos
redis-cli keys 'direction_guard:*'

# Limpiar todo (cuidado)
redis-cli FLUSHDB
```

## 📈 Backtesting

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

## 🐳 Homerun (PC externa Omarchy)

```bash
# Solo en la PC Omarchy, NO en el VPS
cd ~/homerun && docker compose ps
cd ~/homerun && docker compose logs -f
```

## 📁 Archivos clave

| Archivo | Qué es |
|---------|--------|
| `AGENTS.md` | Protocolo de diagnóstico + inventario |
| `specs/SPEC_SYSTEM.md` | Arquitectura y riesgos |
| `specs/SPEC_TREND_MOMENTUM.md` | TM: pipeline y métricas |
| `specs/SPEC_STOCKS.md` | Stocks: pipeline y métricas |
| `scripts/spec_check.py` | Verificador automático de SPECs |
| `scripts/tm_pulse.py` | Diagnóstico rápido TM |
| `scripts/trading_council.py` | Comité de traders (4 miembros) |
| `config/exchange_config.yaml` | Parámetros por exchange/activo |
| `core/asset_profiles.py` | SL/TP/trailing por activo crypto |
| `core/stocks_profiles.py` | Perfiles de acciones/ETFs |
| `risk/risk_manager.py` | RiskManager (autoridad final) |
