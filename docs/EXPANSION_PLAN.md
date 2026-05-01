# PLAN DE EXPANSIÓN — 5 Nuevas Líneas de Negocio

> Meta del consorcio: **2% mensual compuesto** entre todos los agentes activos.
> Basado en infraestructura existente: VPS Linux, Python 3.12, PostgreSQL, Redis, CCXT, Alpaca, Kraken.

---

## Arquitectura objetivo

```
                          ┌─────────────────────────────────────┐
                          │         ARTHAS TRADING v4           │
                          │         5 agentes actuales           │
                          │    + 5 nuevas líneas de negocio      │
                          └─────────────────────────────────────┘
                                          │
          ┌───────────┬──────────┬────────┼────────┬──────────┐
          ▼           ▼          ▼        ▼        ▼          ▼
      Crypto v3   Stocks v3    Poly    Options   BTC Dir   NUEVAS
     (SELL 15m)  (Momentum)   (v3)    (Theta)   (pausado)
          │           │                           
          ▼           ▼                           
    ┌─────────┐ ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
    │GRID     │ │BASIS    │ │VIX MEAN  │ │PAIRS     │ │EARNINGS  │
    │STABLE   │ │TRADE    │ │REVERSION │ │TRADING   │ │STRANGLE  │
    │PAIRS    │ │(Kraken) │ │(Alpaca)  │ │(Alpaca)  │ │(Alpaca)  │
    └─────────┘ └─────────┘ └──────────┘ └──────────┘ └──────────┘
     ETH/BTC     Spot+ Fut   VXX/UVXY    GLD-SLV      NVDA/TSLA
     Stablecoins 8-15% APY   contango    KO-PEP       AAPL/META
```

---

## Resumen de contribución esperada por línea

| Línea | Retorno mensual estimado | Drawdown esperado | Capital mínimo | Correlación con crypto |
|---|---|---|---|---|
| Grid Stable Pairs | 0.5–1.0% | <3% | $50 | Baja (ETH/BTC) |
| Basis Trade | 0.6–1.2% | <2% | $100 | Cero (market neutral) |
| VIX Mean Reversion | 1.0–2.0% | 5–10% | $100 | Negativa (hedge) |
| Pairs Trading | 0.8–1.5% | 3–5% | $100 | Cero (market neutral) |
| Earnings Strangle | 1.5–3.0% | 8–15% | $200 | Baja |
| **TOTAL NUEVAS** | **2.0–4.0%** | — | — | — |
| Agentes actuales | ~3% (estimado paper) | — | — | — |
| **CONSOLIDADO** | **~5% mensual** | — | — | — |

---

## FASE 1: Grid Bot Stable Pairs (Semana 1-2)

### Objetivo
Extender el Grid Bot existente a pares de baja volatilidad donde el rango es más predecible y las comisiones son mínimas.

### Arquitectura

```
agents/grid_agent.py (ya existe)
    └── extender con GRID_STABLE_PAIRS = {ETH/BTC, LINK/BTC, USDC/USDT}
    └── perfiles nuevos en asset_profiles.py
    └── grid_stable_profiles.py (nuevo)
```

### Entregables

| # | Archivo | Descripción |
|---|---|---|
| 1.1 | `core/grid_stable_profiles.py` | Perfiles para ETH/BTC, LINK/BTC, USDC/USDT: ATR más bajo, más niveles (8-10), TP/SL más ceñidos |
| 1.2 | `agents/grid_agent.py` | Aceptar `universe` paramétrico. Agregar `STABLE_UNIVERSE` con loop separado |
| 1.3 | `strategies/grid_stable.py` | Variante de GridBotStrategy con `max_range_width=0.03` (3% rango) y `min_bars_in_range=40` |
| 1.4 | `scripts/backtest_grid_stable.py` | Backtester específico para pares estables (hereda de backtest_grid.py) |
| 1.5 | `config/exchange_config.yaml` | Sección `grid_stable:` con parámetros por par |
| 1.6 | systemd: `grid-stable.service` | Servicio independiente o integrado al grid-agent |

