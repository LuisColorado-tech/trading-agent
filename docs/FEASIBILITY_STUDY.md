# Estudio de Viabilidad — Costos reales (fee + slippage) vs. rentabilidad

> Origen: el capital de despliegues anteriores (crypto y stocks) bajaba pese a que
> el sistema reportaba "ganancias" en paper/producción. Causa raíz confirmada:
> **todo el stack calculaba PnL bruto — nunca restó comisión de exchange ni slippage.**
> La base de datos con el histórico de esos trades fue destruida, así que este estudio
> es **forward-looking**: instrumenta el costo real ANTES de volver a arriesgar capital,
> en vez de auditar trades que ya no existen.
>
> Última actualización: Julio 2026.

---

## 1. Diagnóstico (confirmado en código, antes de este estudio)

| Archivo | Línea | Problema |
|---|---|---|
| `agents/execution_agent.py` | ~102 | `entry_price = signal['indicators']['price']` — sin fee ni slippage al abrir |
| `agents/trade_monitor.py` | ~236-272, ~325-329 | `pnl = (exit - entry) * size` en los 3 caminos de cierre (SL/TP/trailing) — sin costo |
| `agents/grid_stable_agent.py` | ~236-258 | Mismo patrón, cálculo de PnL propio, sin costo |
| `risk/risk_manager.py` | `MIN_RR_RATIO` | RR mínimo (1.5) evaluado sobre distancia de precio, nunca sobre precio neto de fees |
| `config/exchange_config.yaml` | — | Ningún campo de fee/comisión por exchange |
| `scripts/backtest_*.py` | — | Ningún backtest resta comisión al retorno simulado |

Consecuencia: los números en `docs/PRODUCTION_READINESS.md` (TREND_MOMENTUM +$11,781/320 trades,
GRID_BOT +$1,459/431 trades, GRID_STABLE +$385/772 trades) son **PnL bruto**, no lo que
realmente habría quedado en el exchange.

## 2. Qué se corrigió ya en el código (este cambio)

1. **`core/cost_model.py`** (nuevo) — fee schedule por exchange (maker/taker/slippage) y funciones
   `net_pnl()`, `round_trip_cost_pct()`, `min_rr_for_breakeven()`. Punto único de verdad.
2. **`agents/trade_monitor.py`** — `_close_trade()` ahora calcula `pnl_gross`, resuelve el exchange
   del activo vía `ASSET_MAP`, y guarda `pnl` (neto), `pnl_gross` y `fee_paid` en la tabla `trades`.
   El balance del portfolio se actualiza con el PnL **neto**.
3. **`agents/grid_stable_agent.py`** — mismo fix en `close_trade()` (exchange fijo `kraken`).
4. **`risk/risk_manager.py`** — nuevo check **5b**: rechaza el trade (`INSUFFICIENT_NET_RR`) si el
   RR, después de restar el costo estimado del round-trip, cae bajo `MIN_NET_RR_RATIO = 1.0`.
   Esto es preventivo: bloquea el trade ANTES de abrirlo, no solo lo reporta después de cerrarlo.
5. **`db/migrations/007_trade_costs.sql`** — agrega columnas `pnl_gross` y `fee_paid` a `trades`.
   Ejecutar esta migración es un prerequisito para volver a levantar el sistema.

⚠️ **Los fee schedules en `core/cost_model.py` son de referencia (conocimiento general de cada
exchange), no verificados en vivo en esta sesión** (no tuve acceso a la VPS ni pude confirmar
contra las páginas de fees actuales). Antes de fondear capital real, verificar:
- Kraken: kraken.com/features/fee-schedule (tier según volumen 30d real de la cuenta)
- OKX: okx.com/fees
- Alpaca: confirmar spread real observado, no solo "$0 comisión"
- Deribit: deribit.com/pages/information/fees

## 3. Matemática de punto de equilibrio (con los supuestos de arriba)

Costo estimado de un round-trip (entrada + salida, ambos taker) por exchange:

| Exchange | Fee taker ×2 | Slippage ×2 | Costo round-trip |
|---|---|---|---|
| Kraken | 0.52% | 0.16% | **~0.68%** |
| OKX | 0.20% | 0.30% | **~0.50%** |
| Alpaca | 0.00% | 0.20% | **~0.20%** |
| Deribit | 0.08% | 0.40% | **~0.48%** |

Aplicando esto a los parámetros reales de cada estrategia (`risk/risk_manager.py`,
`core/grid_stable_profiles.py`):

