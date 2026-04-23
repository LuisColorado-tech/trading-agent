#!/usr/bin/env python3
"""
xsignals_analyze.py — Análisis de historial de señales scrapeadas desde X.

Lee de la tabla xsignals_signals en PostgreSQL y responde:
  - ¿Cuántas señales por perfil/semana?
  - ¿Qué tickers menciona más cada perfil?
  - ¿Distribución long vs short vs neutral?
  - ¿Confidence score promedio?
  - ¿Cuánto movió el precio después de una señal? (requiere yfinance)

Uso:
  python3 scripts/xsignals_analyze.py                  # resumen de todos los perfiles
  python3 scripts/xsignals_analyze.py aguti00           # análisis de un perfil
  python3 scripts/xsignals_analyze.py --backtest        # valida señales vs precio real
"""
import os
import sys
from datetime import datetime, timezone, timedelta
from collections import Counter

sys.path.insert(0, '/opt/trading')

from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')

from sqlalchemy import create_engine, text


def get_engine():
    db_url = os.environ.get('DB_URL')
    if not db_url:
        h = os.environ.get('POSTGRES_HOST', 'localhost')
        p = os.environ.get('POSTGRES_PORT', '5432')
        u = os.environ.get('POSTGRES_USER', 'trading')
        pw = os.environ.get('POSTGRES_PASSWORD', '')
        d = os.environ.get('POSTGRES_DB', 'trading_agent')
        db_url = f'postgresql://{u}:{pw}@{h}:{p}/{d}'
    return create_engine(db_url)


def analyze_profile(engine, profile: str = None):
    """Análisis estadístico de señales de un perfil (o todos)."""
    where = "WHERE profile = :profile" if profile else ""
    params = {'profile': profile} if profile else {}

    with engine.connect() as conn:
        # Total de señales
        total = conn.execute(
            text(f"SELECT COUNT(*) FROM xsignals_signals {where}"), params
        ).scalar()

        if total == 0:
            print(f"\n{'@'+profile if profile else 'Todos los perfiles'}: sin señales en la DB.")
            print("Ejecuta primero: python3 scripts/xsignals_monitor.py" + (f" {profile}" if profile else ""))
            return

        # Señales por perfil
        perfiles = conn.execute(
            text(f"SELECT profile, COUNT(*) as n FROM xsignals_signals {where} GROUP BY profile ORDER BY n DESC"),
            params,
        ).fetchall()

        # Distribución de dirección
        sides = conn.execute(
            text(f"SELECT side, COUNT(*) as n FROM xsignals_signals {where} GROUP BY side ORDER BY n DESC"),
            params,
        ).fetchall()

        # Top tickers
        tickers = conn.execute(
            text(f"""SELECT ticker, COUNT(*) as n FROM xsignals_signals
                     {where} {'AND' if where else 'WHERE'} ticker != 'UNKNOWN'
                     GROUP BY ticker ORDER BY n DESC LIMIT 10"""),
            params,
        ).fetchall()

        # Confidence promedio
        conf_stats = conn.execute(
            text(f"""SELECT
                     ROUND(AVG(confidence), 1) as avg_conf,
                     MIN(confidence) as min_conf,
                     MAX(confidence) as max_conf
                     FROM xsignals_signals {where}"""),
            params,
        ).fetchone()

        # Señales por mercado (stocks/crypto/forex)
        markets = conn.execute(
            text(f"SELECT market, COUNT(*) as n FROM xsignals_signals {where} GROUP BY market ORDER BY n DESC"),
            params,
        ).fetchall()

        # Señales en últimas 24h / 7 días / 30 días
        recency = conn.execute(
            text(f"""SELECT
                     COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '24 hours') as last_24h,
                     COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '7 days') as last_7d,
                     COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '30 days') as last_30d
                     FROM xsignals_signals {where}"""),
            params,
        ).fetchone()

    title = f"@{profile}" if profile else "Todos los perfiles"
    print(f"\n{'='*55}")
    print(f"  ANÁLISIS xsignals — {title}")
    print(f"{'='*55}")
    print(f"  Total señales históricas: {total}")
    print(f"  Últimas 24h: {recency.last_24h}  |  7 días: {recency.last_7d}  |  30 días: {recency.last_30d}")

    if not profile:
        print(f"\n  Señales por perfil:")
        for row in perfiles:
            print(f"    @{row.profile:<20} {row.n:>5} señales")

    print(f"\n  Dirección (long/short/neutral):")
    for row in sides:
        pct = round(row.n / total * 100, 1)
        bar = '█' * int(pct / 5)
        print(f"    {row.side:<10} {row.n:>5}  ({pct:>5}%)  {bar}")

    print(f"\n  Top tickers mencionados:")
    for row in tickers:
        print(f"    ${row.ticker:<8} {row.n:>4} veces")

    print(f"\n  Confidence score: avg={conf_stats.avg_conf}  min={conf_stats.min_conf}  max={conf_stats.max_conf}")

    print(f"\n  Mercados:")
    for row in markets:
        print(f"    {row.market:<10} {row.n:>5} señales")

    print(f"{'='*55}\n")


