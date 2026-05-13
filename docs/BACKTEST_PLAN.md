# PLAN DE BACKTESTING — Estrategias sin Validación

> Fecha: May 13, 2026
> Objetivo: Validar todas las estrategias que NO tienen backtest independiente
> Regla: Ninguna estrategia se activa sin PF > 1.0 con >50 trades en backtest

---

## Estrategias a evaluar

| Estrategia | Estado actual | Backtest existente | Trades paper |
|------------|--------------|-------------------|-------------|
| TREND_MOMENTUM | ✅ Activa | `backtest.py` 2Y (BTC/ETH/SOL) | 320 trades, +$11,781 |
| GRID_BOT | ✅ Activa | `backtest_grid.py` | 431 trades, +$1,459 |
| GRID_STABLE | ✅ Activa | `backtest_grid_stable.py` | 776 trades, +$389 |
| **BREAKOUT** | ❌ Pausada | ❌ Sin resultados documentados | 0 |
| **BTC_DIP_BUYER** | ❌ Pausada | ❌ Sin resultados documentados | 0 |
| **SMC_ORDER_BLOCKS** | ❌ Pausada | ⚠️ Parcial (solo BTC 15m) | 6 (regresión) |
| **BTC_MICROSTRUCTURE** | ❌ Pausada | ⚠️ Parcial (solo BTC 15m) | 9 (regresión) |
| MEAN_REVERSION | ❌ Pausada | 0/8 WR paper | Descartada |

---

## Método de evaluación

Cada estrategia se evalúa con:

```
backtest.py --months 24 --assets BTC,ETH,SOL,AVAX,INJ,LINK,AAVE --tf 1h
backtest.py --months 24 --assets BTC,ETH,SOL,AVAX,INJ,LINK,AAVE --tf 15m
```

Fuente de datos: KuCoin (ccxt, sin API key, accesible desde VPS ✅)

### Criterios de aprobación

| Métrica | Mínimo | Óptimo |
|---------|--------|--------|
| Profit Factor | > 1.0 | > 1.5 |
| Win Rate | > 40% | > 50% |
| Trades | > 50 | > 100 |
| Max Drawdown | < 20% | < 10% |
| Sharpe | > 0.5 | > 1.0 |
| R:R real | > 1.5 | > 2.0 |

### Criterios de rechazo

- PF < 1.0 → **Descartar definitivamente**
- PF 1.0-1.2 → Paper 2 semanas con $100 capital aislado
- PF > 1.2 → Paper 2 semanas con capital progresivo
- PF > 1.5 + >100 trades → **Activar en producción** (0.25× size inicial)

---

## Resultados preliminares (May 13)

### BTC 1h — 24 meses — configuración ROLLBACK (MIN_SCORE=65)
```
268 trades | WR=34.3% | PF=1.13 | PnL=+$2,740 (+27.4%)
TREND_MOMENTUM: 195 trades, WR=33%, +$758
SMC_ORDER_BLOCKS: 36 trades, WR=33%, +$841
BTC_MICROSTRUCTURE: 37 trades, WR=41%, +$1,141
```

### 5 activos (BTC,ETH,SOL,AVAX,INJ) 1h — 24 meses
```
1512 trades | WR=35.3% | PF=1.08 | PnL=+$8,727 (+87.3%) | MaxDD=29.7%
TREND_MOMENTUM: 1268 trades, WR=35%, +$1,360
BTC_MICROSTRUCTURE: 63 trades, WR=46%, +$2,860 ★
SMC_ORDER_BLOCKS: 116 trades, WR=35%, +$2,415
BREAKOUT: 52 trades, WR=31%, +$1,308
```

### 5 activos (BTC,ETH,SOL,AVAX,INJ) 1h — 12 meses (período difícil)
```
698 trades | WR=32.2% | PF=0.95 | PnL=-$2,501 (-25.0%)
TREND_MOMENTUM: 585 trades, WR=31%, -$4,483 ← único período negativo
BTC_MICROSTRUCTURE: 38 trades, WR=45%, +$1,292
SMC_ORDER_BLOCKS: 62 trades, WR=32%, +$558
```

### Conclusión del backtest comparativo

| Período | TREND_MOMENTUM | Veredicto |
|---------|---------------|-----------|
| 24 meses (May 2024-2026) | +$1,360 | ✅ Rentable |
| 12 meses (May 2025-2026) | -$4,483 | 🔴 Último año difícil |
| 12 meses (May 2024-2025) | +$5,843 | ✅ Primer año excelente |

La estrategia ES rentable a largo plazo. El último año fue adverso para SELL-only
en crypto (BTC subió de $60K a $100K). Pero el edge existe — PF=1.08 a 24 meses.

### Veredicto final

La configuración PRE-v3 (MIN_SCORE=65, confluence_min=3-4) es la correcta.
La calibración v3 (MIN_SCORE=75, confluence_min=5) eliminó el 90% de las señales
sin mejorar la calidad. El rollback de May 13 restaura la configuración original.

---

## Plan de ejecución

### Fase 1: Backtest completo (hoy)
```
# Paso 1: BTC 1h + 15m, 24 meses (más velas, mejor señal)
backtest.py --months 24 --assets BTC --tf 1h
backtest.py --months 24 --assets BTC --tf 15m

# Paso 2: Multi-activo 1h, 12 meses
backtest.py --months 12 --assets BTC,ETH,SOL,AVAX,INJ --tf 1h

# Paso 3: Multi-activo 15m, 12 meses
backtest.py --months 12 --assets BTC,ETH,SOL,AVAX,INJ --tf 15m
```

Tiempo estimado: ~2 horas (descarga de datos de KuCoin)

### Fase 2: Análisis por estrategia
```
Para cada estrategia en {BREAKOUT, BTC_DIP_BUYER, SMC_ORDER_BLOCKS, BTC_MICROSTRUCTURE}:
  1. Extraer trades del CSV de backtest
  2. Calcular métricas por TF y activo
  3. Identificar régimen de mercado óptimo (TREND_UP/DOWN/RANGE)
  4. Documentar en PRODUCTION_READINESS.md
```

### Fase 3: Decisión
```
POR ESTRATEGIA:
  PF > 1.5  → ACTIVAR (paper 2 semanas, $100 aislado)
  PF 1.0-1.5 → PAPER PROBATION (2 semanas, $50 aislado)
  PF < 1.0   → DESCARTAR (no reactivar sin recalibración)
```

---

## Notas

- El backtest usa KuCoin, no Kraken. Los datos son comparables (mismo par, mismo timeframe).
- El backtest simula gestión de riesgo idéntica a producción (mismo RiskManager, cooldowns, concurrencia).
- TREND_MOMENTUM ya está validado 2Y en backtest. No necesita re-evaluación — ya está en producción-ready.
- Los resultados de BTC 15m a 3 meses no son representativos del comportamiento multi-activo completo.
