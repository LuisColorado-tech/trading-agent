# PLAN MAESTRO — GitHub Strategy Hunter
## Sistema de Ingeniería Inversa de Estrategias de Trading

**Creado:** 2026-04-25  
**Actualizado:** 2026-05-02 (sondeo completo — 2 repos nuevos, 1 eliminado)  
**Estado:** ACTIVO  
**Versión:** 1.1

---

## RESUMEN EJECUTIVO

Sistema automatizado para:
1. Buscar los mejores repos de trading en GitHub
2. Extraer y documentar sus estrategias por ingeniería inversa
3. Adaptar estrategias al framework de backtesting existente
4. Backtest en datos históricos reales (KuCoin via ccxt)
5. Filtrar las mejores y desplegarlas en producción

**Resultado:** De 703+ repos identificados → 8 estrategias de alta calidad en DB → 3 adaptadores creados → backtesting integrado (1 repo eliminado por borrado en GitHub)

---

## INFRAESTRUCTURA CREADA

### Base de Datos
- **Tabla:** `repo_strategies` (migración 004)
  - Almacena repos, estrategias, lógica, resultados de backtest
  - Estados: `discovered → analyzed → adapted → backtested → deployed → rejected`
- **Vista:** `v_strategies_to_backtest` — estrategias priorizadas para backtest

### Scripts
- **`/opt/trading/scripts/repo_strategy_hunter.py`** — Pipeline principal
  - `--phase seed` → poblar repos manuales de alta calidad
  - `--phase discover` → busca via GitHub API
  - `--phase analyze` → descarga READMEs y extrae lógica
  - `--phase backtest` → ejecuta backtests
  - `--phase report` → genera reporte completo
  - `--phase all` → ejecutar todo el pipeline

### Estrategias Adaptadas
- **`/opt/trading/strategies/smc_order_blocks.py`** — SMC/ICT Order Blocks + FVG
- **`/opt/trading/strategies/pullback_state_machine.py`** — Pullback 4-Phase State Machine
- **`/opt/trading/strategies/btc_microstructure.py`** — BTC Microstructure Multi-Signal

---

## REPOSITORIOS IDENTIFICADOS (Prioridad 1-3)

### PRIORIDAD 1 — Implementar inmediatamente

| Repo | Estrellas | Estrategia | Tipo | Timeframe | Potencial |
|------|-----------|------------|------|-----------|-----------|
| `Polymarket/agents` | 3,363⭐ | AI Agents oficial Polymarket | agent-based | variable | ★★★ |
| `aulekator/Polymarket-BTC-15-Minute-Trading-Bot` | 196⭐ | Multi-Signal 7-Phase | composite | 15m | ★★☆ |
| `suislanchez/polymarket-kalshi-weather-bot` | 282⭐ | BTC Microstructure + Kelly | composite | 5m | ★★★ |
| `CarlosIbCu/polymarket-kalshi-btc-arbitrage-bot` | 179⭐ | Cross-Platform Arb (PM↔Kalshi) | arb | 1h | ★★★ |

**Lógica clave extraída:**

**Polymarket/agents (OFICIAL):**
- Framework oficial de Polymarket para trading autónomo con AI agents
- Arquitectura: Agent → Strategy → Market → Order
- Soporta multi-market, risk management, backtesting integrado
- MIT license, comunidad activa (760+ forks)

**aulekator:**
- Señales: RSI(14) + Momentum(1m/5m/15m) + VWAP dev + SMA crossover + Market skew
- Convergencia: ≥2 de 5 indicadores
- Position sizing: Kelly fraccional (15%)
- Edge mínimo: 2% para BTC, 8% para weather
- Stop loss: 30%, Take profit: 20%

**CarlosIbCu (NUEVO — Arbitraje riesgo-cero):**
- Arbitraje cross-platform entre Polymarket y Kalshi en mercados BTC 1-Hour
- Detecta diferencias de precio en tiempo real via CLOB de Polymarket + API de Kalshi
- Matemática de arbitraje documentada en `thesis.md`
- MIT license, 525KB de código

### PRIORIDAD 2 — Backtest y validar

