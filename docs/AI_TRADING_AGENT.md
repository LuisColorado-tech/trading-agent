# TRADING AGENT — Documentación IA

> Agente principal de trading algorítmico. Opera TREND_MOMENTUM SELL en crypto y metales.
> Estado: **ACTIVO** — SESSION_008 en curso
> Última actualización: Abril 2026

---

## 1. Resumen ejecutivo

El Trading Agent es el agente más maduro del sistema. Usa TrendMomentum SELL para capturar movimientos bajistas en 7 assets crypto/metales en timeframe 15m.

**Resultados SESSION_008** (12 Apr – 22 Apr 2026):
- PnL: **+$1,246.55** sobre balance inicial ~$10,107
- Retorno: **+12.34%** en 10 días
- Trades totales: 227
- Win Rate: ~56%
- Profit Factor: **1.46**
- EV por trade: **$5.49**
- Días positivos: 7/11 (63.6%)
- Peor día: -$134 (-1.3%) → riesgo controlado
- ⚠️ **Concentración**: 74% del PnL vino de solo 2 días (Apr 18-19). Expectativa realista: 2-4%/mes.

---

## 2. Arquitectura del agente

```
scripts/run_trading.py           ← Entry point (systemd: trading-agent.service)
    │
    ├── agents/strategy_engine.py    ← Orquestador principal (loop cada 60s)
    │       ├── core/market_regime.py     ← Clasifica régimen por asset/TF
    │       ├── strategies/trend_momentum.py ← Evalúa señal SELL
    │       ├── core/asset_profiles.py   ← Parámetros por asset
    │       └── core/performance_guard.py ← Bloquea/probación
    │
    ├── risk/risk_manager.py         ← Autoridad final INMUTABLE
    │
    ├── agents/execution_agent.py    ← Ejecuta órdenes (paper/live)
    │       └── data/market_feed.py  ← OHLCV via CCXT (Kraken/OKX)
    │
    └── agents/trade_monitor.py      ← Monitor de posiciones abiertas
            └── core/paper_session_manager.py ← Contabilidad paper
```

**Ciclo de ejecución** (cada 60 segundos):
1. `strategy_engine` itera los 7 assets
2. Para cada asset: obtiene OHLCV 15m → calcula indicadores → clasifica régimen
3. Si régimen permite → evalúa señal TrendMomentum → pasa a RiskManager
4. RiskManager aprueba/rechaza → ExecutionAgent abre trade si aprobado
5. En paralelo: `trade_monitor` revisa trades abiertos → trailing stop → cierre

---

## 3. Assets operados

| Asset | Exchange | Par | Dirección | Notas |
|---|---|---|---|---|
| BTC | Kraken (prim.) / OKX | BTC/USDT | SELL only | Más estable, horas filtradas |
| ETH | Kraken / OKX | ETH/USDT | SELL only | — |
| SOL | Kraken / OKX | SOL/USDT | SELL only | Alta volatilidad |
| AVAX | Kraken / OKX | AVAX/USDT | SELL only | Buenas correcciones |
| LINK | Kraken / OKX | LINK/USDT | SELL only | Correlación baja con BTC |
| XAU | OKX | XAUT/USDT | SELL only | Tether Gold (proxy oro) |
| XAG | OKX | XAG/USDT:USDT | SELL only | Plata perpetuo (único exchange disponible) |

**Nota Binance**: bloqueado desde este VPS (HTTP 451 geo-restriction). Verificado 2026-03-16.

---

## 4. Estrategias — estado actual

