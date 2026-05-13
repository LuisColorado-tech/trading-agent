# Producción Readiness — TREND_MOMENTUM + GRIDs

> Última auditoría: May 12, 2026
> Estrategias titulares para salida a producción

## Estrategias activas

| # | Estrategia | All-time P&L | Trades | WR | Estado |
|---|-----------|-------------|--------|-----|--------|
| 1 | TREND_MOMENTUM | +$11,781 | 320 | ~50% | ✅ Producción-ready |
| 2 | GRID_BOT | +$1,459 | 431 | ~50% | ✅ Producción-ready |
| 3 | GRID_STABLE | +$385 | 772 | ~50% | ✅ Producción-ready |

## Arquitectura de riesgo

```
Cada agente independiente:
  ├── TREND_MOMENTUM: RiskManager (0.5%/trade, 2 concurrentes, 10% DD halt)
  ├── GRID_BOT:        RiskManager compartido + SL cooldown 30min
  └── GRID_STABLE:     Risk propio (0.1%/level, 5 concurrentes, cooldown 10min)

Protecciones globales:
  ├── DD halt persiste entre reinicios (DB portfolio table)
  ├── Auto-resume paper: 3h cuarentena + DD < 9%
  ├── SIGNAL_DEDUP: 4h bloqueo mismo asset+dirección tras SL
  └── Grid Stable NO interfiere con TrendMomentum (fix May 12)
```

## Límites por agente

### TREND_MOMENTUM
| Parámetro | Valor | Justificación |
|-----------|-------|---------------|
| Riesgo por trade | 0.5% del balance | Backtest 2Y óptimo |
| Exposición máxima | 5% del balance | Limita pérdida diaria a ~2.5% |
| Trades concurrentes | 2 | Evita sobre-exposición |
| DD máximo (halt) | 10% | Para todo. Requiere cuarentena 3h |
| SL cooldown | 60 min | Evita revenge trading |
| SIGNAL_DEDUP | 4h | Bloquea dirección perdedora |
| Horas bloqueadas | Per-asset (asset_profiles.py) | Basado en backtest individual |
| Activos | 10 (BTC,ETH,SOL,AVAX,INJ,LINK,AAVE,POL,XAU,XAG) | Universo expandido May 12 |
| Dirección | SELL only crypto (TREND_MOMENTUM BUY blocked) | Backtest 2Y: BUY -$6,151 |

### GRID_BOT
| Parámetro | Valor | Justificación |
|-----------|-------|---------------|
| Riesgo por nivel | 0.5% × risk_fraction | Dinámico por régimen |
| SL cooldown | 30 min | Evita re-entrada inmediata |
| Niveles por asset | 6-8 | Rango cubierto sin sobre-exposición |
| Trades | 431 (all-time) | Más trades = más datos |

### GRID_STABLE
| Parámetro | Valor | Justificación |
|-----------|-------|---------------|
| Riesgo por nivel | 0.1% del balance (0.5% × 0.20 risk_fraction) | Micro-exposición para pares estables |
| Concurrentes | 5 total (3 ETH/BTC + 2 LINK/BTC) | Limitado por exchange_config |
| TP/SL ratio | 1.80-1.95 / 0.60-0.65 | RR mínimo 1.5 |
| Cooldown | 10 min | Corto por micro-volatilidad |
| Trades | 772 (all-time) | Alta frecuencia, baja varianza |

## Verificaciones de seguridad

| Check | Estado | Nota |
|-------|--------|------|
| DD halt sobrevive reinicio | ✅ | Verificado en DB portfolio |
| Auto-resume en paper | ✅ | 3h + DD < 9% |
| Grid Stable no bloquea TrendMomentum | ✅ | get_open_trades() filtra strategy != 'GRID_STABLE' |
| DEAD_HOURS por asset | ✅ | hour_allowed() en risk_manager.py (May 12) |
| SMC/BTC_MICRO desactivadas | ✅ | Perdían dinero, sin backtest |
| STOCKS_MOMENTUM desactivado | ✅ | Cambiado a TREND_ETF (May 12) |
| Mean Reversion desactivada | ✅ | 0/8 WR en paper |
| Redis cooldowns funcionan | ✅ | Verificado en cada ciclo |

## Pendientes para producción

| # | Tarea | Prioridad |
|---|-------|-----------|
| 1 | Backtest walk-forward 6m con parámetros actuales | HIGH |
| 2 | Sistema de alerts multi-canal (Telegram + email) | HIGH |
| 3 | Dashboard de monitoreo de riesgo en tiempo real | MEDIUM |
| 4 | Paper session con balance aislado por agente | MEDIUM |
| 5 | Logueo de métricas de riesgo a DB (no solo logs) | MEDIUM |
| 6 | Circuit breaker por volatilidad de mercado (VIX > 30 → reducir exposición) | LOW |

## Línea de tiempo sugerida

```
Semana 1: Backtest walk-forward + paper 24/7 con parámetros actuales
Semana 2: Si PF > 1.2 y MaxDD < 15%, activar en producción con 0.25× position size
Semana 3: Si 2 semanas positivas, escalar a 0.5×
Semana 4: Si 3 semanas positivas, escalar a 1.0×
```

## Reglas de oro

1. **NUNCA aumentar MAX_CONCURRENT_TRADES sin backtest** — más trades ≠ más ganancias
2. **NUNCA reducir SL_COOLDOWN** — protege contra revenge trading
3. **SIEMPRE verificar DD halt antes de reiniciar** — `redis-cli get halt:trading`
4. **SIEMPRE correr backtest antes de cambiar MIN_SCORE o SL/TP**
5. **Grid Stable y TrendMomentum son independientes** — no reintroducir el bug de conteo unificado
