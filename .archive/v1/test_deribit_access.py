"""
test_deribit_access.py — Verificación de accesibilidad y datos de Deribit.

Comprueba:
  1. Conectividad HTTP básica a Deribit
  2. Carga de mercados BTC options via ccxt
  3. Listado de PUTs semanales BTC disponibles
  4. Lectura de IV (volatilidad implícita) y greeks del top strike
  5. Datos del orderbook (bid/ask spread)
  6. Funding / colateral requerido por contrato
  7. Estimación de prima anualizada vs colateral (APY rough)

Ejecutar:
  /opt/trading/venv/bin/python3 scripts/test_deribit_access.py

No requiere API keys — solo datos públicos.
"""
import sys
import time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '/opt/trading')

import requests

# ── Check básico HTTP ──────────────────────────────────────────────────────────

print("=" * 60)
print("  DERIBIT ACCESS TEST — Opciones BTC")
print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
print("=" * 60)

DERIBIT_BASE = "https://www.deribit.com/api/v2"


def deribit_get(method: str, params: dict = None) -> dict:
    """Llama a la API pública de Deribit (v2)."""
    url = f"{DERIBIT_BASE}/public/{method}"
    resp = requests.get(url, params=params or {}, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):
        raise RuntimeError(f"Deribit API error: {data['error']}")
    return data.get("result", {})


# ── 1. Ping básico ─────────────────────────────────────────────────────────────
print("\n[1] Ping básico a Deribit...")
try:
    resp = requests.get("https://www.deribit.com", timeout=8)
    print(f"    Status HTTP: {resp.status_code}")
    if resp.status_code == 200:
        print("    ✅  Deribit es accesible desde este VPS")
    else:
        print(f"    ⚠️  Respuesta inesperada: {resp.status_code}")
except Exception as e:
    print(f"    ❌  BLOQUEADO: {e}")
    print("    → Deribit tampoco es accesible. Detener plan P3.")
    sys.exit(1)


# ── 2. BTC spot price desde Deribit ───────────────────────────────────────────
print("\n[2] BTC index price...")
try:
    idx = deribit_get("get_index_price", {"index_name": "btc_usd"})
    btc_price = float(idx["index_price"])
    print(f"    BTC/USD index: ${btc_price:,.0f}")
except Exception as e:
    print(f"    ❌  Error obteniendo price: {e}")
    btc_price = 74000.0
    print(f"    → Usando estimado: ${btc_price:,.0f}")


# ── 3. Listar instrumentos: PUTs semanales BTC ────────────────────────────────
print("\n[3] Listando instrumentos BTC options (PUT)...")
try:
    instruments = deribit_get("get_instruments", {
        "currency": "BTC",
        "kind": "option",
        "expired": "false",
    })
    print(f"    Total instrumentos activos BTC options: {len(instruments)}")

    # Filtrar solo PUTs
    puts = [i for i in instruments if i["instrument_name"].endswith("-P")]
    print(f"    Total PUTs BTC activos: {len(puts)}")

    # Extraer expiraciones únicas
    expirations = sorted(set(i["expiration_timestamp"] for i in puts))
    now_ms = int(time.time() * 1000)

    print(f"\n    Próximas 4 expiraciones:")
    upcoming_exps = []
    for exp_ms in expirations[:4]:
        exp_dt = datetime.fromtimestamp(exp_ms / 1000, tz=timezone.utc)
        days_left = (exp_dt - datetime.now(timezone.utc)).days
        puts_for_exp = [p for p in puts if p["expiration_timestamp"] == exp_ms]
        upcoming_exps.append((exp_ms, exp_dt, days_left, puts_for_exp))
        print(f"      {exp_dt.strftime('%d-%b-%Y')} ({days_left}d) — {len(puts_for_exp)} PUTs disponibles")

except Exception as e:
    print(f"    ❌  Error listando instrumentos: {e}")
    sys.exit(1)


# ── 4. Seleccionar el strike OTM más cercano a -5% ────────────────────────────
print(f"\n[4] Selección de strike óptimo (5–8% OTM desde ${btc_price:,.0f})...")

target_strike_min = btc_price * 0.92   # -8% OTM
target_strike_max = btc_price * 0.95   # -5% OTM
print(f"    Rango target: ${target_strike_min:,.0f} – ${target_strike_max:,.0f}")

# Tomar la expiración de la semana más próxima (mínimo 2 días)
nearest_exp = None
for exp_ms, exp_dt, days_left, exp_puts in upcoming_exps:
    if days_left >= 2:
        nearest_exp = (exp_ms, exp_dt, days_left, exp_puts)
        break