| Estrategia | Estado | Razón |
|---|---|---|
| `TREND_MOMENTUM SELL` | ✅ ACTIVA | Edge validado en paper |
| `TREND_MOMENTUM BUY` | ❌ BLOQUEADA | Backtest 2Y: -$6,151. Bloqueado en `market_regime.py`: TREND_UP no permite BUY |
| `MEAN_REVERSION` | ❌ DESACTIVADA | Paper: 8 trades, 0 wins, -$569. Sin edge estadístico en 15m |
| `BREAKOUT` | ⚪ INACTIVA | `vol_ratio ≥ 2.0` muy estricto → casi nunca dispara |
| `BTC_DIP_BUYER` | ⚪ INACTIVA | Requiere BULL_DIP regime. Backtest: 29% WR, -$4,300 en 15m |
| `PREDICTION_LLM` | ❌ DESACTIVADA | `ENABLED=False` en `prediction.py`. Sin OpenAI API key. 43 trades, 0 wins, -$582 |
| `GRID_BOT` | ⚪ RANGE/CHOPPY | Se activa solo en mercados sin tendencia (Grid Agent) |

---

## 5. Señal TrendMomentum SELL — cómo funciona

**Archivo**: `strategies/trend_momentum.py`

**Indicadores usados** (15m OHLCV):
- EMA 20 / EMA 50 / EMA 200 (cruces)
- RSI (14)
- MACD (12/26/9)
- ATR (14)
- Volume ratio (vol actual / vol promedio)
- Bollinger Bands (ancho = volatilidad implícita)

**Criterios SELL** (todos deben cumplirse):
1. `trend_direction == 'DOWN'` (EMA20 < EMA50)
2. `RSI` entre 25 y 45 (precio bajando pero no sobrevendido extremo)
3. `MACD histograma < 0` (momentum bajista confirmado)
4. `score ≥ 65` (suma de indicadores alineados)
5. `confluence_min` cumplido por asset (ver tabla de perfiles)
6. Régimen permite TREND (ver sección 6)

**Score mínimo**: 65. Cada indicador alineado aporta puntos. El régimen TREND_DOWN añade +8 bonus.

---

## 6. Régimen de mercado — matriz de permisos

**Archivo**: `core/market_regime.py`

| Régimen | Condición | SELL | BUY | MeanRev | Breakout | Grid |
|---|---|---|---|---|---|---|
| `BREAKOUT_DOWN` | vol≥2.0, ATR≥1.5%, dirección DOWN | ✅ | ❌ | ❌ | ✅ | ❌ |
| `BREAKOUT_UP` | vol≥2.0, ATR≥1.5%, dirección UP | ✅ | ❌ (bloqueado) | ❌ | ✅ | ❌ |
| `TREND_DOWN` | dirección DOWN, trend_strength≥0.12, MACD<0 | ✅ (+8 bonus) | ❌ | ❌ | ❌ | ❌ |
| `TREND_UP` | dirección UP, trend_strength≥0.12, MACD>0 | ❌ | ❌ (bloqueado) | ❌ | ❌ | ❌ |
| `RANGE` | BB_width≤0.10, ATR≤1.2% | ❌ | ❌ | ❌ | ❌ | ✅ |
| `CHOPPY` | ninguna condición anterior | ❌ | ❌ | ❌ | ❌ | ✅ |

**Umbrales**:
- `_TREND_STRENGTH_MIN = 0.12` — umbral para activar TREND/BREAKOUT
- Nota: valor anterior era 0.18, demasiado restrictivo en rallies moderados

---

## 7. RiskManager — reglas INMUTABLES

**Archivo**: `risk/risk_manager.py`  
Estas constantes no se pueden cambiar en runtime. Son los límites de seguridad del sistema.

