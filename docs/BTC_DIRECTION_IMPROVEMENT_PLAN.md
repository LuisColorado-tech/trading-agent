# BTC DIRECTION AGENT — Plan de Mejora

> Fecha: Mayo 2026 | Estado actual: 183 trades, WR=0%, PnL=-$497.52

---

## 1. Diagnóstico: por qué la estrategia actual falla

### Arquitectura actual
```
signals table (market_scanner)     Polymarket markets
        │                                  │
        ▼                                  ▼
 momentum 10m (BUY/SELL ratio)     price_up / price_down
        │                                  │
        └──────────┬───────────────────────┘
                   ▼
          edge = 0.50 - price
          conf = 0.5×momentum + 0.5×edge
                   │
                   ▼
         Si edge ≥ 0.05 → ejecutar trade
```

### Fallas identificadas

| # | Falla | Impacto |
|---|-------|---------|
| 1 | **Señal momentum de 10m no predice outcome binario** | La tabla `signals` detecta cruces EMA/RSI/Bollinger para trading direccional 15m. Pero Polymarket resuelve en un timestamp exacto (ej: ¿BTC>$78K a las 3:15pm?). El momentum de los últimos 10 minutos no predice el precio en el segundo exacto 5-900 minutos después. Es como predecir el resultado de un penal viendo los primeros 2 minutos del partido. |
| 2 | **Edge mínimo 5% insuficiente** | Con fees + slippage de Polymarket (~1-2%), el breakeven real requiere edge >8%. El mercado ajusta precios rápido. |
| 3 | **Sin filtro por volatilidad/ATC** | Entra en mercados ultra-volátiles donde el precio es ruido puro. |
| 4 | **Sin backtesting real** | La configuración se ajustó reactivamente a pérdidas (max_trade 20→5, edge 0.03→0.05) sin validación histórica. |
| 5 | **0 wins en 183 trades** | La estrategia nunca acertó una dirección. Es estructuralmente inviable. |

### Conclusión
**La estrategia actual no tiene edge.** 0% WR en 183 trades no es mala suerte, es una señal de que el modelo de señal (momentum 10m → outcome binario con slot de 5m-24h) no funciona. **Requiere reemplazo completo.**

---

## 2. Estrategias viables encontradas en GitHub

### Tier 1 — SNIPE (late-entry) — ⭐ RECOMENDADA para empezar

