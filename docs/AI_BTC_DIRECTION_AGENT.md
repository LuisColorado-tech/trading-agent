# BTC DIRECTION AGENT — Multi-Timeframe en Polymarket

> Apuesta en mercados "Bitcoin Up or Down" en múltiples timeframes simultáneos.
> Estado: **⚠️ VIGILANCIA** — WR 27.6% en 105 trades reales (backfill Abr 2026)
> Última actualización: Abril 2026

---

## 1. Resumen ejecutivo

El BTC Direction Agent opera en mercados de Polymarket del tipo "¿Sube o baja BTC en los próximos X minutos?". Cubre 5 timeframes simultáneos: 5m, 15m, 4H (determinísticos por slug), y 1H/Daily (por scan paginado).

**Resultados reales** (corregidos con backfill en Abr 2026):
- Trades totales: **105**
- Wins: **29** / Losses: **76**
- Win Rate: **27.6%**
- PnL: **-$329**
- Estado: bajo vigilancia activa. Si WR no supera 40% en 3 semanas → pausar.

**⚠️ Bug histórico**: Antes del fix de Abr 2026, el agente usaba `/markets?conditionId=` para resolver outcomes, endpoint que **no filtraba correctamente** y devolvía mercados aleatorios. 105 trades quedaron marcados como EXP con PnL=0. El backfill los corrigió con los outcomes reales usando `/events?slug=`.

---

## 2. Arquitectura

```
btc_direction/run_btc_direction.py    ← Entry point (systemd: btc-direction.service)
    │
    └── btc_direction_executor.py     ← Orquestador principal (loop cada 30s)
            ├── btc_multifeed.py      ← Feed multi-TF: descubre 5 mercados activos
            ├── btc_direction_strategy.py ← Evalúa señales momentum multi-TF
            └── btc_direction_feed.py ← Feed single-TF (legacy, usado por executor)
```

**Ciclo** (cada 30 segundos):
1. `close_expired`: cerrar trades cuyo mercado ya resolvió → obtener outcome real
2. `scan_markets`: descubrir mercados activos en los 5 TFs via `BtcMultiFeed`
3. `evaluate_momentum`: evaluar señal técnica para cada mercado disponible
4. `execute`: si hay señal fuerte + ventana de entrada válida → abrir trade

---

## 3. Los 5 timeframes

### Timeframes determinísticos (slug calculable)

| TF | Duración slot | Plantilla slug | Ventana de entrada |
|---|---|---|---|
| 5m | 300s | `btc-updown-5m-{slot_ts}` | Primeros 2 min del slot, ≥60s restantes |
| 15m | 900s | `btc-updown-15m-{slot_ts}` | Primeros 10 min, ≥60s restantes |
| 4H | 14400s | `btc-updown-4h-{slot_ts}` | Primeras 2 horas, ≥5 min restantes |

**Cálculo del slot_ts** (determinístico):
```python
import time
slot_secs = 900  # para 15m
now_ts = int(time.time())
slot_ts = (now_ts // slot_secs) * slot_secs
slug = f'btc-updown-15m-{slot_ts}'
# Ejemplo: si ahora son las 14:07 UTC (ts=1745324820)
# slot_ts = (1745324820 // 900) * 900 = 1745324400
# slug = 'btc-updown-15m-1745324400'
```

### Timeframes por scan (no determinísticos)

| TF | Duración slot | Método | Ventana de entrada |
|---|---|---|---|
| 1H | 3600s | Scan paginado /markets (cache 5 min) | Primera mitad, ≥2 min restantes |
| Daily | 86400s | Scan paginado /markets (cache 5 min) | Primeras 6 horas, ≥10 min restantes |

---

## 4. Cómo resolver el outcome de un mercado

**CORRECTO** (post-fix Abr 2026):
```python
# btc_direction_feed.py y btc_multifeed.py:
def get_market_outcome(self, slug: str) -> Optional[str]:
    resp = requests.get(
        'https://gamma-api.polymarket.com/events',
        params={'slug': slug},   # ← CORRECTO: /events?slug=
        timeout=10
    )
    data = resp.json()
    if data and data[0].get('umaResolutionStatus') == 'resolved':
        prices = json.loads(data[0]['outcomes'][0].get('outcomePrices', '[]'))
        return 'YES' if prices and float(prices[0]) == 1.0 else 'NO'
    return None  # todavía no resuelto
```

