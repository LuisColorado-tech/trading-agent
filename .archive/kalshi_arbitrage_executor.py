#!/usr/bin/env python3
"""
KalshiArbitrageAgent — Ejecutor de arbitraje cross-platform Polymarket ↔ Kalshi.

Monitorea los mercados BTC 1-Hour de ambas plataformas cada 60 segundos.
Cuando detecta una oportunidad sin riesgo (costo total < $0.995), registra
el trade en BD para tracking de paper trading.

Paper trading: no ejecuta órdenes reales (requiere API keys + funding).
Solo detecta, registra y notifica oportunidades.
"""
import os
import sys
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import requests as req
from loguru import logger
from sqlalchemy import create_engine, text

sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')

from strategies.kalshi_arbitrage import KalshiArbitrageStrategy, ArbitrageSignal
from data.kalshi_feed import KalshiFeed
from core.notifications import send_telegram

# ── Config ──
POLYMARKET_GAMMA = 'https://gamma-api.polymarket.com'
INITIAL_BALANCE = 500.0
POSITION_SIZE = 50.0       # USD por pierna
CYCLE_SECONDS = 60         # Escanear cada 60s
MAX_OPEN = 3

# ── DB ──
db_url = (
    f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
    f"@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}"
    f"/{os.getenv('POSTGRES_DB', 'trading_agent')}"
)
engine = create_engine(db_url)

feed = KalshiFeed()
strategy = KalshiArbitrageStrategy()

# ── Estado ──
_last_signal_time: float = 0
_daily_pnl: float = 0.0


def _ensure_table():
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS kalshi_arbitrage (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                strategy VARCHAR(1),
                poly_slug TEXT,
                poly_token VARCHAR(5),
                poly_price NUMERIC(8,4),
                kalshi_ticker TEXT,
                kalshi_side VARCHAR(3),
                kalshi_price NUMERIC(8,4),
                total_cost NUMERIC(8,4),
                profit_per_unit NUMERIC(8,4),
                profit_pct NUMERIC(8,2),
                position_size NUMERIC(8,2),
                status VARCHAR(20) DEFAULT 'DETECTED',
                timestamp TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        conn.commit()
    logger.info('kalshi_arbitrage table ready')


def _fetch_polymarket_btc_prices() -> Optional[dict]:
    """Obtiene precios UP/DOWN del mercado BTC 1h más cercano en Polymarket."""
    try:
        # Buscar eventos BTC
        resp = req.get(
            f'{POLYMARKET_GAMMA}/events',
            params={'tag': 'bitcoin', 'limit': 20, 'active': 'true', 'closed': 'false'},
            timeout=10,
        )
        if resp.status_code != 200:
            return None

        events = resp.json()
        for ev in events:
            title = ev.get('title', '').lower()
            slug = ev.get('slug', '')
            if 'btc' not in title and 'bitcoin' not in title:
                continue
            if 'hourly' in title or '1h' in title or '60min' in title or 'up/down' in title:
                # Get market data
                markets = ev.get('markets', [])
                prices = {'slug': slug, 'title': title}
                for m in markets:
                    o1 = m.get('outcome', '')
                    o2 = m.get('outcomePrices', '[0,0]')
                    try:
                        parsed = json.loads(o2) if isinstance(o2, str) else o2
                        price = float(parsed) if isinstance(parsed, float) else float(parsed[0]) if isinstance(parsed, list) else 0.5
                    except Exception:
                        price = float(m.get('price', 0.5)) if m.get('price') else 0.5
                    if 'up' in o1.lower() or 'yes' in o1.lower():
                        prices['up'] = price
                    elif 'down' in o1.lower() or 'no' in o1.lower():
                        prices['down'] = price
                if 'up' in prices and 'down' in prices:
                    return prices

        return None
    except Exception as e:
        logger.debug(f'Poly feed error: {e}')
        return None


def _get_current_hour_utc() -> int:
    return datetime.now(timezone.utc).hour


def _save_signal(signal: ArbitrageSignal):
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO kalshi_arbitrage (strategy, poly_slug, poly_token, poly_price,
                kalshi_ticker, kalshi_side, kalshi_price, total_cost,
                profit_per_unit, profit_pct, position_size)
            VALUES (:s, :slug, :ptok, :pp, :kt, :ks, :kp, :tc, :pu, :pct, :ps)
        """), {
            's': signal.strategy, 'slug': signal.poly_event_slug,
            'ptok': signal.poly_token, 'pp': signal.poly_price,
            'kt': signal.kalshi_market_ticker, 'ks': signal.kalshi_side,
            'kp': signal.kalshi_price, 'tc': signal.total_cost,
            'pu': signal.profit_per_unit, 'pct': signal.profit_pct,
            'ps': POSITION_SIZE,
        })
        conn.commit()


def run_cycle():
    """Un ciclo de detección de arbitraje."""
    global _last_signal_time, _daily_pnl

    hour = _get_current_hour_utc()

    # Obtener precios de ambas plataformas
    poly = _fetch_polymarket_btc_prices()
    kalshi = feed.get_prices_for_arbitrage(hour)

    if poly is None or kalshi is None:
        return

    signal = strategy.evaluate(poly, kalshi)
    if signal is None or not signal.is_arbitrage:
        return

    # Evitar spam: solo notificar 1 vez cada 5 minutos
    now = time.time()
    if now - _last_signal_time < 300:
        return

    _last_signal_time = now
    _save_signal(signal)

    logger.info(
        f'ARBITRAGE [{signal.strategy}]: Poly_{signal.poly_token}=${signal.poly_price:.3f} '
        f'+ Kalshi_{signal.kalshi_side}=${signal.kalshi_price:.3f} '
        f'= cost ${signal.total_cost:.4f} | profit ${signal.profit_per_unit:.4f}/unit '
        f'({signal.profit_pct:.1f}%)'
    )

    send_telegram(
        f'💰 <b>ARBITRAJE SIN RIESGO</b>\n'
        f'Estrategia {signal.strategy}: Poly_{signal.poly_token} + Kalshi_{signal.kalshi_side}\n'
        f'Costo: <code>${signal.total_cost:.4f}</code> → Profit: <b>${signal.profit_per_unit:.4f}</b>/unidad\n'
        f'ROI: {signal.profit_pct:.1f}% garantizado'
    )


def main():
    _ensure_table()
    logger.info('Kalshi Arbitrage Agent starting...')
    send_telegram('🔁 <b>Kalshi Arbitrage Agent</b> iniciado\nBuscando arbitraje BTC 1H Polymarket ↔ Kalshi')

    while True:
        try:
            run_cycle()
        except Exception as e:
            logger.error(f'Arbitrage cycle error: {e}')
        time.sleep(CYCLE_SECONDS)


if __name__ == '__main__':
    main()
