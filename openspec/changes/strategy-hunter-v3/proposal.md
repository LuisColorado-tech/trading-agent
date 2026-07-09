# Proposal: Strategy Hunter v3 — Búsqueda en repos chinos y rusos

## Summary
El Strategy Hunter v1 encontró 1 estrategia viable de 5 evaluadas (20% hit rate). La v2 quedó incompleta. La v3 se enfoca en repos quant de China (中文) y Rusia (русский), donde hay estrategias no documentadas en inglés. La meta: encontrar 1-2 estrategias adaptables con backtest incluido.

## Quantitative Evidence

### Strategy Hunter v1 resultados
| Métrica | Valor |
|---------|-------|
| Repos explorados | ~20 |
| Estrategias evaluadas | 5 |
| Adaptadas con éxito | 1 (EMA Ribbon) |
| Hit rate | 20% |
| Tiempo total | ~3 semanas |
| Líneas de código producidas | 98 (ema_ribbon.py) |
| Resultado en paper | Inactiva (bloqueada por régimen, luego pausada) |

### v2 pendiente (NUNCA ejecutado)
| Idioma | Keywords | Repos candidatos | Estado |
|--------|----------|-----------------|--------|
| 中文 | 量化交易, 套利, 网格 | 51bitquant/howtrader (910⭐), vnpy (24K⭐) | Sin explorar |
| русский | алготрейдинг, арбитраж | Sin buscar | Sin explorar |
| English | stat arb, market neutral | eshan-kaul/PairsTrading-Crypto (12⭐) | Identificado, no evaluado |

### Proyección v3
- **Repos a explorar**: 30-50 (búsqueda multi-idioma)
- **Estrategias a evaluar**: 8-12 (las que tengan backtest)
- **Hit rate esperado**: 15-25% (1-3 estrategias viables)
- **Tiempo**: 3-4 semanas (part-time)
- **Costo**: $0 (solo tiempo de análisis)
- **Criterio de entrada**: backtest incluido + <500 líneas + mercado spot/futuros

## Implementation Plan
1. Semana 1: Búsqueda en GitHub con keywords en chino y ruso. Catalogar 30-50 repos.
2. Semana 2: Evaluar top 10 (backtest, legibilidad, adaptabilidad). Seleccionar 2-3 finalistas.
3. Semana 3: Adaptar la mejor a paper. Implementar en `strategies/`, con backtest independiente.
4. Semana 4: Paper trading. Si PF > 1.0 en 50+ trades → Council decide.

## Risk
- La mayoría de repos chinos usan exchanges locales (Binance China, OKX China) — verificar compatibilidad CCXT
- Estrategias pueden estar en chino — requiere traducción
- Hit rate puede ser 0% — pero el costo es solo tiempo
- Peor caso: 4 semanas sin estrategia nueva, pero con 30-50 repos documentados para referencia futura