| Repo | Estrellas | Estrategia | Tipo | Resultados Reportados |
|------|-----------|------------|------|-----------------------|
| `joshyattridge/smart-money-concepts` | 1,615⭐ | SMC/ICT Order Blocks + FVG | breakout | N/A (lib) |
| `ilahuerta-IA/backtrader-pullback-window-xauusd` | 45⭐ | Pullback State Machine | momentum | Sharpe 0.89, PF 1.64, WR 55% |
| ~~`genoshide/polymarket-arbitrage-trading-bot`~~ | ❌ **ELIMINADO** | Latency Arb (2.7s lag) | arb | Repo borrado de GitHub (Mayo 2026) |

### PRIORIDAD 3 — Investigar más

| Repo | Estrellas | Estrategia | Tipo |
|------|-----------|------------|------|
| `0xrsydn/polymarket-crypto-toolkit` | 57⭐ | Plugin-based multi-strat | composite |
| `GiordanoSouza/polymarket-copy-trading-bot` | 44⭐ | Copy-trading wallets | signal_based |

---

## CRITERIOS DE EVALUACIÓN

### Filtros de aprobación (backtest)
| Métrica | Mínimo | Óptimo |
|---------|--------|--------|
| Win Rate | ≥ 45% | ≥ 55% |
| Profit Factor | ≥ 1.2 | ≥ 1.5 |
| Max Drawdown | ≤ 20% | ≤ 10% |
| Sharpe Ratio | ≥ 0.8 | ≥ 1.2 |
| Total Trades | ≥ 50 | ≥ 100 |
| Retorno | ≥ 10% | ≥ 30% |

### Criterios de deployment a producción
1. Backtest aprobado con criterios mínimos
2. Forward test en paper trading ≥ 2 semanas
3. Revisión manual de lógica de entrada/salida
4. Configuración de risk params en `exchange_config.yaml`

---

## PIPELINE DE EJECUCIÓN

### Fase 1 — Discovery (completada ✅)
```bash
python scripts/repo_strategy_hunter.py --phase seed
python scripts/repo_strategy_hunter.py --phase discover
```
- 7 estrategias manuales de alta calidad en DB
- Sistema de búsqueda automática via GitHub API
- Clasificación por tipo, asset class, timeframe

### Fase 2 — Análisis (completada ✅)
```bash
python scripts/repo_strategy_hunter.py --phase analyze
```
- READMEs descargados y parseados
- Lógica de entrada/salida documentada
- Indicadores identificados

### Fase 3 — Adaptación (completada ✅)
```bash
# Estrategias adaptadas creadas:
# strategies/smc_order_blocks.py
# strategies/pullback_state_machine.py
# strategies/btc_microstructure.py
```
- 3 adaptadores creados con interfaz estándar `score(ind, df)`
- Integrados en `scripts/backtest.py`

### Fase 4 — Backtest (PENDIENTE)
```bash
# Backtest individual por estrategia:
python scripts/backtest.py --assets BTC/USDT --tf 15m --months 18 --csv reports/smc_backtest.csv

# Backtest completo con todas las estrategias:
python scripts/repo_strategy_hunter.py --phase backtest
```

### Fase 5 — Evaluación y Deploy (PENDIENTE)
```bash
python scripts/repo_strategy_hunter.py --phase report
```
- Filtrar estrategias con Sharpe ≥ 0.8 y WR ≥ 45%
- Paper trading 2 semanas
- Deploy a producción si pasa

---

## PRÓXIMOS PASOS INMEDIATOS

### 1. Correr backtests de las 3 estrategias nuevas
```bash
cd /opt/trading && source venv/bin/activate
# SMC Order Blocks
python scripts/backtest.py --assets BTC/USDT ETH/USDT --tf 15m --months 18 --csv reports/smc_ob_backtest.csv

# Pullback State Machine
python scripts/backtest.py --assets BTC/USDT ETH/USDT --tf 15m --months 18 --csv reports/psm_backtest.csv

# BTC Microstructure
python scripts/backtest.py --assets BTC/USDT --tf 5m --months 12 --csv reports/btc_micro_backtest.csv
```