**Repo**: [LuciferForge/polymarket-btc-autotrader](https://github.com/LuciferForge/polymarket-btc-autotrader)

| Métrica | Valor |
|---------|-------|
| **WR** | 94% (17W/1L documentado) |
| **Mecánica** | Entrar en min 13-14.5 de un slot 15m comprando el lado ganador a $0.93-$0.97 |
| **Riesgo** | Muy bajo — compras a precio casi-resuelto |
| **Capital min** | $300-500 |
| **Rentabilidad** | ~2-7% ROI por trade exitoso (comprar a $0.93, cobrar $1.00) |
| **Complejidad** | Baja — ~300 líneas de Python |
| **Dependencias** | `py-clob-client` (oficial de Polymarket) |

**Ventajas**: 
- No predice nada — solo compra el outcome que ya es casi seguro
- Fácil de implementar, reutiliza la infraestructura existente de Polymarket feed
- WR altísima, riesgo mínimo

**Desventajas**:
- Pocas oportunidades/día (solo cuando el precio llega a ≥0.93 en el min 13-14)
- ROI pequeño por trade — necesitas volumen

---

### Tier 2 — YES+NO Arbitrage — riesgo CERO

**Repo**: [LuciferForge/polymarket-btc-autotrader](https://github.com/LuciferForge/polymarket-btc-autotrader) (mismo repo, estrategia ARB)

| Métrica | Valor |
|---------|-------|
| **WR** | 100% (risk-free por construcción) |
| **Mecánica** | Cuando price_yes + price_no < $0.985, compras AMBOS lados. Al resolverse, uno vale $1.00, el otro $0.00 → profit = $1.00 - costo |
| **Capital min** | $1,000 |
| **Rentabilidad** | ~1-3% por arbitraje |
| **Complejidad** | Baja |
| **Dependencias** | `py-clob-client` |

**Ventajas**: Sin riesgo direccional, 100% WR garantizada.

**Desventajas**: Oportunidades escasas, capital inmovilizado hasta resolución del mercado.

---

### Tier 3 — Kelly Criterion + Multi-Indicador (Weather-style adaptado a Crypto)

**Repo**: [suislanchez/polymarket-kalshi-weather-bot](https://github.com/suislanchez/polymarket-kalshi-weather-bot) (287 stars)

| Métrica | Valor |
|---------|-------|
| **WR** | ~55-60% estimado |
| **Mecánica** | 4 indicadores (RSI, momentum multi-TF, VWAP, market skew) → señal ponderada. Requiere ≥2 de 4 alineados. Kelly fraccional (0.15) para sizing. Edge > 2% para operar. |
| **Capital min** | $500 |
| **Rentabilidad** | $1,800 simulado en backtest |
| **Complejidad** | Media |
| **Dependencias** | `py-clob-client`, OHLCV feed |

**Ventajas**: Marco de backtesting incluido. Pero requiere validación en crypto (la implementación original es para weather, no crypto).

---

### Tier 4 — Multi-Strategy Bot (4 estrategias en 1)

**Repo**: [Naeaerc20/Polymarket-Multi-Strategy-Bot](https://github.com/Naeaerc20/Polymarket-Multi-Strategy-Bot)

Incluye SNIPE, ARB, Copy-Trade, y RSI+VWAP Signal en un solo bot. Buena arquitectura pero código menos pulido.

---

## 3. Inversión mínima requerida

### Escenarios de capital

| Estrategia | Capital mínimo | Capital recomendado | ROI mensual estimado |
|------------|---------------|---------------------|----------------------|
| **SNIPE solo** | $300 | $500 | 5-15% |
| **ARB solo** | $500 | $1,000 | 3-8% |
| **SNIPE + ARB** | $500 | $800 | 8-20% |
| **Kelly Multi-Ind** | $500 | $1,000 | -5% a +15% (alta variabilidad) |

### Para el plan de fondeo ($300 USDC total)
Con $300 divididos así:
- **$200 → SNIPE** (4-5 operaciones/mes a ~$50 cada una, ganancia ~$2-7 por trade)
- **$100 → ARB** (1-2 oportunidades/semana, requiere más capital para ser rentable)

Recomendación realista: si solo hay $300 para TODO el sistema, la mejor asignación es:
- **$200 → Trading Agent** (ya tiene PF=1.08, edge validado)
- **$80 → Polymarket → SNIPE** (estrategia de menor riesgo)
- **$20 → reserva**

---

## 4. Plan de implementación — Ruta recomendada

### Fase 1: Reemplazar BTC Direction con SNIPE (1-2 días)
1. Clonar/copiar la lógica SNIPE de `polymarket-btc-autotrader`
2. Adaptar a nuestra infraestructura (DB, Redis, systemd)
3. Validar en paper 2 semanas
4. Objetivo: WR ≥ 80%, PnL positivo

### Fase 2: Agregar ARB como estrategia complementaria (1 día)
1. Implementar monitor de YES+NO spreads en el mismo agente
2. Ejecutar solo cuando spread sea favorable (< $0.985)
3. Paper 1 semana

### Fase 3 (opcional): Kelly Multi-Indicador (3-5 días)
1. Implementar los 4 indicadores con señales de nuestra DB
2. Backtesting con datos históricos de Polymarket
3. Solo activar si backtest muestra PF ≥ 1.3

---

## 5. Backtesting

### Lo que se puede backtestear
- **SNIPE**: Simulable con datos históricos de precios de Polymarket. Verificar cuántas veces el precio YES llegó a ≥0.93 en min 13-14 de cada slot 15m en los últimos 30 días.
- **ARB**: Simulable con spreads históricos. Verificar frecuencia y magnitud de oportunidades.
- **Kelly Multi-Ind**: Requiere OHLCV histórico + precios de Polymarket. Más complejo pero factible.

### Script de validación rápida (SNIPE)
```bash
cd /opt/trading
venv/bin/python3 -c "
# Simular SNIPE en datos históricos: 
# ¿Cuántos slots 15m de los últimos 7 días habrían dado profit?
# Para cada slot: si price_yes ≥ 0.93 en min 13-14 y outcome fue YES → win
# Usar la tabla poly_markets (ya tiene outcomes)
"
```

---

## 6. Comparativa: mantener vs reemplazar

| | Estrategia actual | SNIPE | ARB |
|---|---|---|---|
| WR | 0% | 94% | 100% |
| Riesgo direccional | Alto | Muy bajo | Cero |
| Oportunidades/día | 5-10 | 1-3 | 0-3 |
| Capital/día inmovilizado | Variable | Bajo (min 13-14) | Hasta resolución |
| Complejidad | Ya implementada | Baja | Baja |
| Mantenimiento | Alto (requiere ajustes) | Bajo | Mínimo |

---

## 7. Recomendación final

**Reemplazar completamente la estrategia actual.** No tiene sentido intentar reparar un sistema con 0% WR en 183 trades. La evidencia estadística es contundente.

**Plan concreto:**
1. **Parar el servicio `btc-direction`** — está quemando recursos sin generar valor
2. **Implementar SNIPE como nuevo agente** `polymarket-snipe` — basado en `polymarket-btc-autotrader`
3. **Paper 2 semanas** con $500 balance simulado
4. **Si WR ≥ 80%:** activar con $50-80 reales del fondeo de $300
5. **Si no:** probar ARB como fallback (100% WR garantizada)

### Comando para detener el agente actual
```bash
systemctl stop btc-direction
systemctl disable btc-direction
```

### Próximo paso
Indicar si se procede con la Fase 1 (SNIPE) y empiezo la implementación.
