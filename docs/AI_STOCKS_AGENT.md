# STOCKS AGENT — Documentación IA

> Agente de trading de acciones NYSE/NASDAQ vía Alpaca Markets.
> Estado: **ACTIVO v3** — STOCKS_SESSION_001 en curso
> Última actualización: Mayo 2026 (post-auditoría v3)

---

## 1. Resumen ejecutivo

Opera acciones y ETFs en NYSE/NASDAQ usando momentum + xsignal boost. Paper trading con Alpaca. 11 activos.

**Backtest 24 meses (v3, May 2024 → Abr 2026)**:
- Trades: 3,042 | Win Rate: 34.7% | Profit Factor: **1.18** | PnL: **+$925**
- SLV es el primer activo con PF≥1.30 (criterio live)

**STOCKS_SESSION_001**: $220 inicial. Operando en horario NYSE (14:30-21:00 UTC).

---

## 2. Arquitectura

```
scripts/run_stocks.py                    ← Entry point (systemd: stocks-agent.service)
    │
    ├── agents/stocks_agent.py           ← Orquestador principal
    │       ├── strategies/stocks_momentum.py  ← Acciones individuales (NVDA, TSLA...)
    │       ├── strategies/stocks_trend_etf.py ← ETFs (SPY, QQQ, GLD...)
    │       ├── core/stocks_profiles.py   ← Parámetros por símbolo
    │       └── data/stocks_feed.py       ← OHLCV via Alpaca + yfinance
    │
    ├── core/alpaca_session_manager.py   ← Auth API Alpaca (paper/live)
    └── riesgo integrado en stocks_agent.py
```

**Ciclo** (cada 5 min, solo NYSE abierto):
1. Verifica NYSE open (14:30-21:00 UTC, L-V)
2. Calcula macro bias (SPY/QQQ) con severidad
3. Para cada símbolo: OHLCV 1h → indicadores → estrategia → macro filter → execute
4. Monitor: trailing stop, SL/TP

---

## 3. Universo de activos

| Símbolo | Estrategia | SL× | TP× | Trail@R | min_atr_pct | Macro filter |
|---|---|---|---|---|---|---|
| NVDA | MOMENTUM | 1.2 | 2.5 | 0.75R | 0.008 | ✓ |
| TSLA | MOMENTUM | 1.3 | 2.8 | 1.0R | 0.010 | ✓ |
| AAPL | MOMENTUM | 1.0 | 2.0 | 0.75R | 0.006 | ✓ |
| META | MOMENTUM | 1.1 | 2.3 | 0.75R | 0.006 | ✓ |
| AMZN | MOMENTUM | 1.1 | 2.3 | 0.75R | 0.005 | ✓ |
| SPY | TREND_ETF | 0.9 | 1.8 | 0.75R | 0.004 | — |
| QQQ | TREND_ETF | 1.0 | 2.0 | 0.75R | 0.005 | — |
| GLD | TREND_ETF | 1.0 | 2.0 | 0.75R | 0.003 | — |
| SLV | TREND_ETF | 1.1 | 2.2 | 0.75R | 0.004 | — |
| EEM | TREND_ETF | 1.1 | 2.2 | 0.75R | 0.004 | ✓ |
| EWJ | TREND_ETF | 0.9 | 1.8 | 0.75R | 0.003 | ✓ |

---

## 4. Estrategias

### STOCKS_MOMENTUM (acciones individuales)

**MIN_SCORE = 65**. Evalúa BUY y SELL simultáneamente.

**BUY scoring** (máx 118):
- EMA20 > EMA50 (+25), strong trend (+10)
- Price > EMA20 (+15)
- RSI 45-68 (+20), RSI>72 penaliza (-15)
- MACD bull (+15), Vol > 1.5× (+15) o > 1.2× (+7)
- Room to BB upper (+10), Above VWAP (+8)

**SELL scoring** (máx 118):
- EMA20 < EMA50 (+25), strong trend (+10)
- Price < EMA20 (+15)
- RSI 28-48 (+20), RSI<28 penaliza (-15)
- MACD bear (+15), Vol > 1.5× (+15) o > 1.2× (+7)
- Near BB upper (+10), Below VWAP (+8)

### STOCKS_TREND_ETF (ETFs)

Ídem MOMENTUM pero con umbrales más suaves:
- Vol BUY 1.2× (vs 1.5), SELL 1.3×
- RSI BUY 40-65 (vs 45-68), SELL 30-52 (vs 28-48)
- bb_pct room < 0.75 (vs 0.70)

---

## 5. Parámetros de riesgo

```python
MAX_CONCURRENT_TRADES = 3
MAX_RISK_PER_TRADE_PCT = 0.01       # 1% del balance
MAX_PORTFOLIO_EXPOSURE = 2.0        # 200% (fractional shares)
MAX_NOTIONAL_PER_TRADE = 0.80       # máx 80% balance por trade
MAX_DRAWDOWN_STOP = 0.10            # halt si DD ≥ 10%
MIN_CONFLUENCE = 3                  # indicadores alineados mínimos
XSIGNAL_LOOKBACK_HOURS = 48         # ventana de xsignals boost
```

---

## 6. Mejoras v3 (Mayo 2026)

| # | Cambio | Impacto |
|---|---|---|
| **Trailing stop** | Implementado en `_monitor_open_trades()`. Trackea high/low, activa a partir de `trailing_activation_r`, cierra con `trailing_offset_r × risk` | +0.15-0.25 PF (estimado) |
| **XSignal boost direccional** | Solo aplica boost a la dirección alineada con el xsignal, no a ambas | +0.05-0.10 PF |
| **min_atr_pct subido** | AAPL 0.004→0.006, SPY 0.002→0.004, QQQ 0.003→0.005 | Filtra entradas en ruido |
| **Macro bias con gradiente** | BEAR severo (>1% bajo SMA10) bloquea BUY. BEAR leve (0.1-1%) permite BUY con score≥80 | Recupera oportunidades |
| **blocked_hours_utc** | Respeta bloqueo por hora definido en StocksProfile | Evita gaps de apertura |

---

## 7. Diagnóstico

```bash
# Estado del agente:
systemctl status stocks-agent

# Logs en tiempo real:
journalctl -u stocks-agent -f

# Status rápido:
cd /opt/trading && venv/bin/python3 scripts/run_stocks.py --status

# Trades abiertos:
venv/bin/python3 -c "
from sqlalchemy import create_engine, text; import os
from dotenv import load_dotenv; load_dotenv('config/.env')
e = create_engine(os.environ['DB_URL'])
with e.connect() as c:
    r = c.execute(text(\"SELECT symbol, direction, entry_price, pnl, status FROM stocks_trades ORDER BY opened_at DESC LIMIT 10\")).fetchall()
    [print(dict(row._mapping)) for row in r]
"
```

---

## 8. Criterios para live

- 4 semanas paper con PF ≥ 1.3
- 20+ trades cerrados
- Max DD ≤ 8%
- Macro bias BULL o NEUTRAL

---

## 9. Changelog

| Fecha | Cambio |
|---|---|
| 2026-05-01 | v3: trailing stop, xsignal fix, ATR filters, macro gradient, blocked hours |
| 2026-04-28 | Bugs corregidos: NameError `strategy_name`, Alpaca 422 fractional SELL, Decimal aritmética |
| 2026-04-23 | STOCKS_SESSION_001 iniciada |
