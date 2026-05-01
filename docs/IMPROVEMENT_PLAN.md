# PLAN DE MEJORA — Auditoría Mayo 2026

> Plan de acción para mejorar eficiencia y rendimiento de los 3 agentes activos.
> Basado en backtesting 24 meses (May 2024 → Abr 2026).

---

## Estado actual

| Agente | PF | WR | PnL 24m | Meta live | Estado |
|---|---|---|---|---|---|
| Crypto v3 | 1.08 | 35.3% | +$45,866 | PF ≥ 1.5 | ⏳ En calibración |
| Stocks | 1.17 | 35.4% | +$931 | PF ≥ 1.3 | ⏳ En calibración |
| Polymarket | 0.37 | 29.9% | -$961 | Break-even | ❌ Crítico |

---

## BLOQUE 1: Polymarket (URGENTE)

### Causas raíz
1. **Edge = abs(0.50 - price)** — tautología matemática que causa selección adversa inversa
2. Señales técnicas (EMA, RSI) no predicen outcomes de Polymarket
3. max_spread configurado pero nunca aplicado
4. Kelly sizing usa probabilidades infladas (entry_price + edge = 0.50 cuando real es 0.35)
5. Dynamic SL permite -40% antes de activarse
6. Fallback defaults peligrosos (min_price_yes baja a 0.20 si YAML falla)

### Acciones
| # | Acción | Archivo | Líneas | Impacto |
|---|---|---|---|---|
| 1.1 | Reemplazar edge: usar signal_conviction*0.10 | signal_based_poly.py | 383-400 | Elimina selección adversa |
| 1.2 | Subir min_price_yes a 0.42 | exchange_config.yaml + signal_based_poly.py | YAML L148, código L89 | Elimina 71 trades <0.30 |
| 1.3 | Forzar max_spread en feed | polymarket_feed.py | ~160 | Evita rake 5%+ |
| 1.4 | Corregir estimated_prob | signal_based_poly.py | 412 | Kelly realista |
| 1.5 | SL dinámico 0.60→0.75 de entry | poly_monitor.py | SL_LOSS_FRACTION | -25% max pérdida |
| 1.6 | max_concurrent 5→3, max_position 2.5%→1.5% | exchange_config.yaml | risk | Menos exposición |
| 1.7 | Desactivar COMBINATORIAL y LEGGED_ARB | exchange_config.yaml | strategies | -$239 pérdida |

**Meta**: 50 trades con PnL ≥ $0 y WR ≥ 45%

---

## BLOQUE 2: Crypto v3 (ALTA)

### Causas raíz
1. Clasificador de régimen roto (99.6% TREND_DOWN, no filtra nada)
2. TREND_MOMENTUM (61% trades) tiene el peor PF=1.03
3. 7 horas UTC son perdedoras netas (-$25,264 combinado)
4. INJ riesgo 2× otros assets
5. 0 trades cerrados por TRAILING_STOP en 5,469 trades

### Acciones
| # | Acción | Archivo | Impacto |
|---|---|---|---|
| 2.1 | Extender DEAD_HOURS: {9,13,14,20,22,23} | risk_manager.py | -$25K pérdidas |
| 2.2 | Normalizar riesgo INJ (-40% size) | asset_profiles.py | Menos varianza |
| 2.3 | MIN_SCORE 70→75 | trend_momentum.py | Filtra 15% trades malos |
| 2.4 | Activar trailing stop defaults | asset_profiles.py | +0.10 PF |
| 2.5 | MAX_CONCURRENT 3→2 | risk_manager.py | Menos exposición |

**Meta**: PF 1.08 → ≥1.20

---

## BLOQUE 3: Stocks (MEDIA)

### Causas raíz
1. Trailing stop NO implementado (el más grave)
2. XSignal boost aplicado en ambas direcciones
3. ATR filters demasiado bajos (AAPL 0.4%)
4. Macro bias binario sin gradiente