### Parámetros clave

```yaml
grid_stable:
  enabled: true
  pairs:
    ETH/BTC:
      min_range_pct: 0.005     # 0.5% rango mínimo
      max_range_pct: 0.030     # 3% rango máximo
      grid_levels: 10          # más niveles = más trades pequeños
      tp_ratio: 1.20           # TP más ceñido (menos ganancia pero más frecuente)
      sl_ratio: 0.40           # SL muy ceñido (poca volatilidad)
      min_volume_btc: 500      # liquidez mínima
```

---

## FASE 2: Basis Trade (Semana 2-3)

### Objetivo
Comprar spot + vender futuro del mismo vencimiento. Capturar el funding rate sin riesgo direccional. Estrategia 100% market-neutral.

### Cómo funciona

1. Comprar 0.01 BTC en spot (Kraken)
2. Vender 0.01 BTC en futures mismo exchange (Kraken Futures)
3. El funding rate se paga cada 8 horas (típicamente 0.01% = 10.95% anual)
4. Al vencimiento del futuro: recomprar futuro + vender spot → PnL = funding acumulado - comisiones

### Arquitectura

```
strategies/basis_trade.py (nuevo)
    ├── data/kraken_futures_feed.py (nuevo) — API Kraken Futures
    ├── agents/basis_executor.py (nuevo) — ejecuta apertura/cierre del par
    └── core/kraken_futures_session.py (nuevo) — auth Kraken Futures
```

### Entregables

| # | Archivo | Descripción |
|---|---|---|
| 2.1 | `data/kraken_futures_feed.py` | Cliente Kraken Futures: `get_funding_rate()`, `get_futures_contracts()`, `get_open_positions()` |
| 2.2 | `core/kraken_futures_session.py` | Autenticación Kraken Futures (API key existente, endpoint `futures.kraken.com`) |
| 2.3 | `strategies/basis_trade.py` | Lógica: elegir contrato con mayor funding rate positivo, abrir par spot+futuro, monitorear |
| 2.4 | `agents/basis_executor.py` | Ejecución: orden spot + orden futuro simultáneas. Roll-over automático al siguiente contrato |
| 2.5 | `scripts/backtest_basis.py` | Backtest con datos históricos de funding rate (Kraken API histórica) |
| 2.6 | `config/exchange_config.yaml` | Sección `basis_trade:` con min_funding_rate, max_capital_pct |

### Parámetros clave

```yaml
basis_trade:
  enabled: true
  paper_trading: true           # ← paper primero, SIEMPRE
  min_funding_rate_annual: 8.0  # % anual mínimo para entrar
  max_capital_pct: 0.30         # 30% del capital total en basis trades
  contracts: [BTC/USD, ETH/USD] # solo los líquidos
  rollover_days_before: 2       # rollear 2 días antes del vencimiento
  check_interval_minutes: 60    # verificar funding cada hora
```

---

## FASE 3: VIX Mean Reversion (Semana 3-4)

### Objetivo
Operar productos de volatilidad (VXX, UVXY, SVXY) en Alpaca. Estos productos pierden valor por contango → venderlos o comprar el inverso cuando VIX está alto.

### Cómo funciona

1. Monitorear VIX spot (via yfinance) + contango (futures term structure)
2. Cuando VIX > 30 (pánico): comprar SVXY (inverso) o vender UVXY en papel
3. Cuando VIX < 15 (complacencia): tomar profit o rotar a cash
4. Durante VIX 15-30: no operar o reducir tamaño

### Arquitectura

```
strategies/vol_mean_reversion.py (nuevo)
    ├── data/vol_feed.py (nuevo) — VIX spot, VIX futures, contango
    ├── core/vol_profiles.py (nuevo) — perfiles de productos de vol
    └── se integra al StocksAgent como estrategia adicional
```

