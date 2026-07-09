# STOCKS AGENT — Plan de Mejora v1.1

> **Motivación**: El 22 de Mayo 2026, el stocks agent ejecutó 75 trades fantasmas de QQQ
> con precio congelado en $712.92, generando +$554 de PnL falso en 6 horas.
> Este documento analiza la causa raíz y propone soluciones robustas.

---

## 1. ¿Qué pasó exactamente?

### Cronología

| Hora (UTC) | Evento |
|---|---|
| 20:35 | QQQ cierra un trade legítimo con TP @ $717.25, PnL +$4.86 |
| 20:35 | El agente detecta señal QQQ BUY score=93 |
| 20:35 | Abre nuevo trade QQQ BUY @ $712.92 |
| 20:35 | **NYSE CIERRA** (21:00 UTC = 17:00 EST) |
| 20:35 → 03:00+ | Loop infinito: Alpaca devuelve $712.92 (último trade antes del cierre). El agente cree que el precio no se movió. Vuelve a abrir. TP se dispara con precio simulado. Cierra. Repite. |

### Mecanismo del fallo

```
1. get_price("QQQ") → Alpaca API → último trade = $712.92 (pre-cierre)
2. trade_monitor.check() → precio actual $717.25 → TP alcanzado → cerrar
3. Nueva señal BUY → entry_price = get_price("QQQ") = $712.92 (mismo precio)
4. Abrir trade → SL y TP calculados con precio congelado
5. GOTO 2
```

**El precio NUNCA cambió.** Alpaca devolvía el último trade del viernes una y otra vez. El agente no tiene detección de staleness.

### ¿Ganamos o perdimos?

**No fue ni ganancia ni pérdida real.** Los 75 trades eran PAPER (Alpaca paper trading). Las órdenes se ejecutaron en el sandbox de Alpaca, no en el mercado real. El PnL registrado en la DB era una ilusión generada por el loop de precio congelado.

Si hubiera sido live trading con dinero real:
- Las órdenes se habrían ejecutado a precios de mercado reales (no $712.92)
- El loop no habría ocurrido porque el precio real SÍ cambia
- Pero el riesgo es que el agente opere fuera de horario con datos stale → potenciales pérdidas reales

---

## 2. Causa raíz

**El `StocksFeed.get_price()` no valida la frescura del dato.**

```python
# Actual (roto):
def get_price(self, symbol):
    trade = self._alpaca.get_latest_trade(symbol)
    return float(trade.get('p', 0))  # Siempre devuelve algo, nunca None
```

No hay:
- Timestamp del último trade
- Comparación con el precio anterior
- Límite de edad del dato
- Verificación de horario de mercado

---

## 3. Plan de mejora

### Fase 1 — Staleness guard (inmediato)

Agregar validación de frescura en `StocksFeed.get_price()`:

```python
def get_price(self, symbol: str) -> float:
    symbol = symbol.upper()
    if self._alpaca_available:
        try:
            trade = self._alpaca.get_latest_trade(symbol)
            price = float(trade.get('p', 0))
            ts = trade.get('t', '')
            
            # Validar frescura
            if ts:
                trade_time = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                age_seconds = (datetime.now(timezone.utc) - trade_time).total_seconds()
                
                # Si el último trade tiene > 5 minutos, el dato es stale
                if age_seconds > 300:
                    logger.warning(f"STALE PRICE: {symbol} last trade {age_seconds:.0f}s ago")
                    return None  # None → el agente salta este símbolo
            
            # Detectar precio congelado (mismo precio que la última vez)
            last = self._last_price.get(symbol)
            if last and abs(price - last['price']) < 0.01 and age_seconds > 60:
                if (datetime.now(timezone.utc) - last['ts']).seconds > 300:
                    logger.warning(f"FROZEN PRICE: {symbol} ${price} unchanged for >5min")
                    return None
            
            self._last_price[symbol] = {'price': price, 'ts': datetime.now(timezone.utc)}
            return price
        except Exception:
            pass
    return None  # Sin dato fresco → no operar
```

### Fase 2 — Hard stop fuera de horario (inmediato)

El agente ya tiene `_is_nyse_open()` pero solo lo usa para saltar ciclos completos. Agregar un segundo check en `get_price()`:

```python
def get_price(self, symbol: str) -> float:
    if not self._is_nyse_open():
        return None  # Fuera de horario → sin datos
    ...
```

### Fase 3 — Circuit breaker por repetición (esta semana)

Si el mismo símbolo abre y cierra trades idénticos (misma entry, mismo TP) más de 3 veces en 30 minutos, pausar el símbolo por 1 hora:

```python
# En stocks_agent.py, después de close_trade():
if self._detect_overtrade_loop(symbol, entry_price):
    logger.error(f"OVERTRADE LOOP: {symbol} — pausando 1h")
    redis.set(f"cooldown:stocks:{symbol}", "3600", ex=3600)
    return
```

### Fase 4 — Health check de frescura (esta semana)

Agregar al health check un indicador de datos stale para stocks:

```python
def check_stocks_data_fresh():
    """Verificar que el feed de stocks tiene datos < 5 min."""
    # Consultar último trade en stocks_trades
    # Si el último trade tiene > 15 min, alertar
```

---

## 4. Lecciones aprendidas

1. **Nunca confiar en un feed externo sin validación de frescura.** Alpaca, yfinance, CCXT — todos pueden devolver datos stale.

2. **El paper trading NO es inofensivo.** Aunque no haya dinero real, datos falsos contaminan las métricas y llevan a decisiones equivocadas (como pensar que el stocks agent tiene +55% de retorno).

3. **Validar en horario de mercado.** El crypto agent ya tiene `STALE DATA` warnings. El stocks agent necesita lo mismo.

4. **Circuit breakers por repetición.** Si un patrón se repite idéntico N veces, algo está mal. El loop de QQQ era detectable: misma entry, mismo TP, cada 5 minutos.

---

## 5. Estado actual (post-limpieza)

| Métrica | Antes (con fake) | Después (real) |
|---|---|---|
| Trades | 113 | **38** |
| WR | — | **63.2%** |
| PnL | +$591.96 | **+$37.86 (+3.8%)** |
| QQQ trades | 94 | **19 reales** |

El rendimiento real es modesto pero positivo: +3.8% en 4 días hábiles con 38 trades. Nada espectacular, pero real.