### TREND_MOMENTUM (Kraken, SL=1.5×ATR, TP=2.5×ATR)
Con ATR típico ~1.5% del precio en BTC 1h: riesgo=2.25% del precio, ganancia=3.75%.
Ganancia neta = 3.75% − 0.68% = 3.07% → **RR neto ≈ 1.36**. Por encima del piso (1.0),
con margen razonable. Es la estrategia menos frágil ante fees — movimientos grandes,
pocos trades relativos.

### GRID_BOT / GRID_STABLE (Kraken, spacing ~0.10-0.20% del precio)
Ganancia esperada por nivel ≈ 0.10-0.20% del precio. Costo round-trip (0.68% si ambas
patas son taker, ~0.4% si la entrada es limit/maker) **ya es igual o mayor que la ganancia
bruta esperada por trade**. Con 772 trades (GRID_STABLE) y 431 (GRID_BOT) acumulados, un
costo de ~$0.30-0.50/trade no cubierto convierte fácilmente un "+$385 bruto" en **neto
negativo**. Esto coincide exactamente con la experiencia real que describiste: muchos
trades, ganancia nominal, capital bajando.

**Conclusión: los grids, tal como están parametrizados, no sobreviven fees reales de
Kraken taker.** Para que sean viables necesitan una de estas tres cosas:
1. Spacing de grid más ancho (más ganancia por nivel, menos trades) — perjudica win rate.
2. Órdenes 100% maker en ambas patas (fee ~0.16% en vez de 0.26%) — no siempre ejecutable,
   requiere colocar límites en el nivel de salida en vez de market SL/TP.
3. Volumen 30 días alto para bajar de tier de fee en Kraken (poco realista con $1,000 de capital).

### Stocks (Alpaca)
Costo round-trip ~0.20% (sin comisión, solo spread/slippage estimado). El riesgo de fees
es bajo comparado con crypto — el riesgo real ahí es más de tamaño de posición mínimo y
PDT rule (Pattern Day Trader, cuentas <$25k) que de comisión.

## 3b. ¿Se puede salvar GRID_BOT / GRID_STABLE? (actualizado tras retrofit)

Se agregó el gate de RR neto también al lado de la **apertura** (no solo al cierre):
`risk/risk_manager.py` (protege GRID_BOT, que comparte RiskManager) y
`strategies/grid_stable.py` (GRID_STABLE tenía "risk propio", no pasaba por RiskManager —
antes de este cambio NO tenía ninguna protección de fees al abrir). Con eso, calculé
el RR neto real en los extremos del rango operable de cada perfil:

| Estrategia/par | Config | net RR en `min_range_pct` | net RR en `max_range_pct` | Veredicto |
|---|---|---|---|---|
| GRID_BOT (default, 6 niveles) | Kraken taker | -2.0 aprox (range 0.8%) | +1.1 aprox (range 10%) | Viable solo en el 3er superior del rango permitido |
| GRID_STABLE ETH/BTC (10 niveles, original) | Kraken taker | -21.9 (range 0.5%) | -1.16 (range 3.0%) | **Nunca viable dentro de su rango permitido**, ni en el mejor caso |
| GRID_STABLE LINK/BTC (8 niveles, original) | Kraken taker | -8.8 (range 0.8%) | +1.12 (range 5.0%) | Viable solo en la punta superior del rango |

**Conclusión: sí se puede salvar, pero con retunes distintos por par — no hay un fix único.**

### LINK/BTC — salvado con solo config (aplicado en este cambio)
Bajé `grid_levels` 8→4 y subí `min_range_pct` 0.8%→3.0% en `core/grid_stable_profiles.py`.
Resultado: net RR pasa de negativo en casi todo el rango a **+1.26 en el peor caso** (range 3%)
y **+1.95 en el mejor caso** (range 5%). El par realmente opera casi siempre en 3-6% según las
notas originales del perfil, así que esta banda cubre su comportamiento típico. Cambio de cero
riesgo de ingeniería — solo parámetros, ya verificado con la fórmula real de la estrategia.

### ETH/BTC — NO se pudo salvar solo con config
El rango permitido (0.5%-3.0%, para no confundirse con TREND) es demasiado angosto para que
el spacing cubra el fee round-trip de Kraken (~0.68%), incluso llevando `grid_levels` a 3-4.
En el mejor caso (range=3.0%, 4 niveles) el net RR apenas toca +1.11 — casi nunca se va a dar
exactamente el rango máximo, así que en la práctica el gate rechazará casi toda señal. Quedó
documentado en `core/grid_stable_profiles.py` con dos caminos posibles, ninguno aplicado aún
porque requieren una decisión de diseño, no solo un número:
- **(a) Ejecución maker/limit real en ambas patas** (bajaría el costo de ~0.68% a ~0.32%,
  volviendo viable el extremo alto del rango). Esto es trabajo de ingeniería nuevo — hoy el
  sistema simula fills perfectos al precio de la señal, no coloca órdenes límite reales en el
  exchange. Es la solución "correcta" para un grid bot (así operan en la práctica), pero
  requiere soportar fills parciales / no-fill cuando el precio no toca el nivel exacto.