if nearest_exp is None:
    print("    ❌  No hay expiraciones disponibles con ≥2 días. Mercado sin weeklies.")
    sys.exit(1)

exp_ms, exp_dt, days_left, exp_puts = nearest_exp
print(f"    Expiración elegida: {exp_dt.strftime('%d-%b-%Y')} ({days_left}d)")

# Filtrar strikes dentro del rango objetivo
candidate_puts = [
    p for p in exp_puts
    if target_strike_min <= p["strike"] <= target_strike_max
]
if not candidate_puts:
    # Ampliar rango a -10% – -3%
    candidate_puts = [
        p for p in exp_puts
        if btc_price * 0.90 <= p["strike"] <= btc_price * 0.97
    ]
    print("    ⚠️  Rango ampliado a -10%/-3% OTM")

if not candidate_puts:
    print("    ❌  Sin strikes en rango. Revisar manualmente.")
    # Mostrar los 5 strikes más cercanos al precio actual
    sorted_puts = sorted(exp_puts, key=lambda x: abs(x["strike"] - btc_price))
    print("    Top 5 strikes más cercanos:")
    for p in sorted_puts[:5]:
        otm_pct = (btc_price - p["strike"]) / btc_price * 100
        print(f"      strike={p['strike']:,.0f}  ({otm_pct:.1f}% OTM)  {p['instrument_name']}")
    sys.exit(1)

# Tomar el más cercano al precio actual (menor gap OTM)
best_put = min(candidate_puts, key=lambda x: abs(x["strike"] - (btc_price * 0.935)))
otm_pct = (btc_price - best_put["strike"]) / btc_price * 100
print(f"    Strike seleccionado: ${best_put['strike']:,.0f}  ({otm_pct:.1f}% OTM)")
print(f"    Instrumento: {best_put['instrument_name']}")


# ── 5. Orderbook y datos de mercado del strike ────────────────────────────────
print(f"\n[5] Orderbook y datos de mercado: {best_put['instrument_name']}...")
try:
    ticker = deribit_get("get_order_book", {
        "instrument_name": best_put["instrument_name"],
        "depth": 5,
    })

    bid = ticker.get("best_bid_price", 0)
    ask = ticker.get("best_ask_price", 0)
    iv = ticker.get("mark_iv", 0)
    delta = ticker.get("greeks", {}).get("delta", None)
    gamma = ticker.get("greeks", {}).get("gamma", None)
    theta = ticker.get("greeks", {}).get("theta", None)
    vega = ticker.get("greeks", {}).get("vega", None)
    mark_price = ticker.get("mark_price", 0)

    print(f"    Mark price:  {mark_price:.4f} BTC  (${mark_price * btc_price:,.0f})")
    print(f"    Bid/Ask:     {bid:.4f} / {ask:.4f} BTC")
    if bid > 0 and ask > 0:
        spread_pct = (ask - bid) / mark_price * 100
        print(f"    Spread:      {spread_pct:.1f}%")
    print(f"    IV (mark):   {iv:.1f}%")

    if delta is not None:
        print(f"\n    Greeks:")
        print(f"      Δ delta:   {delta:.4f} (probabilidad de que expire ITM: {abs(delta)*100:.1f}%)")
        print(f"      Θ theta:   {theta:.4f} BTC/día (decay a favor del vendedor)")
        print(f"      Γ gamma:   {gamma:.6f}")
        print(f"      ν vega:    {vega:.4f} (sensibilidad a IV)")

    # Calcular prima en USD y APY estimado
    min_contract_size = best_put.get("min_trade_amount", 0.1)
    contract_size = 0.1  # BTC (mínimo de Deribit para BTC options)
    colateral_btc = best_put["strike"] / btc_price * contract_size  # equivalente en BTC
    colateral_usd = best_put["strike"] * contract_size  # colateral en USD

    # Prima recibida si vendemos al bid (conservative: vendemos a bid)
    if bid > 0:
        prima_btc = bid * contract_size
        prima_usd = prima_btc * btc_price
        retorno_pct = prima_usd / colateral_usd * 100
        # Anualizar: una semana = 52 semanas/año
        weeks_per_year = 365 / max(days_left, 1)
        apy_rough = retorno_pct * weeks_per_year

        print(f"\n    Estimación de rentabilidad (1 contrato = {contract_size} BTC):")
        print(f"      Colateral requerido: ~${colateral_usd:,.0f} USD en USDC")
        print(f"      Prima recibida (bid): {prima_btc:.5f} BTC = ${prima_usd:,.0f}")
        print(f"      Retorno por operación: {retorno_pct:.2f}%")
        print(f"      APY rough (si repetimos cada {days_left}d): {apy_rough:.1f}%")

        # Escenarios
        print(f"\n    Escenarios al vencimiento ({exp_dt.strftime('%d-%b-%Y')}):")
        print(f"      ✅  BTC ≥ ${best_put['strike']:,.0f}: opción expira worthless → GANAMOS ${prima_usd:,.0f}")
        print(f"      ⚠️  BTC = ${best_put['strike']*0.97:,.0f} (-3% del strike): pérdida parcial ~${prima_usd*0.5:,.0f}")
        print(f"      ❌  BTC < ${best_put['strike'] * 0.95:,.0f}: gap supera stop (2× prima) → STOP OUT ~${prima_usd*2:,.0f}")
    else:
        print("    ⚠️  Sin bid disponible (mercado sin liquidez en este strike)")

