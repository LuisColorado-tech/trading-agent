# GitHub Strategy Hunter v2.0 — Plan de Expansión Multi-idioma

> Actualizado: May 16, 2026. Basado en aprendizajes del v1.0.

## Lecciones aprendidas (v1.0)

| Lección | Qué pasó | Regla nueva |
|---------|----------|-------------|
| Sin backtest = no activar | SMC/BTC_MICRO se activaron sin backtest independiente. Perdieron en paper. | **Ninguna estrategia entra sin >50 trades en backtest con PF > 1.0** |
| opencode no integra | Fases 2-5 creadas por opencode nunca se terminaron (sin systemd, sin config). | **Todo despliegue requiere: código + backtest + systemd + config + dashboard** |
| Más idiomas = más edge | Solo buscamos en inglés. Chinos/rusos/indios tienen mercados y enfoques distintos. | **Buscar en 中文, русский, हिन्दी, English** |
| Simplicidad gana | Grid Stable (la más simple) es la más rentable (101% ROI). SMC (la más compleja) perdió. | **Priorizar estrategias con <200 líneas de código** |
| Market-neutral es el santo grial | Basis Trade, Pairs y Kalshi Arb son riesgo cero en teoría. El desafío es la ejecución. | **Foco en arbitraje y market-neutral** |

## Pipeline de búsqueda multi-idioma

### Chino (中文) — Mercado más grande de crypto quant
```
Keywords: 量化交易, 套利, 网格交易, 加密货币, backtest, python
```
| Repo | ⭐ | Descripción | Resultado |
|------|-----|-------------|-----------|
| 51bitquant/howtrader | 910 | Framework quant crypto (fork VNPY) | Framework muy grande, no estrategia individual |
| *pendiente expandir* | — | — | — |

### Global — Estrategias encontradas y evaluadas

| Repo | ⭐ | Estrategia | ¿Adaptable? | Estado |
|------|-----|-----------|-------------|--------|
| **andrewboyley/crypto-trader** | 15 | EMA Ribbon (5 EMAs + RSI + Stochastic) | ✅ Simple, 70 líneas | **ADAPTADA May 16 → strategies/ema_ribbon.py** |
| eshan-kaul/PairsTrading-Crypto | 12 | Pares cointegrados Engle-Granger | ⚠️ Similar a nuestro Pairs actual | Evaluar mejora |
| johann-clouie/crypto-trading-bot | 4 | Funding rate arb multi-exchange | ❌ Muy complejo (websockets, orderbook) | Descartado |
| brokermr810/QuantDinger | 5333 | Plataforma quant completa | ❌ Reemplazaría todo el sistema | Arquitectura de referencia |
| Drakkar-Software/OctoBot | 5927 | Bot multi-estrategia | ❌ 118 issues, muy pesado | Descartado |

### EMA Ribbon — Evaluación de viabilidad

**Frecuencia de señal**: EMA alineado 22-36% de días. Con RSI<65: 13-22%.
Con 10 activos: 5-8 entradas/mes. Frecuencia ideal.

**Broker viability**: Cualquier exchange con spot trading. Binance, Kraken, OKX.
NO requiere futuros, NO requiere margen. Capital mínimo $100.

**Riesgo**: SL 5%, TP 15% (R:R 3:1). Con WR estimada 40-50%, EV positivo.
**Complementariedad**: BUY-only complementa SELL de TrendMomentum.
**Independencia**: Slots separados (1 para EMA_RIBBON), no compite con TREND_MOMENTUM.

### Ruso (Русский) — Fuerte tradición matemática
```
Keywords: алготрейдинг, арбитраж, криптовалюта, статистический арбитраж
```
| Repo | ⭐ | Descripción |
|------|-----|-------------|
| *pendiente buscar* | — | — |

### Indio (English + NSE/BSE) — Mercado de opciones masivo
```
Keywords: algo trading nse, options strategy india, banknifty python
```
| Repo | ⭐ | Descripción |
|------|-----|-------------|
| *pendiente buscar* | — | — |

### Global — Market Neutral / Arbitrage
```
Keywords: statistical arbitrage crypto, pairs trading, funding rate arbitrage
```
| Repo | ⭐ | Descripción |
|------|-----|-------------|
| brokermr810/QuantDinger | 5333 | AI quant platform |

## Criterios de selección v2.0

1. **Backtest incluido en el repo** — no aceptamos estrategias sin backtest
2. **<500 líneas de lógica core** — si es muy complejo, probablemente overfitted
3. **GitHub stars >50** o paper/publicación que lo respalde
4. **Funciona en spot/futuros estándar** — no requiere APIs exóticas
5. **Market-neutral > direccional** — el riesgo cero es el objetivo final

## Plan de ejecución

| Fase | Acción | Tiempo |
|------|--------|--------|
| 1 | Búsqueda completa en 4 idiomas (50+ repos) | 1 día |
| 2 | Análisis de top 10 por idioma | 1 día |
| 3 | Adaptación de código al framework Arthas | 2-3 días |
| 4 | Backtest 24 meses con datos reales | 1 día |
| 5 | Paper 2 semanas con capital aislado | 14 días |
| 6 | Activar solo si PF > 1.2 en paper | — |

## Meta

Encontrar **2-3 estrategias market-neutral** que complementen el core direccional (TrendMomentum + Grids). Con market-neutral no importa si el mercado sube o baja — siempre generas.