- **(b) Subir `max_range_pct` por encima de 3%** — le daría más espacio de spacing, pero
  el 3% actual está ahí específicamente para filtrar tendencias disfrazadas de rango en un par
  de baja volatilidad (ETH/BTC). Subirlo es una decisión de riesgo, no solo de rentabilidad.

**Recomendación**: dejar ETH/BTC pausado/silencioso (protegido por el gate, no perdiendo
capital) hasta decidir (a) o (b). No tiene sentido forzar un número que no está respaldado
por la matemática de la propia estrategia.

### GRID_BOT (10 activos crypto/metales) — no retuneado en esta pasada
**Corrección de auditoría (Jul 2026)**: GRID_BOT NO pasa por RiskManager — `agents/grid_agent.py`
inserta trades directo a la DB (la doc de PRODUCTION_READINESS decía "RiskManager compartido"
pero el código solo importa la constante de riesgo). El gate de costos se agregó directamente
en `strategies/grid_bot.py::calculate_grid` (mismo patrón que GRID_STABLE): cada nivel debe
tener RR neto ≥ 1.0 con el fee del exchange real del activo (via ASSET_MAP). El cálculo
agregado con los defaults globales (6 niveles, rango 0.8%-10%) muestra el mismo patrón: viable
solo en el tercio superior del rango permitido. A diferencia de GRID_STABLE, cada uno de los 10
activos ya tiene su propio perfil en `core/asset_profiles.py` (grid_tp_ratio, grid_sl_ratio,
grid_levels, grid_min_rr) — el mismo tipo de retune que se hizo en LINK/BTC se puede replicar
activo por activo, pero requiere el ATR/rango típico real de cada uno para no adivinar. Queda
como siguiente paso si se quiere reactivar GRID_BOT con expectativa de que genere señales (hoy
genera señales pero el gate va a rechazar la mayoría hasta que se retunen).

## 4. Framework de decisión (para cuando se retome paper trading)

> ⚠️ Actualizado tras la verificación retroactiva (§6b): el veredicto por RR
> nominal sobreestimó a TREND_MOMENTUM. La vara real es expectancy realizada.

| Estrategia | Estado con costos reales | Acción recomendada |
|---|---|---|
| TREND_MOMENTUM | RR nominal viable, pero **edge realizado 0.189% < costo 0.68%** (§6b) | No fondear tal cual. Reducir frecuencia/trailing prematuro o pasar a maker; re-validar expectancy neta en paper |
| GRID_BOT | Gate activo; viable solo en tercio superior del rango con params default | Retunear por activo (como LINK/BTC) antes de esperar actividad real. Ver 3b |
| GRID_STABLE LINK/BTC | **Retuneado — net RR +1.26 a +1.95** | Retomar en paper con el nuevo perfil, validar 2-3 semanas |
| GRID_STABLE ETH/BTC | No viable dentro de su rango permitido, ni en el mejor caso | **Pausado.** Requiere ejecución maker real o subir max_range_pct (decisión de riesgo). Ver 3b |
| Stocks (Alpaca) | Costo bajo, riesgo es otro (tamaño mínimo, PDT) | Retomar paper, monitorear spread real vs. estimado |
| Options/Polymarket/Basis/Pairs/VIX | Sin fee schedule confirmado, no analizado en detalle en esta pasada | Extender `core/cost_model.py` antes de reactivarlos con capital |

## 5. Checklist antes de volver a fondear con capital real

- [ ] Correr `venv/bin/python3 scripts/preflight_live.py` en la VPS — automatiza los
      primeros 3 checks de esta lista (fees reales vía ccxt, migración 007, cobertura
      de ASSET_MAP) y reporta viabilidad neta de cada perfil grid. Exit 1 = bloqueador.
- [ ] Correr la suite de tests de costos: `venv/bin/python3 -m pytest tests/unit/test_cost_model.py
      tests/unit/test_net_rr_gate.py tests/unit/test_grid_costs.py tests/unit/test_trade_monitor_costs.py -v`
- [ ] Correr migración `007_trade_costs.sql` en la DB nueva
- [ ] Verificar fee schedules reales de Kraken/OKX/Alpaca/Deribit contra `core/cost_model.py`
      (con la cuenta y volumen real, no supuestos)
