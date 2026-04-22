"""
backfill_btc_direction.py — Re-settle EXP trades using Gamma events API.

Recorre todos los btc_direction_trades con outcome='EXP' y pnl_usdc=0,
consulta Polymarket para ver si realmente resolvieron, y actualiza el
outcome + pnl_usdc correcto en la DB.

Uso:
    python3 /opt/trading/scripts/backfill_btc_direction.py [--dry-run]
"""
import json
import os
import sys
import time

import requests
from sqlalchemy import create_engine, text

GAMMA = 'https://gamma-api.polymarket.com'
DRY_RUN = '--dry-run' in sys.argv

engine = create_engine(os.environ['DB_URL'])
session = requests.Session()
session.headers.update({'User-Agent': 'btc-direction-backfill/1.0'})


def get_outcome_from_slug(slug: str) -> str | None:
    """Devuelve 'Up', 'Down', o None si el mercado no ha resuelto."""
    try:
        resp = session.get(f'{GAMMA}/events', params={'slug': slug}, timeout=10)
        resp.raise_for_status()
        events = resp.json()
    except Exception as e:
        print(f'  ERROR API: {e}')
        return None

    if not events:
        return None

    markets = events[0].get('markets', [])
    if not markets:
        return None

    market = markets[0]
    uma_status = market.get('umaResolutionStatus', '')
    is_closed = market.get('closed', False)
    if uma_status != 'resolved' and not is_closed:
        return None

    prices_raw = market.get('outcomePrices', '[]')
    try:
        prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
        if len(prices) >= 2:
            if float(prices[0]) >= 0.99:
                return 'Up'
            if float(prices[1]) >= 0.99:
                return 'Down'
    except Exception:
        pass
    return None


def main():
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, market_slug, direction, shares, cost_usdc "
            "FROM btc_direction_trades "
            "WHERE outcome = 'EXP' AND pnl_usdc = 0 AND status = 'CLOSED' "
            "ORDER BY timestamp_close DESC"
        )).fetchall()

    print(f'Encontrados {len(rows)} trades EXP a re-verificar')
    print(f'Modo: {"DRY RUN" if DRY_RUN else "WRITE"}\n')

    updated = skipped = errors = 0

    for row in rows:
        trade_id   = row[0]
        slug       = row[1]
        direction  = row[2]
        shares     = float(row[3])
        cost       = float(row[4])

        outcome = get_outcome_from_slug(slug)

        if outcome is None:
            print(f'  [{slug}] → sin resolución aún, skip')
            skipped += 1
            time.sleep(0.1)
            continue

        won = direction == outcome
        if outcome == 'EXP':
            pnl = 0.0
        elif won:
            pnl = round(shares * 1.0 - cost, 4)
        else:
            pnl = round(-cost, 4)

        status = 'WIN' if won else 'LOSS'
        print(
            f'  [{slug}] dir={direction} → outcome={outcome} '
            f'pnl={pnl:+.2f} ({status})'
        )

        if not DRY_RUN:
            with engine.begin() as conn:
                conn.execute(text(
                    "UPDATE btc_direction_trades "
                    "SET outcome = :outcome, pnl_usdc = :pnl "
                    "WHERE id = :id"
                ), {'outcome': outcome, 'pnl': pnl, 'id': trade_id})

        updated += 1
        time.sleep(0.15)  # rate limiting

    print(f'\nResumen: {updated} actualizados, {skipped} sin datos, {errors} errores')
    if DRY_RUN:
        print('(modo dry-run: ningun cambio escrito en DB)')


if __name__ == '__main__':
    main()