```python
MAX_RISK_PER_TRADE_PCT   = 0.005   # 0.5% del portafolio por trade
MAX_PORTFOLIO_EXPOSURE   = 0.05    # 5% máximo total expuesto
STOP_LOSS_ATR_MULTIPLIER = 1.5     # SL = entry - (1.5 × ATR)
TAKE_PROFIT_ATR_MULT     = 2.5     # TP = entry + (2.5 × ATR)
MAX_DRAWDOWN_STOP        = 0.10    # 10% drawdown → HALT total
MAX_CONCURRENT_TRADES    = 3       # Máximo trades abiertos
MIN_RR_RATIO             = 1.5     # R:R mínimo para aprobar trade
SL_COOLDOWN_MINUTES      = 60      # Espera tras SL (mismo asset)
TP_COOLDOWN_MINUTES      = 5       # Espera tras TP/TRAILING
DEAD_HOURS_UTC           = {1,2,3,4}  # Horas bloqueadas (0% WR histórico)
SIGNAL_DEDUP_HOURS       = 4       # No reentrar mismo asset+dirección en 4h tras SL
MAX_NOTIONAL_PCT         = 0.50    # Notional máx = 50% del balance
PAPER_HALT_COOLDOWN_HOURS = 3      # Paper: reanuda solo tras 3h de halt
PAPER_AUTO_RESUME_MAX_DD = 0.09    # Solo reanuda si DD < 9%
```

**Flujo de aprobación de un trade**:
1. ¿Hora bloqueada? (DEAD_HOURS_UTC) → rechazar
2. ¿Cooldown activo? (Redis `cooldown:{asset}`) → rechazar
3. ¿Dedup activo? (Redis `dedup:{asset}:{direction}`) → rechazar
4. ¿Trades abiertos ≥ MAX_CONCURRENT_TRADES? → rechazar
5. ¿Exposición total + nuevo trade > MAX_PORTFOLIO_EXPOSURE? → rechazar
6. Calcular position_size = MAX_RISK_PER_TRADE_PCT × balance / (entry - SL)
7. ¿R:R < MIN_RR_RATIO? → rechazar
8. ¿Halt activo? (drawdown > 10%) → rechazar (o esperar auto-resume en paper)
9. ✅ Aprobar

---

## 8. Perfiles de assets (AssetProfile)

**Archivo**: `core/asset_profiles.py`

| Asset | SL× | TP× | Trail@R | Step | Offset | ConfMin | HorasOK | HorasBloq |
|---|---|---|---|---|---|---|---|---|
| BTC | 1.5 | 2.5 | 0.75R | 0.30R | 0.75R | 3 | — | {0,20,22} |
| ETH | 1.5 | 2.5 | 0.75R | 0.30R | 0.75R | 3 | — | — |
| SOL | 1.8 | 3.0 | 1.0R | 0.40R | 1.0R | 4 | — | — |
| AVAX | 1.8 | 3.0 | 1.0R | 0.40R | 1.0R | 3 | — | — |
| LINK | 1.6 | 2.8 | 0.75R | 0.30R | 0.75R | 3 | — | — |
| XAU | 1.5 | 2.5 | 1.0R | 0.50R | 1.0R | 3 | — | — |
| XAG | 2.0 | 3.5 | 1.2R | 0.50R | 1.2R | 3 | — | — |

- `SL×` = multiplicador de ATR para Stop Loss
- `TP×` = multiplicador de ATR para Take Profit
- `Trail@R` = R mínimo para activar trailing stop
- `Step` = escalón de avance del trailing (en R)
- `Offset` = distancia SL dinámico al pico (en R)
- `ConfMin` = mínimo indicadores confluentes

---

## 9. PerformanceGuard — sistema de bloqueo automático

**Archivo**: `core/performance_guard.py`

Monitorea el rendimiento por estrategia y bloquea/pone en probación automáticamente.

**Reglas**:
- Si WR < 30% en últimas 10 trades → **bloqueo 4 horas** (no opera)
- Si WR entre 30-40% en últimas 5 trades → **probación** (opera al 50% de tamaño)
- Persiste en Redis: `guard:{strategy}:blocked`, `guard:{strategy}:probation`

**Ver estado actual**:
```bash
cd /opt/trading && venv/bin/python3 -c "
from core.performance_guard import StrategyPerformanceGuard
import os; from dotenv import load_dotenv
load_dotenv('config/.env')
db_url = f\"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}@{os.getenv('POSTGRES_HOST')}/{os.getenv('POSTGRES_DB')}\"
guard = StrategyPerformanceGuard(db_url)
for s in ['TREND_MOMENTUM', 'BREAKOUT', 'MEAN_REVERSION']:
    print(s, 'blocked:', guard.is_blocked(s), 'probation:', guard.is_on_probation(s))
"
```