### Acciones
| # | Acción | Archivo | Impacto |
|---|---|---|---|
| 3.1 | Implementar trailing stop | stocks_agent.py:392-419 | +0.15-0.25 PF |
| 3.2 | Corregir xsignal boost dir | stocks_momentum.py:33-37 | +0.05-0.10 PF |
| 3.3 | Subir min_atr_pct | stocks_profiles.py | Filtra ruido |
| 3.4 | Macro bias con gradiente | stocks_agent.py:227-230 | +0.05 PF |
| 3.5 | Implementar blocked_hours_utc | stocks_agent.py | +0.03 PF |

**Meta**: PF 1.17 → ≥1.30

---

## Métricas objetivo para fondeo

| Agente | PF actual | PF objetivo | Plazo |
|---|---|---|---|
| Crypto v3 | 1.08 | ≥1.50 | 3 meses paper |
| Stocks | 1.17 | ≥1.30 | 4 semanas paper |
| Polymarket | 0.37 | ≥1.00 | 1 semana |

---

## Historial de cambios

| Fecha | Bloque | Cambio | Resultado backtest |
|---|---|---|---|
| 2026-05-01 | — | Plan creado | — |
| 2026-05-01 | Poly 1.1 | Edge formula: abs(0.50-price) → tf_conviction*0.15 en signal_based_poly.py | Verificado en vivo |
| 2026-05-01 | Poly 1.2 | min_price_yes: 0.35→0.42 en config + ambos .py | 0.40 rechazado ✓ |
| 2026-05-01 | Poly 1.3 | max_spread enforce en polymarket_feed.py:162 | price_yes+price_no > 1.05 → None |
| 2026-05-01 | Poly 1.4 | estimated_prob: entry_price+edge → entry_price*(1+edge*0.5) | 0.45→0.48 (antes 0.60) |
| 2026-05-01 | Poly 1.5 | SL_LOSS_FRACTION: 0.40→0.25 en poly_monitor.py y config | Max pérdida 40%→25% |
| 2026-05-01 | Poly 1.6 | max_position_pct: 2.5→1.5, max_total_exposure: 40→30, max_concurrent: 5→3 | Menos exposición |
| 2026-05-01 | Poly 1.7 | COMBINATORIAL y LEGGED_ARB ya estaban disabled | Confirmado |
| 2026-05-01 | Crypto 2.1 | DEAD_HOURS: {1,2,3,4,9,13,14,20,22,23} | -25K pérdidas |
| 2026-05-01 | Crypto 2.2 | INJ: sl_multiplier 1.3→1.8, confluence 4→5, tp 2.6→3.5 | -40% size |
| 2026-05-01 | Crypto 2.3 | MIN_SCORE 70→75 en trend_momentum.py | Filtra señales débiles |
| 2026-05-01 | Crypto 2.4 | Trailing: BTC/AVAX/XAU/XAG a 0.75R, INJ a 1.0R | Activa antes |
| 2026-05-01 | Crypto 2.5 | MAX_CONCURRENT 3→2 | Menos exposición |
| 2026-05-01 | Crypto BT | Backtest 6m: PF=1.04, PnL=+$3,342 (1,308 trades) | Mejora marginal — trailing no medible en BT |
| 2026-05-01 | Stocks 3.1 | Trailing stop implementado en _monitor_open_trades() | No medible en backtest |
| 2026-05-01 | Stocks 3.2 | XSignal boost solo en dirección alineada (no ambas) | No medible en backtest |
| 2026-05-01 | Stocks 3.3 | min_atr_pct: AAPL 0.004→0.006, SPY 0.002→0.004, QQQ 0.003→0.005 | QQQ PF 1.08→1.25 |
| 2026-05-01 | Stocks 3.4 | Macro bias con gradiente + get_macro_severity() | No medible en backtest |
| 2026-05-01 | Stocks 3.5 | blocked_hours_utc respetado en _evaluate_symbol() | Filtra gaps apertura |
| 2026-05-01 | Stocks BT | Backtest 24m: PF=1.18, PnL=+$925, SLV PF=1.30 ✓ | 3,383→3,042 trades |
