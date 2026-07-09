import sys
sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')

from sqlalchemy import create_engine, text
import os

pw = os.getenv('POSTGRES_PASSWORD', 'Tr4d1ng_Ag3nt_2026' + '!')
e = create_engine(f'postgresql://trading:{pw}@localhost:5432/trading_agent')

with e.connect() as c:
    n = c.execute(text('SELECT COUNT(*) FROM options_market_data')).scalar()
    print(f'=== options_market_data: {n} filas ===')

    sample = c.execute(text(
        'SELECT instrument_name, btc_price, strike, dte, iv_pct, delta, bid_btc, mark_btc '
        'FROM options_market_data ORDER BY timestamp DESC LIMIT 5'
    )).fetchall()
    for r in sample:
        m = dict(r._mapping)
        print(f"  {m['instrument_name']:30s} | BTC=${m['btc_price']:,.0f} | strike={m['strike']:,.0f} | DTE={m['dte']} | IV={m['iv_pct']:.1f}% | delta={m['delta']:.3f} | bid={m['bid_btc']:.5f}")

    print()
    pos = c.execute(text(
        'SELECT instrument_name, status, entry_premium_usd, margin_required_usd, expiration_date, delta_at_entry '
        'FROM options_positions ORDER BY opened_at DESC'
    )).fetchall()
    print(f'=== options_positions: {len(pos)} fila(s) ===')
    for r in pos:
        m = dict(r._mapping)
        print(f"  {m['instrument_name']} | status={m['status']} | premium=${m['entry_premium_usd']} | margin=${m['margin_required_usd']} | expires={m['expiration_date']} | delta={m['delta_at_entry']}")