- [ ] Confirmar qué tipo de orden usa cada executor en la entrada y en la salida
      (market vs. limit) — el costo cambia mucho entre maker y taker
- [ ] Correr GRID_BOT y GRID_STABLE en paper con el nuevo check `INSUFFICIENT_NET_RR` activo
      y ver cuántas señales rechaza — si rechaza casi todo, el spacing actual no es viable
      tal cual, hay que rediseñarlo antes de gastar más ciclos en paper
- [ ] Graduación a producción (`README.md`) debe exigir PF y WR calculados sobre `pnl` **neto**,
      no sobre `pnl_gross`
- [ ] Extender `core/cost_model.py` a Deribit/Polymarket/Binance con fees confirmados antes de
      reactivar esos agentes

## 6b. VERIFICACIÓN RETROACTIVA CON DATOS REALES (Jul 2, 2026 — VPS recuperada)

La VPS fue recuperada con la base de datos intacta: **8,729 trades cerrados
(Mar 16 – Jul 2, 2026)**. Se corrió el análisis retroactivo que la sección 3
solo pudo estimar. Métrica: **edge por trade como % del notional** (unit-safe,
comparable directamente contra el costo del round-trip).

| Estrategia | Trades | Edge/trade | WR | vs. costo Kraken taker (0.68%) | vs. maker puro (0.32%) |
|---|---|---|---|---|---|
| SMC_ORDER_BLOCKS | 153 | +0.237% | 52.3% | MUERE (costo 2.9×) | MUERE |
| TREND_MOMENTUM | 774 | +0.189% | 53.7% | MUERE (costo 3.6×) | MUERE |
| BTC_MICROSTRUCTURE | 92 | +0.184% | 58.7% | MUERE | MUERE |
| GRID_STABLE | 6,158 | +0.039% | 70.4% | MUERE (costo 17×) | MUERE |
| GRID_BOT | 1,515 | +0.029% | 46.3% | MUERE (costo 23×) | MUERE |
| MEAN_REVERSION / EMA_RIBBON / BASIS | 45 | negativo | — | MUERE | MUERE |

**Conclusión retroactiva: NINGUNA estrategia, con su comportamiento realizado,
cubre los fees reales — ni siquiera con ejecución 100% maker.**

### Corrección al veredicto de la sección 3
La sección 3 declaró TREND_MOMENTUM "viable con margen (RR neto ≈1.36)". Ese
cálculo era correcto **para un trade que llega al TP completo**, pero el
comportamiento realizado es otro: el edge promedio por trade fue 0.189% del
notional (no 3.07%), porque la mayoría de los cierres son trailing stops
tempranos (activación a 0.75R), stop losses y break-evens — no TPs completos.
**El gate de RR neto es necesario pero NO suficiente**: filtra trades cuyo TP
no cubriría el costo, pero la vara real es la *expectancy realizada* neta.
Las columnas nuevas `pnl_gross`/`fee_paid` existen exactamente para medir eso
en adelante; la graduación a producción debe exigir
`AVG(pnl/notional) > round_trip_cost_pct` por estrategia, no solo PF/WR.

### Bug adicional descubierto: sizing con unidades rotas en pares BTC-quoted
Trades de ETH/BTC con `position_size` de 14,000–65,000 ETH y notionals de
385–1,800 **BTC** en una cuenta de $1,000: el sizing divide riesgo en USD por
distancia de precio en BTC (`risk_amount / risk_per_unit` sin conversión de
moneda de cotización). En paper pasó invisible porque el PnL guardado quedaba
"del tamaño del riesgo" (~$1); en live esas órdenes son imposibles de llenar
o rechazadas por balance. Los pares USD-quoted (USDC/USDT, DAI/USDT) también
muestran notionals de $12k–17k (12–17× la cuenta). **Bloqueador para live
independiente de los fees**: hay que convertir el riesgo a moneda de
cotización en el sizing de GRID_STABLE (y auditar TREND con notional max
observado de $97,882).

### Estado operativo al momento de la verificación
Los agentes quedaron corriendo tras la recuperación (paper): 12 trades en las
últimas 24h con el código viejo (sin gates de costos). Inofensivo en paper,
pero las estadísticas que generan siguen siendo brutas → detener o desplegar
el retrofit antes de sacar conclusiones de las próximas semanas.

## 6c. Datos de la instancia de producción — resto de agentes (Jul 2, 2026)

Revisión del resto de tablas de la VPS (`stocks_trades`, `poly_sessions`,
`snipe_sessions`, `portfolio`):