### Entregables

| # | Archivo | Descripción |
|---|---|---|
| 3.1 | `data/vol_feed.py` | `get_vix_spot()`, `get_vix_futures_term_structure()`, `get_contango_pct()`, `get_vix_percentile(252d)` |
| 3.2 | `core/vol_profiles.py` | Perfiles para VXX, UVXY, SVXY, VIXY: SL/TP, tamaño, filtros de entrada |
| 3.3 | `strategies/vol_mean_reversion.py` | Señal cuando VIX > percentil 80. Entrada: short VXX o long SVXY. Salida: VIX < percentil 50 o TP/SL |
| 3.4 | `scripts/backtest_vol.py` | Backtest con datos históricos de VIX y productos de vol (yfinance, 5 años) |
| 3.5 | Integración en `stocks_agent.py` | Agregar VXX/UVXY/SVXY al universo con `use_regime_filter=False` |

### Parámetros clave

```yaml
vol_mean_reversion:
  enabled: true
  paper_trading: true
  assets: [SVXY]                  # long SVXY = short vol
  vix_entry_percentile: 80        # entrar cuando VIX > percentil 80 del último año
  vix_exit_percentile: 50         # salir cuando VIX vuelve a la mediana
  max_position_pct: 0.10          # 10% del capital en vol
  stop_loss_pct: 0.15             # -15% en el activo → salir
  min_contango_annual_pct: 20.0   # contango mínimo para que valga la pena
```

---

## FASE 4: Pairs Trading (Semana 4-6)

### Objetivo
Identificar pares de activos cointegrados. Cuando el spread se desvía, abrir posiciones opuestas (long uno, short el otro). Market-neutral.

### Pares candidatos

| Par | Sector | Correlación 2Y | Fuente datos |
|---|---|---|---|
| GLD-SLV | Metales preciosos | 0.82 | Alpaca (ya en universo) |
| KO-PEP | Consumo defensivo | 0.78 | Alpaca (agregar) |
| XOM-CVX | Energía | 0.85 | Alpaca (agregar) |
| BTC-ETH | Crypto | 0.89 | Kraken (ya en universo) |
| SPY-QQQ | Índices USA | 0.92 | Alpaca (ya en universo) |

### Cómo funciona

1. Calcular ratio o spread = log(P1) - β × log(P2) con β de regresión 252 días
2. Z-score del spread: (spread - media) / desviación
3. Entrada: z-score > 2.0 o < -2.0 → abrir par (long underperformer, short outperformer)
4. Salida: z-score vuelve a 0, o TP/SL fijo
5. Tamaño: risk-neutral (mismo capital en ambas piernas)

### Arquitectura

```
strategies/pairs_trading.py (nuevo)
    ├── data/pairs_feed.py (nuevo) — descarga OHLCV para pares, calcula cointegración
    ├── core/pairs_profiles.py (nuevo) — perfiles de pares (half-life, z-entry, z-exit)
    ├── agents/pairs_executor.py (nuevo) — ejecuta órdenes long+short simultáneas
    └── scripts/backtest_pairs.py (nuevo) — backtest de cointegración con rolling window
```

### Entregables

| # | Archivo | Descripción |
|---|---|---|
| 4.1 | `data/pairs_feed.py` | `get_pair_ohlcv()`, `calc_cointegration()`, `calc_half_life()`, `calc_zscore()` |
| 4.2 | `core/pairs_profiles.py` | Perfiles: par, β (hedge ratio), half-life (días), z_entry (2.0), z_exit (0.0), max_hold_days |
| 4.3 | `strategies/pairs_trading.py` | Genera señal cuando z-score cruza umbral. Calcula tamaños risk-neutral |
| 4.4 | `agents/pairs_executor.py` | Ejecuta long+short simultáneos en Alpaca/Kraken. Monitorea spread |
| 4.5 | `scripts/backtest_pairs.py` | Rolling cointegration test (ventana 252d, refit cada 21d). Backtest walk-forward |
| 4.6 | systemd: `pairs-agent.service` | Loop independiente |