def backtest_signals(engine, profile: str = None, days_back: int = 30):
    """Compara señales históricas contra el movimiento real del precio.

    Para cada señal con ticker conocido, verifica si el precio se movió
    en la dirección esperada en las siguientes 24h y 48h.
    """
    try:
        import yfinance as yf
    except ImportError:
        print("yfinance no instalado. Ejecuta: pip install yfinance")
        return

    params = {'profile': profile} if profile else {}

    with engine.connect() as conn:
        signals = conn.execute(
            text(f"""SELECT id, profile, ticker, side, confidence, created_at, published_hint
                     FROM xsignals_signals
                     WHERE {'profile = :profile AND' if profile else ''}
                     ticker != 'UNKNOWN' AND side != 'neutral'
                     ORDER BY created_at DESC LIMIT 100"""),
            params,
        ).fetchall()

    if not signals:
        print(f"Sin señales con ticker+dirección en los últimos {days_back} días.")
        return

    print(f"\n{'='*55}")
    print(f"  BACKTEST xsignals — últimos {days_back} días")
    print(f"  Señales a validar: {len(signals)}")
    print(f"{'='*55}")

    hits_24h = 0
    hits_48h = 0
    total_valid = 0
    tickers_cache = {}

    for sig in signals:
        ticker = sig.ticker.replace('$', '').upper()
        # Mapear tickers que yfinance no conoce con su nombre estándar
        TICKER_MAP = {'TSMC': 'TSM', 'GOOGL': 'GOOGL', 'GOOG': 'GOOG'}
        ticker = TICKER_MAP.get(ticker, ticker)
        side = sig.side

        # Usar published_hint (fecha real del tweet) si está disponible
        if sig.published_hint:
            try:
                from datetime import datetime, timezone
                signal_dt = datetime.fromisoformat(sig.published_hint.replace('Z', '+00:00'))
            except Exception:
                signal_dt = sig.created_at
        else:
            signal_dt = sig.created_at

        if ticker not in tickers_cache:
            try:
                hist = yf.download(ticker, period='3mo', interval='1d', progress=False, auto_adjust=True)
                tickers_cache[ticker] = hist
            except Exception:
                tickers_cache[ticker] = None

        hist = tickers_cache.get(ticker)
        if hist is None or hist.empty:
            continue

        signal_date = signal_dt.date() if hasattr(signal_dt, 'date') else signal_dt
        # Buscar precio de cierre el día de la señal y los siguientes 2 días
        try:
            idx = hist.index.date
            entry_rows = hist[[d >= signal_date for d in idx]]
            if len(entry_rows) < 2:
                continue
            price_entry = float(entry_rows.iloc[0]['Close'])
            price_24h = float(entry_rows.iloc[1]['Close']) if len(entry_rows) > 1 else None
            price_48h = float(entry_rows.iloc[2]['Close']) if len(entry_rows) > 2 else None
        except Exception:
            continue

        total_valid += 1
        move_24h = (price_24h - price_entry) / price_entry if price_24h else None
        move_48h = (price_48h - price_entry) / price_entry if price_48h else None

        hit_24h = (side == 'long' and move_24h and move_24h > 0) or \
                  (side == 'short' and move_24h and move_24h < 0)
        hit_48h = (side == 'long' and move_48h and move_48h > 0) or \
                  (side == 'short' and move_48h and move_48h < 0)

        if hit_24h:
            hits_24h += 1
        if hit_48h:
            hits_48h += 1

    if total_valid == 0:
        print("  Sin suficientes datos de precio para validar.")
        return

    wr_24h = round(hits_24h / total_valid * 100, 1)
    wr_48h = round(hits_48h / total_valid * 100, 1)

    print(f"  Señales validadas contra precio: {total_valid}")
    print(f"  Win rate 24h: {wr_24h}%  ({hits_24h}/{total_valid})")
    print(f"  Win rate 48h: {wr_48h}%  ({hits_48h}/{total_valid})")
    print(f"\n  Interpretación:")
    # Evaluar edge en 48h (ventana más relevante para value/swing trading)
    if wr_48h >= 65 and total_valid >= 15:
        print(f"  ✅ EDGE REAL a 48h (WR={wr_48h}%, n={total_valid})")
        print(f"     @{profile or 'perfiles'} muestra dirección estadísticamente significativa")
        print(f"     → Usar como boost en estrategia swing (horizonte 2-3 días)")
    elif wr_24h >= 55:
        print(f"  ✅ Edge real a 24h (WR={wr_24h}%) → boost para estrategia intradía")
    elif wr_24h >= 50 or wr_48h >= 55:
        print(f"  ⚠️  Edge marginal → usar solo como confirmación, no señal primaria")
    else:
        print(f"  ❌ Sin edge estadístico (WR 24h={wr_24h}%, 48h={wr_48h}%) → señales no accionables")
    if total_valid < 30:
        print(f"  ⚠️  Muestra pequeña ({total_valid} señales) — necesita más datos para confirmación estadística")
    print(f"{'='*55}\n")


def main():
    args = sys.argv[1:]
    backtest = '--backtest' in args
    profile = next((a for a in args if not a.startswith('--')), None)

    engine = get_engine()

    analyze_profile(engine, profile)

    if backtest:
        backtest_signals(engine, profile)


if __name__ == '__main__':
    main()