**INCORRECTO** (antes del fix — NO usar):
```python
# Este endpoint NO filtraba por conditionId, devolvía mercados aleatorios:
requests.get('https://gamma-api.polymarket.com/markets',
             params={'conditionId': condition_id})  # ❌ BUGGY
```

**Por qué el bug**: El parámetro `conditionId` en `/markets` estaba siendo ignorado por la API de Gamma, devolviendo una lista de mercados aleatorios. El endpoint correcto para buscar por slug es `/events?slug=`.

---

## 5. Lógica de señal (btc_direction_strategy.py)

La estrategia usa momentum técnico multi-timeframe para determinar dirección:

**Indicadores**:
- EMA cruce (EMA3 vs EMA8 en ventana corta)
- RSI momentum (RSI > 55 = alcista, RSI < 45 = bajista)
- Volume ratio (volumen actual vs promedio últimas N velas)
- MACD histograma (positivo = alcista, negativo = bajista)

**Señal UP**: EMA3 > EMA8, RSI > 55, MACD > 0, volume_ratio > 1.1
**Señal DOWN**: EMA3 < EMA8, RSI < 45, MACD < 0, volume_ratio > 1.1

**Umbral mínimo**: `min_price_edge = 0.03` (3% de diferencia entre señal y precio actual del mercado)

---

## 6. Parámetros de riesgo

No están en `exchange_config.yaml` (el agente usa su propia config en `btc_direction_config.yaml`):

```yaml
# btc_direction/btc_direction_config.yaml
max_trade_usdc: 20.0      # Máximo $20 USDC por trade
max_open_trades: 2        # Máximo 2 trades abiertos simultáneos
min_price_edge: 0.03      # Edge mínimo sobre precio mercado (3%)
```

---

## 7. Ejecución de trades

**Archivo**: `btc_direction/btc_direction_executor.py`

```python
# Cómo pasa el slug al settlement (post-fix):
outcome = feed.get_market_outcome(trade['market_slug'])
# Antes pasaba trade['condition_id'] → bug
```

**Tablas DB**:
```sql
CREATE TABLE btc_direction_trades (
    id SERIAL PRIMARY KEY,
    market_slug VARCHAR(100),      -- slug del mercado (ej: btc-updown-15m-1745324400)
    condition_id VARCHAR(100),     -- ID hex del mercado en Polymarket
    timeframe VARCHAR(10),         -- 5m, 15m, 4h, 1h, daily
    direction VARCHAR(5),          -- UP / DOWN
    entry_price NUMERIC,           -- precio de entrada (0-1)
    amount_usdc NUMERIC,           -- USDC apostados
    outcome VARCHAR(5),            -- YES / NO / null (si no resolvió aún)
    pnl NUMERIC,                   -- ganancias/pérdidas en USDC
    status VARCHAR(10),            -- OPEN / CLOSED / EXP
    opened_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ
);
```

---

## 8. Backfill de Abril 2026

**Archivo**: `scripts/backfill_btc_direction.py`

Este script fue creado para corregir 105 trades que quedaron en estado `EXP` con `pnl=0` por el bug en `get_market_outcome`.

**Qué hizo**:
1. Obtuvo todos los trades `EXP` con `pnl=0` de la DB
2. Para cada uno, llamó a `get_market_outcome(market_slug)` con el endpoint correcto `/events?slug=`
3. Actualizó el outcome real (YES/NO) y calculó el PnL verdadero
4. Resultado: 29 wins / 76 losses → WR 27.6%, PnL = -$329

**Cómo ejecutarlo de nuevo** (si hay más trades EXP en el futuro):
```bash
cd /opt/trading
set -a && source config/.env && set +a
venv/bin/python3 scripts/backfill_btc_direction.py
```

---

## 9. Señales compartidas con Trading Agent