### Parámetros clave

```yaml
pairs_trading:
  enabled: true
  paper_trading: true
  pairs:
    GLD-SLV:
      hedge_ratio_window: 252    # días para estimar β
      refit_interval: 21         # recalcular β cada 21 días
      z_entry: 2.0               # entrada: 2 desviaciones
      z_exit: 0.0                # salida: reversión a la media
      stop_loss_z: 3.5           # SL si z-score sigue divergiendo
      max_hold_days: 60          # tiempo máximo en el trade
      min_half_life: 5           # half-life mínimo (días) — que revierta rápido
      max_half_life: 60          # half-life máximo
    BTC-ETH:
      hedge_ratio_window: 90
      refit_interval: 7
      z_entry: 2.5               # más ancho para crypto (más volátil)
      z_exit: 0.5
      stop_loss_z: 4.0
      max_hold_days: 30
```

---

## FASE 5: Earnings Strangle (Semana 6-8)

### Objetivo
Comprar strangles (call + put OTM) antes de earnings de alta volatilidad. El objetivo no es acertar dirección, sino que el movimiento post-earnings sea mayor que la prima pagada.

### Cómo funciona

1. Calendario de earnings: identificar próximos NVDA, TSLA, AAPL, META, AMZN
2. 1 día antes del earnings: comprar strangle (call OTM +5% y put OTM -5%)
3. Las opciones son caras (IV alto pre-earnings) pero el movimiento suele superar la prima
4. Cerrar 1 día después del earnings (ya pasó el evento)
5. Paper trading en Alpaca Options (paper)

### Arquitectura

```
strategies/earnings_strangle.py (nuevo)
    ├── data/earnings_calendar.py (nuevo) — calendario de earnings (yfinance o API)
    ├── data/options_chain_feed.py (nuevo) — cadena de opciones de Alpaca
    ├── core/earnings_profiles.py (nuevo) — perfiles por acción (OTM%, DTE, SL%)
    └── scripts/backtest_earnings.py (nuevo) — backtest con datos históricos de earnings
```

### Entregables

| # | Archivo | Descripción |
|---|---|---|
| 5.1 | `data/earnings_calendar.py` | `get_next_earnings()` via yfinance. Filtrar por market cap > $100B |
| 5.2 | `data/options_chain_feed.py` | Extender Alpaca client para `get_option_chain()`. Calcular IV, Greeks |
| 5.3 | `core/earnings_profiles.py` | NVDA: OTM=±6%, DTE=7. TSLA: OTM=±8%. AAPL: OTM=±4% |
| 5.4 | `strategies/earnings_strangle.py` | Elegir strikes, comprar strangle 1 día antes, vender 1 día después |
| 5.5 | `agents/earnings_executor.py` | Ejecutar compra de opciones en Alpaca paper. Monitorear PnL |
| 5.6 | `scripts/backtest_earnings.py` | Simular strangles históricos con precios de cierre pre/post earnings (yfinance) |

### Parámetros clave

```yaml
earnings_strangle:
  enabled: true
  paper_trading: true
  assets: [NVDA, TSLA, AAPL, META, AMZN]
  otm_pct: 0.05                   # 5% OTM para calls y puts
  days_before: 1                  # comprar 1 día antes
  days_after: 1                   # vender 1 día después
  max_position_pct: 0.05          # 5% del capital por strangle
  min_market_cap: 100e9           # solo mega-cap (evitar penny stocks)
  max_iv_rank: 90                 # no comprar si IV rank > 90 (demasiado caro)
  min_iv_rank: 40                 # no comprar si IV rank < 40 (poco movimiento esperado)
  stop_loss_pct: 0.50             # SL si el strangle pierde 50% de la prima
```

