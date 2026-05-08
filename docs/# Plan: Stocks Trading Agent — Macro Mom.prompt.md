# Plan: Stocks Trading Agent — Macro Momentum Híbrido

**TL;DR:** Construir un agente de acciones sobre la misma infraestructura del crypto agent. El 80% del código ya existe y se reutiliza. Arranca con una fase de exploración de xsignals (@aguti00) para entender qué valor real aporta antes de integrarlo. La estrategia decide sola si va long o short. Alpaca es el broker (como Kraken pero para la Bolsa de New York, tiene paper gratuito).

---

## Fase 0 — Exploración xsignals (antes de escribir una línea del bot)

El objetivo es responder: **¿@aguti00 tiene edge real? ¿Con qué frecuencia posta señales accionables?**

**Paso 1** — Añadir @aguti00 y hacer primeros scans:
```bash
cd /opt/arthas-bot
python3 xsignals_v2.py profiles add aguti00
python3 xsignals_v2.py scan-profile aguti00 20
```
Las señales quedan en **PostgreSQL local** (tabla `xsignals_signals`) — misma DB del trading agent. Los perfiles sí están en `/root/.web_agent/xsignals_profiles.json`.

Se agrega un flag `--local` al scan para que guarde en PostgreSQL en lugar de Supabase.

**Paso 2** — Script de análisis de historial:

Un script temporal que lea de PostgreSQL local y responda:
- ¿Cuántas señales/semana posta @aguti00?
- ¿Qué tickers menciona más?
- ¿Distribución long vs short vs neutral?
- ¿Confidence score promedio?

**Paso 3** — Comparar señales contra movimiento real del precio:
Con `yfinance` verificar: cuando @aguti00 dijo "long NVDA", ¿subió NVDA en las siguientes 24-48h?

**Decisión post-exploración:** con los datos reales se decide si xsignals bloquea trades contrarios, solo boosted, o se ignora.

---

## Fase 1 — Infraestructura broker

**Alpaca** = broker de acciones con API. Equivale a lo que es Kraken para crypto.
- Paper trading: operás con dinero ficticio, misma API que el real
- Crear cuenta en https://alpaca.markets → gratis, solo email
- Genera dos claves: `ALPACA_API_KEY` + `ALPACA_SECRET_KEY` (una para paper, otra para live)
- Las claves van a `/opt/trading/config/.env` como `CHANGE_ME` hasta que las tengas

**Verificación de acceso desde el VPS:**
```bash
curl -s https://api.alpaca.markets/v2/clock
# Debe responder con {"is_open": true/false, ...}
# Si da error → hay bloqueo geográfico (mismo problema que Binance)
```

---

## Fase 2 — Data layer

**Nuevo archivo:** `data/stocks_feed.py`
- OHLCV desde Alpaca Data API (gratuito con cuenta paper)
- Fallback: `yfinance` para cuando Alpaca no tiene datos históricos suficientes
- Timeframes: `5m`, `15m`, `1h`, `1d`
- Los 8 activos del portafolio: `NVDA`, `TSLA`, `AAPL`, `SPY`, `QQQ`, `META`, `AMZN`, `GLD`

**Tablas DB nuevas:** `stocks_sessions`, `stocks_trades`

**Cron xsignals:** `scripts/xsignals_monitor.py` — scan automático cada 30min de todos los perfiles → guarda directamente en tabla `xsignals_signals` en PostgreSQL local → el stocks_agent la consulta desde ahí sin llamar a Supabase

---

## Fase 3 — Estrategia y agente

**Lo que se reutiliza sin cambios:**
- `indicators.py` → EMA, RSI, MACD, ATR, VWAP, Bollinger — funciona igual para acciones
- `risk_manager.py` → misma lógica, ajuste menor de parámetros
- `market_regime.py` → TREND/RANGE/CHOPPY aplica igual

**Lo que se adapta:**

| Parámetro | Crypto actual | Acciones | Razón |
|---|---|---|---|
| `sl_multiplier` | 1.3–1.5 × ATR | 1.0–1.2 × ATR | Acciones menos volátiles |
| `tp_multiplier` | 2.6–3.0 × ATR | 2.0–2.5 × ATR | Movimientos más lentos |
| `vol_ratio breakout` | ≥ 2.0 | ≥ 1.5 | Spikes de volumen más pequeños |
| Horario operativo | 24/7 | Solo NYSE open: 14:30–21:00 UTC | Mercado tiene horario |
| Long/Short | Solo SELL (backtest 2Y) | **Ambos** — estrategia decide | No hay restricción histórica aún |