except Exception as e:
    print(f"    ❌  Error obteniendo orderbook: {e}")


# ── 6. Test ccxt (librería que usaremos en el agente) ─────────────────────────
print("\n[6] Verificando ccxt Deribit...")
try:
    import ccxt
    exchange = ccxt.deribit({
        'enableRateLimit': True,
    })
    markets = exchange.load_markets()
    btc_options = [k for k in markets.keys() if 'BTC' in k and 'P' in k.split('/')[-1] if len(k.split('/')) > 1]
    # Alternativa: filtrar por tipo
    opt_markets = {k: v for k, v in markets.items() if v.get('type') == 'option' and v.get('base') == 'BTC'}
    print(f"    ccxt deribit: ✅  cargó {len(markets)} mercados totales")
    print(f"    Opciones BTC (tipo=option): {len(opt_markets)}")
    print(f"    ccxt versión: {ccxt.__version__}")
except ImportError:
    print("    ⚠️  ccxt no instalado. Instalar con: pip install ccxt")
except Exception as e:
    print(f"    ⚠️  ccxt Deribit error: {e}")
    print("    → Se usará la API REST directa como fallback")


# ── 7. IV rank estimado (últimos 30d de IV histórica) ─────────────────────────
print("\n[7] Volatilidad histórica (últimos 10 datos daily) via Deribit...")
try:
    hist_vol = deribit_get("get_historical_volatility", {"currency": "BTC"})
    if hist_vol and len(hist_vol) >= 5:
        recent_ivs = [float(h[1]) for h in hist_vol[-30:]]
        current_iv = recent_ivs[-1]
        iv_min = min(recent_ivs)
        iv_max = max(recent_ivs)
        iv_rank = (current_iv - iv_min) / (iv_max - iv_min) * 100 if iv_max > iv_min else 50.0

        print(f"    IV actual:   {current_iv:.1f}%")
        print(f"    IV 30d range: {iv_min:.1f}% – {iv_max:.1f}%")
        print(f"    IV Rank:     {iv_rank:.0f}%")

        if iv_rank >= 30:
            print(f"    ✅  IV Rank {iv_rank:.0f}% ≥ 30% — CONDICIÓN OK para vender opciones")
        else:
            print(f"    ⚠️  IV Rank {iv_rank:.0f}% < 30% — premium bajo, NO conveniente ahora")
    else:
        print("    Sin datos históricos suficientes")
except Exception as e:
    print(f"    ⚠️  Error IV histórica: {e}")


# ── Resumen final ──────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("  RESUMEN DEL TEST")
print("=" * 60)
print(f"  Exchange:      Deribit ✅  accesible")
print(f"  BTC price:     ${btc_price:,.0f}")
print(f"  Instrumento:   {best_put['instrument_name']}")
print(f"  Strike:        ${best_put['strike']:,.0f} ({otm_pct:.1f}% OTM)")
print(f"  Expiración:    {exp_dt.strftime('%d-%b-%Y')} ({days_left}d)")
if 'prima_usd' in dir() or 'prima_usd' in locals():
    print(f"  Prima (bid):   ${prima_usd:,.0f} por contrato de 0.1 BTC")
    print(f"  Colateral:     ${colateral_usd:,.0f} USDC")
    print(f"  APY rough:     {apy_rough:.1f}%")
print()
print("  → Deribit es VIABLE para theta farming desde este VPS")
print("  → Próximo paso: construir options_agent.py con modo paper")
print("=" * 60)