### Stocks (Alpaca, paper — `PAPER_TRADING=true` confirmado)
**429 trades cerrados, PnL total −$501, edge promedio −0.181%/trade — negativo
ANTES de fees** (Alpaca no cobra comisión). El agente pierde en bruto. Pero el
agregado esconde una división nítida:

| Symbol | n | PnL | Edge/trade | Veredicto |
|---|---|---|---|---|
| FXI | 67 | +$416 | +1.708% | ✅ cubre slippage con margen amplio |
| GLD | 70 | +$217 | +0.371% | ✅ marginal pero positivo |
| QQQ | 132 | −$477 | −0.276% | ❌ cortar (además tuvo el bug de fake trades, May 2026) |
| EEM | 79 | −$547 | −1.856% | ❌ cortar |
| NVDA/META/SVXY | 60 | −$161 | negativo | ❌ cortar |

FXI+GLD: 137 trades con edge positivo real. El resto quema todo lo que esos dos ganan.

### Polymarket — 5 sesiones, CERO ganadoras
POLY_SESSION_001 a 005: −$438, −$143, −$129, −$250, −$24 (~−$985 acumulado,
la sesión activa también en rojo). A diferencia de los exchanges, la wallet de
Polymarket es USDC real en Polygon (CAPITAL_FLOW.md §2) — verificar cuánto de
esto fue capital real. **Recomendación: matar el agente Polymarket** — no es
un problema de fees, la estrategia no tiene edge en ningún régimen observado.

### GRID_STABLE en producción: 4 pares (2 no estaban en GitHub) — verificado Jul 2

La VPS (v1.4) agregó pares stablecoin que no existían en el clon de GitHub:

| Par | Trades | Edge/trade | WR | Notional avg | Fee real/trade (0.68%) | Neto real/trade |
|---|---|---|---|---|---|---|
| LINK/BTC | 443 | +0.111% | 45.4% | $558* | ~$3.8 | negativo |
| ETH/BTC | 2,927 | +0.057% | 46.6% | $1,164* | ~$7.9 | negativo |
| DAI/USDT | 1,617 | +0.009% | **99.3%** | $10,476 | ~$71 | **−$70/trade** |
| USDC/USDT | 1,179 | +0.006% | **99.6%** | $15,406 | ~$105 | **−$104/trade** |

(*) BTC-quoted: el notional real en USD es mucho mayor por el bug de unidades.

**Los pares stablecoin son el peor caso de todo el sistema**: farmean el ruido
del peg con spacing de ~0.005-0.014% y ganan ~$0.94 casi siempre (WR 99%+),
pero cada "ganancia" pagaría $71-105 de fee real. En live, solo estos dos
pares habrían perdido ~$237,000 estimados con las posiciones registradas.
El WR de 99% es el número más engañoso del dashboard — es exactamente la
firma de una estrategia fee-blind.

**Posición abierta AHORA (Jul 2)**: SELL 7,812,500 LINK (≈$96M nominal a
precio real de LINK) en un agente con balance inicial de $500. Causa raíz
confirmada: `grid_stable_agent` no pasa por RiskManager, no tiene cap de
notional, y `size = riesgo / distancia_SL` con distancias microscópicas
explota el tamaño. El gate de RR neto del retrofit silenciaría los stables y
ETH/BTC automáticamente al desplegarse; falta además un cap de notional local.

### ⚠️ Bug de cash negativo ACTIVO HOY
Snapshot del portfolio de hoy (Jul 2): `available_cash = −$6,744` en un ciclo,
+$2,260 en el siguiente. Es el mismo bug de "available_cash negativo invisible"
de las lecciones de Mayo (AGENTS.md) — consecuencia directa del sizing con
unidades rotas (§6b). Sigue ocurriendo con el código corriendo en la VPS.

### Balance crypto actual (SESSION_011)
$2,353 desde $1,000 inicial (May 20) = +135% en 6 semanas **bruto** — número
inflado por (a) cero fees descontados y (b) posiciones con notional imposible
por el bug de unidades. No usar este número para ninguna decisión.

## 6. Qué quedó fuera de esta pasada (deuda explícita)

- No se tocó `agents/stocks_agent.py` ni los executors de options/polymarket/pairs/vix/basis —
  comparten el mismo patrón de PnL bruto pero no se retrofittearon en esta sesión.
- No se verificaron fee schedules contra las páginas oficiales (sin acceso a red de búsqueda
  en esta sesión) — son supuestos razonables, no datos confirmados.
- No hay backtest histórico neto de costos porque la DB con los trades reales fue destruida.
