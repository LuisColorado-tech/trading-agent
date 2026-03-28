# 📊 Journal: PAPER_SESSION_003

**Estado:** CLOSED  
**Período:** 2026-03-18 21:37:23 → 2026-03-19 14:24:34  
**Balance:** $10,000 → $21,238 (+112.4%)  

> **Notas del operador:** Sesión con bug de duplicación post-TP. Mejoras previas: dead hours, signal dedup, session-scoped guard. Resultados inflados por loop de reapertura tras TP.


## Métricas Globales

| Métrica | Valor | Target |
|---------|-------|--------|
| Total trades | 48 | ≥30 |
| Win rate | 85.4% | ≥55% |
| Profit factor | 36.73 | ≥1.5 |
| Sharpe ratio | 9.25 | ≥1.5 |
| Max drawdown | -1.0% | ≥-12% |
| Expectancy | $234.12/trade | >0 |
| Avg duration | 32 min | — |
| Total P&L | $11,237.55 | — |

**🎓 Ready for live:** SÍ ✅

## Por Estrategia

| Estrategia | Trades | WR | P&L | Avg |
|------------|--------|-----|------|-----|
| TREND_MOMENTUM | 48 | 85% | $11,238 | $239.1 |

## Por Asset

| Asset | Trades | WR | P&L | Sides |
|-------|--------|-----|------|-------|
| BTC | 12 | 92% | $3,314 | SELL:12 |
| XAG | 13 | 100% | $3,153 | SELL:13 |
| SOL | 8 | 75% | $2,285 | SELL:8 |
| XAU | 9 | 78% | $1,451 | SELL:9 |
| ETH | 6 | 67% | $1,034 | SELL:6 |

## Por Hora (UTC)

| Hora | Trades | WR | P&L |
|------|--------|-----|------|
| 05:00 | 2 | 100% | $417 |
| 06:00 | 16 | 94% | $3,700 |
| 07:00 | 8 | 100% | $2,055 |
| 09:00 | 2 | 100% | $195 |
| 12:00 | 11 | 100% | $4,135 |
| 13:00 | 6 | 33% | $627 |
| 21:00 | 2 | 0% | $-100 |
| 22:00 | 1 | 100% | $208 |

## Por Motivo de Cierre

| Motivo | Count | WR | P&L | Avg |
|--------|-------|-----|------|-----|
| TAKE_PROFIT | 37 | 100% | $11,164 | $301.7 |
| TRAILING_STOP | 8 | 50% | $388 | $48.5 |
| SESSION_CLOSE | 1 | 0% | $0 | $0.0 |
| STOP_LOSS | 2 | 0% | $-315 | $-157.3 |

## Top 5 Mejores Trades

1. **BTC SELL** — $+420.63 (TREND_MOMENTUM, TAKE_PROFIT, 1.3 min)
2. **ETH SELL** — $+420.63 (TREND_MOMENTUM, TAKE_PROFIT, 1.2 min)
3. **SOL SELL** — $+420.63 (TREND_MOMENTUM, TAKE_PROFIT, 1.1 min)
4. **SOL SELL** — $+403.80 (TREND_MOMENTUM, TAKE_PROFIT, 1.1 min)
5. **BTC SELL** — $+403.80 (TREND_MOMENTUM, TAKE_PROFIT, 1.3 min)

## Top 5 Peores Trades

1. **BTC SELL** — $-214.52 (TREND_MOMENTUM, STOP_LOSS, 10.5 min)
2. **ETH SELL** — $-100.00 (TREND_MOMENTUM, STOP_LOSS, 341.2 min)
3. **XAU SELL** — $+0.00 (TREND_MOMENTUM, TRAILING_STOP, 63.3 min)
4. **SOL SELL** — $+0.00 (TREND_MOMENTUM, TRAILING_STOP, 8.5 min)
5. **SOL SELL** — $+0.00 (TREND_MOMENTUM, TRAILING_STOP, 3.8 min)

## Recomendaciones

- WIN_RATE ALTA (85%): Considerar aumentar TP target o reducir SL — podrías capturar más profit por trade.

## LLM (anomaly_check)

- Total llamadas: 49
- Anomaly checks: 0
- Flagged: 0 (0%)
- Avg confidence: 0

