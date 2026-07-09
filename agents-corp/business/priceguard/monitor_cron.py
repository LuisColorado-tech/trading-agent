"""PriceGuard Monitor Cron — checks all products for price changes hourly."""
import os, sys
sys.path.insert(0, '/opt/trading/agents-corp')
sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')
from business.priceguard.scraper import run_monitoring_cycle, search_products, save_to_db
import json

# Run monitoring cycle
alerts = run_monitoring_cycle()
if alerts:
    print(f"Alerts: {len(alerts)}")
    for a in alerts:
        change = a.get('change', 0)
        emoji = '🔻' if change < 0 else '🔺'
        print(f"  {emoji} {a.get('product','?')[:60]}: ${a.get('old',0)} → ${a.get('new',0)} ({change:.1f}%)")
else:
    print("No price alerts")