---

## 10. Base de datos — esquema relevante

```sql
-- paper_sessions
CREATE TABLE paper_sessions (
    id SERIAL PRIMARY KEY,
    session_name VARCHAR(50) UNIQUE,
    status VARCHAR(20),          -- ACTIVE / CLOSED
    initial_balance NUMERIC,
    final_balance NUMERIC,
    total_trades INTEGER,
    winning_trades INTEGER,
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ
);

-- trades
CREATE TABLE trades (
    id SERIAL PRIMARY KEY,
    asset VARCHAR(10),
    side VARCHAR(5),             -- BUY / SELL
    strategy VARCHAR(50),
    entry_price NUMERIC,
    exit_price NUMERIC,
    stop_loss NUMERIC,
    take_profit NUMERIC,
    position_size NUMERIC,
    position_pct NUMERIC,
    pnl NUMERIC,
    status VARCHAR(20),          -- OPEN / CLOSED
    close_reason VARCHAR(50),    -- STOP_LOSS / TAKE_PROFIT / TRAILING / MANUAL
    paper_trade BOOLEAN,
    timestamp_open TIMESTAMPTZ,
    timestamp_close TIMESTAMPTZ
);

-- portfolio (snapshot por ciclo)
CREATE TABLE portfolio (
    id SERIAL PRIMARY KEY,
    total_balance NUMERIC,
    available_cash NUMERIC,
    exposure_pct NUMERIC,
    drawdown_pct NUMERIC,
    pnl_total NUMERIC,
    peak_balance NUMERIC,
    timestamp TIMESTAMPTZ
);
```

---

## 11. Cómo diagnosticar problemas

### El agente no abre trades
```bash
# Ver si hay halt activo:
redis-cli get halt:trading

# Ver logs de rechazos del RiskManager:
journalctl -u trading-agent -n 100 --no-pager | grep -E "REJECT|BLOCK|HALT|cooldown"

# Ver régimen de mercado actual:
cd /opt/trading && venv/bin/python3 scripts/ai_context.py | grep -A 30 "RÉGIMEN"
```

### Trades se cierran en SL constantemente
```bash
# Análisis por asset en sesión activa:
venv/bin/python3 -c "
from sqlalchemy import create_engine, text; import os
from dotenv import load_dotenv; load_dotenv('config/.env')
e = create_engine(os.environ['DB_URL'])
with e.connect() as c:
    r = c.execute(text('''
        SELECT asset, close_reason, COUNT(*), SUM(pnl)
        FROM trades WHERE status='CLOSED' AND timestamp_close > NOW() - INTERVAL '7 days'
        GROUP BY asset, close_reason ORDER BY asset, close_reason
    ''')).fetchall()
    [print(row) for row in r]
"
```

### Modificar parámetros de riesgo
- **Parámetros de régimen**: `core/market_regime.py` → constantes `_TREND_STRENGTH_MIN`
- **Parámetros de RiskManager**: `risk/risk_manager.py` → constantes al inicio del archivo
- **Parámetros por asset**: `core/asset_profiles.py` → cada `AssetProfile(...)`
- Después de cualquier cambio: `systemctl restart trading-agent`

---

## 12. Historial de cambios recientes (Abril 2026)

| Archivo | Cambio | Razón |
|---|---|---|
| `strategies/prediction.py` | `ENABLED = False` | 43 trades, 0 wins, -$582. Sin API key. |
| `core/market_regime.py` | TREND_UP: `allow_mean_reversion=False` | Paper: 8 trades, 0 wins, -$569 |
| `core/deribit_session_manager.py` | `_update_peak_and_drawdown(conn=None)` | Deadlock fix: reutiliza tx existente |