El BTC Direction Agent también lee la tabla `signals` del Trading Agent. Cuando hay una señal técnica fuerte de TREND_MOMENTUM SELL en BTC, el score influye en la decisión de apostar DOWN.

```sql
-- Señales recientes disponibles:
SELECT asset, direction, score, regime, timestamp
FROM signals
WHERE asset='BTC' AND timestamp > NOW() - INTERVAL '15 minutes'
ORDER BY timestamp DESC;
```

---

## 10. Diagnóstico del BTC Direction Agent

```bash
# Logs en tiempo real:
journalctl -u btc-direction -f

# Últimos trades (con outcomes reales):
set -a && source /opt/trading/config/.env && set +a
/opt/trading/venv/bin/python3 -c "
from sqlalchemy import create_engine, text; import os
e = create_engine(os.environ['DB_URL'])
with e.connect() as c:
    r = c.execute(text('''
        SELECT timeframe, direction, entry_price, amount_usdc, outcome, pnl, status, opened_at
        FROM btc_direction_trades
        ORDER BY opened_at DESC LIMIT 20
    ''')).fetchall()
    wins = sum(1 for row in r if row[6]=='CLOSED' and row[5] and row[5]>0)
    total = sum(1 for row in r if row[6]=='CLOSED')
    print(f'Últimos 20: {wins}/{total} wins')
    [print(' ', row) for row in r]
"

# WR y PnL global:
/opt/trading/venv/bin/python3 -c "
from sqlalchemy import create_engine, text; import os
e = create_engine(os.environ['DB_URL'])
with e.connect() as c:
    r = c.execute(text('''
        SELECT COUNT(*) total,
               SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) wins,
               SUM(pnl) total_pnl
        FROM btc_direction_trades WHERE status='CLOSED' AND pnl IS NOT NULL
    ''')).fetchone()
    wr = r[1]/r[0]*100 if r[0] else 0
    print(f'Total: {r[0]} | Wins: {r[1]} | WR: {wr:.1f}% | PnL: \${r[2]:+.2f}')
"

# Verificar que el endpoint de settlement funciona:
/opt/trading/venv/bin/python3 -c "
import requests, json
slug = 'btc-updown-15m-1745324400'  # reemplazar con slug real
r = requests.get('https://gamma-api.polymarket.com/events', params={'slug': slug}, timeout=10)
data = r.json()
if data:
    print('Status:', data[0].get('umaResolutionStatus'))
    outcomes = data[0].get('outcomes', [])
    if outcomes:
        prices = json.loads(outcomes[0].get('outcomePrices','[]'))
        print('Prices:', prices)
else:
    print('No data para slug:', slug)
"
```

---

## 11. Estado y decisiones futuras

| Métrica | Actual | Umbral | Decisión si no alcanza |
|---|---|---|---|
| Win Rate | 27.6% | ≥ 40% | Pausar el agente |
| PnL | -$329 | ≥ 0 | Revisar min_price_edge y sizing |
| Plazo evaluación | — | 3 semanas | Revisar en ~15 Mayo 2026 |

**Análisis por timeframe** (pendiente con más datos):
- 5m: mercados muy ruidosos, edge técnico muy bajo
- 15m: más señal que ruido, el original del sistema
- 4H: pocas señales pero potencialmente más calidad

**Posibles mejoras si WR sigue bajo**:
1. Desactivar 5m (demasiado ruido)
2. Aumentar `min_price_edge` a 5% (filtrar mercados más ajustados)
3. Requerir confluencia con la señal 1H del Trading Agent (no solo 15m)

---

## 12. Historial de cambios (Abril 2026)

| Archivo | Cambio | Razón |
|---|---|---|
| `btc_direction_feed.py` | `get_market_outcome(slug)` usa `/events?slug=` | `/markets?conditionId=` era buggy, ignoraba el param |
| `btc_multifeed.py` | Mismo fix | Consistencia |
| `btc_direction_executor.py` | `feed.get_market_outcome(trade['market_slug'])` | Antes pasaba `condition_id` → bug |
| `scripts/backfill_btc_direction.py` | Nuevo script | Backfill de 105 trades EXP con outcomes reales |
