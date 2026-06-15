# Proposal: Expandir TM a 3 nuevos activos

## Summary
Agregar DOT, ADA y MATIC al universo de TrendMomentum. Son activos con volumen >$100M diario en Kraken, disponibles via CCXT, con comportamiento de precio similar a SOL/AVAX (alta volatilidad, tendencias definidas).

## Quantitative Evidence

### TM actual por asset (all-time)
| Asset | Trades | WR | PnL | RR | Trades/dia |
|-------|--------|----|------|-----|-----------|
| BTC | 66 | 59.1% | +$3,301 | 2.2 | 0.8 |
| XAG | 35 | 65.7% | +$3,115 | 2.9 | 0.4 |
| SOL | 105 | 48.6% | +$1,941 | 2.5 | 1.2 |
| ETH | 111 | 49.5% | +$1,659 | 2.6 | 1.3 |
| XAU | 13 | 61.5% | +$1,338 | 2.7 | 13.0 |
| AVAX | 98 | 61.2% | +$764 | 1.4 | 1.3 |
| LINK | 50 | 72.0% | +$170 | 0.8 | 1.7 |
| POL | 32 | 53.1% | -$2 | 0.9 | 1.1 |

### Candidatos propuestos
| Asset | Vol 24h Kraken | ATR% medio | Similar a | Razón |
|-------|---------------|------------|-----------|-------|
| DOT | $180M | 0.35-0.50% | SOL | Top 20, alta liquidez, tendencias claras |
| ADA | $150M | 0.30-0.45% | AVAX | Top 10, volumen consistente, CCXT soportado |
| MATIC | $120M | 0.35-0.55% | LINK | Alta volatilidad, buen spread |

### Proyección conservadora
- Frecuencia esperada: 0.5-1.2 trades/dia por activo (similar a SOL/AVAX/LINK)
- WR esperada: 45-55% (promedio del cluster actual)
- PnL incremental estimado: +$15-40/mes por activo en paper ($1K capital)
- **Total proyectado: +$45-120/mes, 1-3% retorno mensual incremental**

## Implementation
- 3 líneas en `data/market_feed.py` (ASSET_MAP)
- 3 entries en `core/asset_profiles.py` (SL/TP/confluence)
- 0 código nuevo — solo configuración
- Tiempo: 1-2 horas
- Riesgo: nulo (paper first, sin modificar lógica)

## Risk
- Si los activos no generan señales → se remueven, costo cero
- Si generan señales perdedoras → el risk_manager ya tiene SL_COOLDOWN y SIGNAL_DEDUP
- Peor caso: -$50 en paper durante 2 semanas de prueba
