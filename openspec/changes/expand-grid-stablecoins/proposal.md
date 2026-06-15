# Proposal: Grid Stable con stablecoins (USDC/USDT, DAI/USDC)

## Summary
Extender GRID_STABLE a pares de stablecoins. Spread microscópico (0.01-0.05%) pero altísima frecuencia (50-200 trades/dia). Capital ultra-seguro: las stablecoins no tienen riesgo direccional.

## Quantitative Evidence

### GRID_STABLE actual
| Par | Trades | PnL | avg/trade | trades/dia |
|-----|--------|-----|-----------|------------|
| ETH/BTC | 2,364 | +$1,319 | +$0.56 | 53.7 |
| LINK/BTC | 368 | +$212 | +$0.58 | 8.4 |

- Consistencia probada: +$1,531 en 2,732 trades, 46.4% WR
- avg win/loss ratio favorable: gana $1.50-1.90, pierde $0.50-0.65

### Stablecoins — simulación
| Par | Spread típico | Vol 24h | Grid levels | TP esperado | trades/dia est |
|-----|--------------|---------|-------------|-------------|---------------|
| USDC/USDT | 0.01-0.03% | $2B+ | 20 | 0.015% | 100-200 |
| DAI/USDC | 0.02-0.05% | $500M | 15 | 0.025% | 50-100 |
| USDT/DAI | 0.02-0.05% | $300M | 15 | 0.025% | 30-60 |

### Proyección conservadora
- Capital: $100 por par (riesgo mínimo)
- TP: $0.015-0.025 por trade (spread × size)
- Frecuencia: 30-100 trades/dia combinados
- **Retorno estimado: $0.45-2.50/dia → $13-75/mes → 13-75% ROI mensual sobre $100**
- Drawdown esperado: <1% (movimientos de stablecoin son microscópicos)

## Implementation
- 3 entries en el universo de `grid_stable_agent.py`
- Perfiles en `grid_stable_profiles.py`: niveles más densos (15-20), TP/SL más ceñidos
- 0 código nuevo — extender configuración existente
- Tiempo: 2-3 horas
- Riesgo: casi nulo (stablecoins no se mueven)

## Risk
- Si el spread es menor que las comisiones de Kraken → PnL negativo
- Paper 2 semanas antes de decidir
- Peor caso: -$5 en comisiones simuladas durante prueba
