# POLYMARKET SNIPE AGENT — Documentación IA

> Agente de late-entry y arbitraje para mercados Up/Down 15m de Polymarket.
> Reemplaza al BTC Direction Agent (WR=0%, 183 trades, -$497).
> Estado: **NUEVO** — Mayo 2026
> Basado en: [LuciferForge/polymarket-btc-autotrader](https://github.com/LuciferForge/polymarket-btc-autotrader)

---

## 1. Resumen ejecutivo

El PolyMarket SNIPE Agent opera dos estrategias complementarias en mercados binarios Up/Down de 15 minutos en Polymarket:

| Estrategia | WR | Riesgo | Descripción |
|------------|-----|--------|-------------|
| **SNIPE** | ~94% | Muy bajo | Compra el lado ganador en minuto 13-14.5 a $0.93-$0.97 |
| **ARB** | 100% | Cero | Compra YES+NO cuando suma < $0.985 |

Ambas estrategias son **de muy bajo riesgo** porque no intentan predecir direcciones — la SNIPE espera hasta que el movimiento ya está casi decidido, y el ARB es matemáticamente risk-free.

---

## 2. Por qué reemplaza al BTC Direction Agent

| | BTC Direction (antiguo) | PolySnipe (nuevo) |
|---|---|---|
| Señal | Momentum 10m de DB → outcome 5-900 min después | Precio Binance en min 13-14 → quedan 30-90s |
| WR | 0% (183 trades) | 94% (17W/1L documentado) |
| Riesgo | Alto (predicción) | Muy bajo (confirmación) |
| Capital min | $500 (agotado) | $300 |
| Edge | Ninguno (estructuramente inviable) | Late-entry: el movimiento ya ocurrió |

---

## 3. Arquitectura

```
Binance (price feed) ──→ Strategy Engine (SNIPE / ARB)
                              │
                    Gamma API (market discovery)
                              │
                         DB: snipe_trades
                              │
                    Resolution: Binance close price
                              │
                         Telegram (alertas)
```

### Archivos

| Componente | Archivo |
|---|---|
| Agente principal | `agents/polymarket_snipe.py` |
| Entry point | `scripts/run_polymarket_snipe.py` |
| Config | `config/exchange_config.yaml` → `polymarket_snipe` |
| Servicio | `polymarket-snipe.service` |
| Tabla DB | `snipe_trades` |

---

## 4. Estrategia SNIPE — cómo funciona

1. Cada 30s escanea mercados `{asset}-updown-15m-{ts}` para BTC, ETH, SOL, XRP
2. En minuto 13-14.5 de la ventana, consulta precio open/close en Binance
3. Si el asset se movió >0.10% desde el open, dirección está decidida
4. Si el lado ganador cotiza entre $0.88-$0.97 en Polymarket → compra
5. Al cerrar la ventana (15 min), resuelve contra close de Binance
6. Si acertó: profit = (1.00 - entry) × shares | Si falló: pérdida = entry × shares

**Backtest del autor**: 17W/1L con threshold 0.10% en minuto 13.

---

## 5. Estrategia ARB — cómo funciona

1. En cada ciclo verifica YES+NO mid prices desde Gamma API
2. Si suma < $0.985 → compra ambos lados
3. Al resolverse el mercado, uno vale $1.00 y el otro $0.00
4. Profit garantizado = (1.00 - suma) × shares

---

## 6. Configuración

```yaml
polymarket_snipe:
  initial_paper_balance: 500.0
  scan_interval_seconds: 30
  assets: [btc, eth, sol, xrp]
  snipe:
    min_minute: 13
    max_minute: 14.5
    momentum_threshold_pct: 0.10
    max_entry_price: 0.97
    min_entry_price: 0.88
    order_size_shares: 40
  arb:
    target_cost: 0.985
    min_gap: 0.015
    order_size_shares: 25
  risk:
    max_daily_loss: 5.0
    max_concurrent_positions: 3
```

---

## 7. Base de datos

```sql
CREATE TABLE snipe_trades (
    id              UUID PRIMARY KEY,
    asset           VARCHAR(10),       -- BTC, ETH, SOL, XRP
    strategy        VARCHAR(20),       -- SNIPE, ARB
    market_slug     VARCHAR(200),      -- btc-updown-15m-{ts}
    condition_id    VARCHAR(100),
    direction       VARCHAR(4),        -- UP, DOWN, BOTH
    entry_price     NUMERIC(10,4),
    shares          NUMERIC(14,4),
    cost_usdc       NUMERIC(10,4),
    move_pct        NUMERIC(8,4),      -- % movimiento del asset
    window_start    BIGINT,            -- Unix timestamp inicio ventana 15m
    window_end      BIGINT,            -- Unix timestamp fin ventana
    outcome         VARCHAR(8),        -- WIN, LOSS, EXPIRED
    pnl_usdc        NUMERIC(10,4),
    status          VARCHAR(8),        -- OPEN, CLOSED
    paper_trade     BOOLEAN,
    timestamp_open  TIMESTAMPTZ,
    timestamp_close TIMESTAMPTZ
);
```

---

## 8. Comandos

```bash
# Estado del servicio
systemctl status polymarket-snipe

# Logs en tiempo real
journalctl -u polymarket-snipe -f

# Ver mercados activos
cd /opt/trading && venv/bin/python3 scripts/run_polymarket_snipe.py --scan

# Estadísticas
cd /opt/trading && venv/bin/python3 scripts/run_polymarket_snipe.py --stats

# Forzar resolución de trades
cd /opt/trading && venv/bin/python3 scripts/run_polymarket_snipe.py --resolve

# Reiniciar
systemctl restart polymarket-snipe
```

---

## 9. Comandos Telegram

```
/snipe         → Estado actual (stats, open trades, P&L)
/snipe_scan    → Mercados activos ahora
```

---

## 10. Dashboard

El dashboard incluye sección "PolySnipe" en la pestaña Polymarket, mostrando:
- Trades totales y abiertos
- Win rate por estrategia (SNIPE vs ARB)
- P&L acumulado
- Balance actual
- Últimos 5 trades cerrados

---

## 11. Plan de fondeo (live trading)

Cuando se active con fondos reales:
1. **Capital**: $50-80 del fondeo de $300
2. **Prerequisitos**: 2 semanas paper con WR ≥ 80%
3. **Riesgo**: $5/trade máximo, stop diario $5
4. **API keys**: requiere POLYMARKET_API_KEY, POLYMARKET_SECRET, POLYMARKET_PASSPHRASE en .env

---

## 12. Historial de decisiones

| Fecha | Decisión | Razón |
|-------|----------|-------|
| May 2026 | Creación del agente | Reemplaza BTC Direction (0% WR). SNIPE + ARB con edge validado externamente |