---

## Cronograma de implementación

| Semana | Fase | Entregables | Backtest |
|---|---|---|---|
| **1** | Grid Stable | 1.1–1.5: perfiles, estrategia, config | `backtest_grid_stable.py` ETH/BTC 2Y |
| **2** | Grid Stable | 1.6: systemd service, integración, paper live | Ajustar parámetros post-backtest |
| **3** | Basis Trade | 2.1–2.3: API Kraken Futures, estrategia | `backtest_basis.py` funding rates 2Y |
| **4** | Basis Trade + VIX | 2.4–2.6: ejecutor, backtest, config. 3.1–3.3: vol feed + estrategia | `backtest_vol.py` VIX 5Y |
| **5** | Pairs Trading | 4.1–4.4: feed pares, cointegración, estrategia, ejecutor | `backtest_pairs.py` GLD-SLV 5Y |
| **6** | Pairs Trading | 4.5–4.6: backtest final, systemd service | Ajustar umbrales z-score |
| **7** | Earnings | 5.1–5.4: calendario, opciones, estrategia | `backtest_earnings.py` NVDA/TSLA 3Y |
| **8** | Earnings + Cierre | 5.5–5.6: ejecutor, systemd. Documentación general. Dashboard | Backtest final todos |

---

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Basis trade: Kraken Futures API cambia | Paper 4 semanas antes de live, monitorear changelog |
| VIX: SVXY puede tener decay en mercados laterales | Solo operar cuando VIX > percentil 80, SL del 15% |
| Pairs: cointegración se rompe (régimen cambia) | Refit semanal del hedge ratio. Stop loss por z-score |
| Earnings: IV crush come toda la prima | Paper primero. Solo operar acciones con avg move > OTM% histórico |
| Grid stable: baja volatilidad = pocas señales | Combinar con grid normal. No dedicar más del 20% del capital |
| Sobrecarga del VPS: 5 agentes nuevos | Un agente por vez. Medir CPU/RAM. Si hace falta, escalar VPS |

---

## Dashboard — Integración visual

Agregar al React dashboard una sección **"Líneas de Negocio"** en el Overview:

| Línea | Estado | Capital | PnL mensual | Retorno % |
|---|---|---|---|---|
| Crypto v3 | 🟢 LIVE | $10,000 | — | — |
| Stocks v3 | 🟢 LIVE | $220 | — | — |
| Polymarket v3 | 🟢 LIVE | $1,000 | — | — |
| Grid Stable | 🟡 DEV | $0 | — | — |
| Basis Trade | ⚪ PLAN | $0 | — | — |
| VIX Mean Rev | ⚪ PLAN | $0 | — | — |
| Pairs Trading | ⚪ PLAN | $0 | — | — |
| Earnings Strangle | ⚪ PLAN | $0 | — | — |

---

## Próximo paso

Arrancar **Fase 1 (Grid Stable)**. Es la de menor riesgo, menor esfuerzo (extiende código existente), y puede dar 0.5-1% mensual en 1-2 semanas. ¿Procedo?

---

## Historial de implementación

| Fecha | Fase | Estado | Resultado backtest | Commit |
|---|---|---|---|---|
| 2026-05-01 | 1 — Grid Stable | ✅ COMPLETADA | ETH/BTC: PF=1.84, DD=0.3%, Sharpe=2.20 | a3119e4 |
| 2026-05-03 | 2 — Basis Trade | ⏳ Programado | — | — |
| 2026-05-05 | 3 — VIX Mean Rev | ⏳ Programado | — | — |
| 2026-05-07 | 4 — Pairs Trading | ⏳ Programado | — | — |
| 2026-05-10 | 5 — Earnings Strangle | ⏳ Programado | — | — |
| 2026-05-13 | 6 — Reporte Final | ⏳ Programado | — | — |