### 2. Analizar estrategia de arbitraje cross-platform (Polymarket ↔ Kalshi)
- Revisar código de `CarlosIbCu/polymarket-kalshi-btc-arbitrage-bot` ⭐179
- Leer `thesis.md` con la matemática de arbitraje
- Evaluar si es compatible con nuestra infraestructura existente (ya tenemos feeds de ambos)
- Implementar detector de oportunidades Kalshi vs Polymarket

### 3. Evaluar Polymarket AI Agents oficial
- Revisar framework `Polymarket/agents` ⭐3,363 (oficial de Polymarket)
- Arquitectura agent-based compatible con nuestro sistema
- Evaluar migración de nuestros agentes Polymarket al framework oficial
- Identificar las top 10 wallets en Polymarket
- Monitorear sus trades en tiempo real
- Implementar replicación con delay mínimo

### 4. Expandir búsqueda de repos
- Buscar estrategias específicas de opciones
- Explorar repos con backtesting documentado (Sharpe publicado)
- Integrar `freqtrade` strategies (50+ built-in)

---

## ARQUITECTURA DE INTEGRACIÓN

```
GitHub API
    ↓
repo_strategy_hunter.py (Discovery + Analysis)
    ↓
DB: repo_strategies (estado: discovered → analyzed → adapted)
    ↓
strategies/*.py (Adaptadores de estrategia)
    ↓
scripts/backtest.py (Backtest en datos históricos KuCoin)
    ↓
DB: repo_strategies.backtest_result (métricas guardadas)
    ↓
[Filtra: WR≥45%, PF≥1.2, Sharpe≥0.8]
    ↓
Paper Trading 2 semanas
    ↓
Production (agents/strategy_engine.py o core/poly_strategy_hub.py)
```

---

## COMANDOS DE MANTENIMIENTO

```bash
# Ver todas las estrategias en DB
psql -c "SELECT id, strategy_name, strategy_type, implementation_status, priority FROM repo_strategies ORDER BY priority"

# Actualizar estado de una estrategia
psql -c "UPDATE repo_strategies SET implementation_status='backtested' WHERE id=5"

# Ver candidatos para deploy
psql -c "SELECT strategy_name, backtest_result FROM repo_strategies WHERE backtest_result->>'win_rate' > '0.45'"

# Correr reporte completo
python /opt/trading/scripts/repo_strategy_hunter.py --phase report
```

---

## NOTAS DE INGENIERÍA INVERSA

### Smart Money Concepts (SMC/ICT)
La librería `smartmoneyconcepts` de joshyattridge implementa:
- **Order Blocks:** Última vela de dirección opuesta antes de un impulso fuerte
- **Fair Value Gaps:** Cuando `high[i-1] < low[i+1]` (bullish) o `low[i-1] > high[i+1]` (bearish)
- **Break of Structure:** Precio rompe sobre un swing high previo (alcista) o bajo un swing low (bajista)
- **Change of Character:** El primer BOS contrario a la tendencia mayor

### BTC Microstructure (suislanchez)
Pesos de señales documentados:
- RSI(14): peso 0.25
- Momentum multiperiodo: peso 0.25  
- VWAP deviation: peso 0.20
- SMA crossover: peso 0.15
- Market skew: peso 0.15

### Kelly Criterion (suislanchez)
```
kelly = (win_prob * odds - lose_prob) / odds
position = kelly * 0.15 * bankroll  # 15% fraccional
# Capped: max(5% bankroll, $75 por trade)
```

### Cross-Platform Arbitrage (CarlosIbCu)
- Monitorea simultáneamente Polymarket CLOB y Kalshi API para mercados BTC 1-Hour
- Detecta discrepancia de precios: si P_poly + P_kalshi < $1.00 → arbitraje libre de riesgo
- Fórmula: Profit = (1 - P_poly - P_kalshi) * position_size - fees
- Tesis matemática completa en thesis.md del repo

### Polymarket AI Agents (oficial)
- Sistema de agentes autónomos con marketplace de estrategias
- Cada agente: percepción del mercado → decisión → ejecución → aprendizaje
- Risk management integrado: position sizing, stop loss, portfolio limits
- API compatible con Python SDK de Polymarket
