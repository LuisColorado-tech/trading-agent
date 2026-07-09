# 📊 Journal: PAPER_SESSION_001

**Estado:** FAILED  
**Período:** 2026-03-16 06:04:05 → 2026-03-18 14:53:48  
**Balance:** $10,000 → $8,734 (-12.7%)  

> **Notas del operador:** Primera sesión. Sin dead hours, sin dedup, sin guard session-scoped. Mean reversion activo. Sesgo BUY fuerte. Cerrada por drawdown excesivo.


## Métricas Globales

| Métrica | Valor | Target |
|---------|-------|--------|
| Total trades | 38 | ≥30 |
| Win rate | 18.4% | ≥55% |
| Profit factor | 0.49 | ≥1.5 |
| Sharpe ratio | -1.09 | ≥1.5 |
| Max drawdown | -20.3% | ≥-12% |
| Expectancy | $-33.30/trade | >0 |
| Avg duration | 142 min | — |
| Total P&L | $-1,265.56 | — |

**🎓 Ready for live:** NO ❌

## Por Estrategia

| Estrategia | Trades | WR | P&L | Avg |
|------------|--------|-----|------|-----|
| MEAN_REVERSION | 8 | 0% | $-569 | $-71.1 |
| TREND_MOMENTUM | 30 | 23% | $-696 | $-23.2 |

## Por Asset

| Asset | Trades | WR | P&L | Sides |
|-------|--------|-----|------|-------|
| ETH | 7 | 14% | $-127 | BUY:7 |
| XAG | 4 | 25% | $-144 | SELL:3, BUY:1 |
| XAU | 3 | 0% | $-193 | BUY:3 |
| SOL | 7 | 14% | $-348 | BUY:7 |
| BTC | 17 | 24% | $-454 | BUY:17 |

## Por Hora (UTC)

| Hora | Trades | WR | P&L |
|------|--------|-----|------|
| 00:00 | 5 | 80% | $717 |
| 01:00 | 3 | 0% | $-112 |
| 02:00 | 6 | 0% | $-558 |
| 03:00 | 6 | 0% | $-632 |
| 05:00 | 3 | 0% | $-202 |
| 06:00 | 1 | 0% | $-100 |
| 07:00 | 1 | 100% | $166 |
| 10:00 | 2 | 0% | $-198 |
| 11:00 | 2 | 0% | $0 |
| 12:00 | 6 | 17% | $-312 |
| 17:00 | 2 | 50% | $67 |
| 18:00 | 1 | 0% | $-101 |

## Por Motivo de Cierre

| Motivo | Count | WR | P&L | Avg |
|--------|-------|-----|------|-----|
| TAKE_PROFIT | 7 | 100% | $1,209 | $172.7 |
| TRAILING_STOP | 4 | 0% | $0 | $0.0 |
| STOP_LOSS | 27 | 0% | $-2,475 | $-91.7 |

## Top 5 Mejores Trades

1. **BTC BUY** — $+180.74 (TREND_MOMENTUM, TAKE_PROFIT, 42.2 min)
2. **BTC BUY** — $+180.74 (TREND_MOMENTUM, TAKE_PROFIT, 43.9 min)
3. **ETH BUY** — $+177.78 (TREND_MOMENTUM, TAKE_PROFIT, 2.5 min)
4. **BTC BUY** — $+177.78 (TREND_MOMENTUM, TAKE_PROFIT, 60.4 min)
5. **BTC BUY** — $+166.67 (TREND_MOMENTUM, TAKE_PROFIT, 419.2 min)

## Top 5 Peores Trades

1. **BTC BUY** — $-113.84 (TREND_MOMENTUM, STOP_LOSS, 1.1 min)
2. **BTC BUY** — $-112.70 (TREND_MOMENTUM, STOP_LOSS, 1.1 min)
3. **ETH BUY** — $-112.03 (TREND_MOMENTUM, STOP_LOSS, 125.7 min)
4. **BTC BUY** — $-111.57 (TREND_MOMENTUM, STOP_LOSS, 1.1 min)
5. **BTC BUY** — $-110.46 (TREND_MOMENTUM, STOP_LOSS, 1.1 min)

## Recomendaciones

- WIN_RATE BAJA (18%): Revisar criterios de entrada — demasiadas señales falsas están pasando el filtro.
- PROFIT_FACTOR < 1 (0.49): El sistema pierde dinero neto. Las pérdidas son mayores que las ganancias.
- DRAWDOWN ALTO (-20.3%): Reducir position sizing o agregar filtro de régimen de mercado.
- ESTRATEGIA MEAN_REVERSION: P&L negativo ($-569 en 8 trades). Considerar desactivar o recalibrar.
- ESTRATEGIA TREND_MOMENTUM: P&L negativo ($-696 en 30 trades). Considerar desactivar o recalibrar.
- ASSET ETH: P&L negativo ($-127). Evaluar si este mercado es operable con la estrategia actual.
- ASSET SOL: P&L negativo ($-348). Evaluar si este mercado es operable con la estrategia actual.
- ASSET BTC: P&L negativo ($-454). Evaluar si este mercado es operable con la estrategia actual.
- HORAS NEGATIVAS (1:00, 2:00, 3:00, 5:00, 12:00 UTC): Considerar agregar a DEAD_HOURS.
- DEMASIADOS SL (27/38): SL puede estar muy ajustado, o las entradas son imprecisas.

## LLM (anomaly_check)

- Total llamadas: 41
- Anomaly checks: 0
- Flagged: 0 (0%)
- Avg confidence: 0

