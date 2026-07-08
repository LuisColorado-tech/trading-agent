"""
Test de conectividad con exchanges via ccxt.
Ejecutar: cd /opt/trading && source venv/bin/activate && python3 scripts/test_exchange.py
"""
import os
import sys
import yaml

from dotenv import load_dotenv

load_dotenv('/opt/trading/config/.env')

# Cargar configuración de exchanges
with open('/opt/trading/config/exchange_config.yaml') as f:
    config = yaml.safe_load(f)

import ccxt

print(f'ccxt version: {ccxt.__version__}')
print()

results = {}

for exname, exconf in config['exchanges'].items():
    if not exconf.get('enabled', False):
        print(f'[SKIP] {exname}: disabled in config')
        results[exname] = 'SKIPPED'
        continue

    ccxt_id = exconf['ccxt_id']
    print(f'=== {exname} ({ccxt_id}) — role: {exconf["role"]} ===')

    try:
        exchange_cls = getattr(ccxt, ccxt_id)
        exchange = exchange_cls({'enableRateLimit': True, 'timeout': 15000})
        exchange.load_markets()

        for asset_key, asset_conf in exconf['assets'].items():
            pair = asset_conf['pair']
            if pair in exchange.markets:
                ticker = exchange.fetch_ticker(pair)
                print(f'  {asset_key:5s} {pair:20s} last={ticker["last"]}  vol={ticker.get("baseVolume", "?")}')
            else:
                # Intentar par alternativo
                alt = asset_conf.get('alt_pair')
                if alt and alt in exchange.markets:
                    ticker = exchange.fetch_ticker(alt)
                    print(f'  {asset_key:5s} {alt:20s} last={ticker["last"]}  vol={ticker.get("baseVolume", "?")}  (alt)')
                else:
                    print(f'  {asset_key:5s} {pair:20s} NOT LISTED')

        results[exname] = 'OK'
        print(f'  -> {exname}: OK')

    except Exception as e:
        print(f'  -> {exname}: ERROR — {e}')
        results[exname] = f'ERROR: {e}'

    print()

# Resumen
print('=== SUMMARY ===')
all_ok = True
for exname, status in results.items():
    icon = 'OK' if status == 'OK' else ('SKIP' if status == 'SKIPPED' else 'FAIL')
    print(f'  {exname:15s} {icon}')
    if icon == 'FAIL':
        all_ok = False

if all_ok:
    print('\nExchange connectivity: OK')
else:
    print('\nExchange connectivity: PARTIAL — check errors above')
    sys.exit(1)