**Nuevos archivos:**
- `core/stocks_profiles.py` — AssetProfile por acción (clone de asset_profiles.py)
- `strategies/stocks_momentum.py` — momentum adaptado (clone de trend_momentum.py)
- `core/alpaca_session_manager.py` — auth Alpaca (similar a deribit_session_manager.py)
- `agents/stocks_agent.py` — orquestador (clone de strategy_engine.py + capa xsignals)
- `scripts/run_stocks.py` — entry point

---

## Fase 4 — Integración

- `stocks-agent.service` systemd
- Comando `/stocks` y `/stocks_status` en telegram_bot.py
- `AI_MASTER.md` actualizado con el nuevo agente

---

## Mercados internacionales

| Mercado | Cómo | Cuándo |
|---|---|---|
| NYSE/NASDAQ (USA) | Alpaca | Desde el inicio |
| Europa, Asia | Interactive Brokers (IBKR) | Solo si capital > $1,000 |
| LatAm via ETFs | `EWZ` (Brasil), `GXG` (Colombia), `EEM` (emergentes) en Alpaca | Desde el inicio — se operan como acciones USA |
| Forex | Broker separado | Fuera del alcance inicial |

---

## COP → USD para Alpaca

```
Tarjeta débito → Binance P2P (USDT/USD) → Wise (cuenta USD virtual)
    → Wire transfer a Alpaca (acepta wire internacional)

Monto mínimo útil: $50 USD (fractional shares: podés comprar $5 de NVDA)
```

---

## Portafolio inicial de acciones (8 activos)

| Ticker | Sector | Por qué | Perfil xsignals |
|---|---|---|---|
| `NVDA` | Tech/AI | Mayor momentum 2024-26 | unusual_whales, aguti00 |
| `TSLA` | EV/Tech | Altísima volatilidad, muchas señales X | aguti00 |
| `AAPL` | Tech | Liquidez máxima, ATR estable | deitaone |
| `SPY` | ETF S&P500 | Macro gauge, hedge | deitaone |
| `QQQ` | ETF NASDAQ | Tech momentum index | unusual_whales |
| `META` | Tech/Social | Momentum fuerte | aguti00 |
| `AMZN` | Tech/Retail | Tendencias claras | unusual_whales |
| `GLD` | ETF Oro | Correlación con XAU que ya opera el bot | fxhedgers |

`SPY` y `QQQ` también sirven como indicadores macro — si caen, el bot evita posiciones LONG en el resto.

---

## Plataforma técnica — Matemáticas de la estrategia

**Núcleo idéntico al crypto agent:**

Confluence BUY:
- EMA20 > EMA50 → tendencia alcista
- Precio > EMA20 → confirmación
- RSI 45–68 → momentum (no sobrecomprado)
- MACD > Signal + histograma positivo
- Volume ratio > 1.5 (acciones) vs 1.2 (crypto)
- Precio > VWAP

Confluence SELL (short):
- EMA20 < EMA50 → tendencia bajista
- Precio < EMA20 → confirmación
- RSI 32–55 → momentum bajista
- MACD < Signal + histograma negativo
- Volume ratio > 1.5
- Precio < VWAP

MIN_SCORE: 65 (igual que crypto)
MIN_CONFLUENCE_INDICATORS: 3

**RiskManager para $50–$220 en acciones:**
- MAX_RISK_PER_TRADE_PCT: 1.0% (vs 0.5% crypto — acciones más predecibles)
- MAX_PORTFOLIO_EXPOSURE: 8% (vs 5% crypto)
- STOP_LOSS_ATR_MULTIPLIER: 1.0 (vs 1.5 crypto)
- TAKE_PROFIT_ATR_MULT: 2.0 (vs 2.5 crypto)
- MAX_DRAWDOWN_STOP: 10% (igual)
- MAX_CONCURRENT_TRADES: 3 (igual)

---

## Verificación por fase

1. **Fase 0**: `python3 xsignals_monitor.py aguti00` → señales en PostgreSQL tabla `xsignals_signals`
2. **Fase 1**: `curl https://api.alpaca.markets/v2/clock` desde VPS → responde sin error
3. **Fase 2**: `python3 data/stocks_feed.py NVDA 15m 100` → 100 velas de NVDA en DB
4. **Fase 3**: Paper session corriendo → `journalctl -u stocks-agent -f` muestra ciclos
5. **Fase 4**: 4 semanas paper con PF ≥ 1.3 → fondear con $50 real en Alpaca

---

## Pendiente / Decisiones abiertas

- [ ] Crear cuenta Alpaca en alpaca.markets (gratis, solo email) y pasar claves
- [ ] Verificar acceso VPS a api.alpaca.markets (posible bloqueo geográfico como Binance)
- [ ] Ejecutar Fase 0 xsignals y analizar datos reales de @aguti00 antes de integrar
- [ ] Decidir post-exploración: ¿xsignals bloquea trades contrarios o solo boost?
- [ ] Evaluar Interactive Brokers para mercados internacionales cuando capital > $1,000
