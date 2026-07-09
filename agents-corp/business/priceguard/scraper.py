"""
PriceGuard Scraper — MercadoLibre Argentina.
Scrapes real product pages, detects price changes, stores history.
"""
import json, time, os, sys, urllib.request
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, '/opt/trading/agents-corp')
sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml',
    'Accept-Language': 'es-AR,es;q=0.9',
}

# Use MercadoLibre's public API (more reliable than scraping HTML)
ML_API = "https://api.mercadolibre.com"

def scrape_product(item_id: str) -> dict:
    """Scrape MercadoLibre product by ID using their public API."""
    try:
        req = urllib.request.Request(f"{ML_API}/items/{item_id}", headers={'User-Agent': HEADERS['User-Agent']})
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        return {
            "id": data.get("id"),
            "title": data.get("title", "")[:200],
            "price": data.get("price", 0),
            "currency": data.get("currency_id", "ARS"),
            "available_quantity": data.get("available_quantity", 0),
            "condition": data.get("condition", ""),
            "permalink": data.get("permalink", ""),
            "sold_quantity": data.get("sold_quantity", 0),
            "seller": data.get("seller", {}).get("nickname", ""),
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {"error": str(e)[:150], "id": item_id, "scraped_at": datetime.now(timezone.utc).isoformat()}


def search_products(query: str, limit: int = 10, country: str = "MLA") -> list:
    """Search products on MercadoLibre. MLA=Argentina, MLB=Brazil, MLM=Mexico, MCO=Colombia."""
    try:
        url = f"{ML_API}/sites/{country}/search?q={urllib.request.quote(query)}&limit={limit}"
        req = urllib.request.Request(url, headers={'User-Agent': HEADERS['User-Agent']})
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        results = []
        for item in data.get("results", []):
            results.append({
                "id": item.get("id"),
                "title": item.get("title", "")[:200],
                "price": item.get("price", 0),
                "currency": item.get("currency_id", "ARS"),
                "thumbnail": item.get("thumbnail", ""),
                "permalink": item.get("permalink", ""),
                "condition": item.get("condition", ""),
                "sold_quantity": item.get("sold_quantity", 0),
            })
        return results
    except Exception as e:
        return [{"error": str(e)[:150]}]


def save_to_db(product_data: dict):
    """Save scraped product to DB and check for price changes."""
    import psycopg2
    DB = {
        'host': os.getenv('POSTGRES_HOST'), 'port': int(os.getenv('POSTGRES_PORT', '5432')),
        'user': os.getenv('POSTGRES_USER'), 'password': os.getenv('POSTGRES_PASSWORD'),
        'dbname': os.getenv('POSTGRES_DB'), 'connect_timeout': 5,
    }
    if 'error' in product_data:
        return None

    conn = psycopg2.connect(**DB)
    cur = conn.cursor()

    # Check existing product
    cur.execute("SELECT id, current_price, previous_price FROM priceguard_products WHERE url=%s", (product_data['permalink'],))
    existing = cur.fetchone()

    if existing:
        prod_id, old_price, prev_price = existing
        new_price = product_data['price']

        if old_price != new_price:
            change_pct = ((new_price - old_price) / old_price * 100) if old_price > 0 else 0

            cur.execute("UPDATE priceguard_products SET previous_price=current_price, current_price=%s, last_checked=NOW() WHERE id=%s", (new_price, prod_id))

            # Create alert if significant change
            if abs(change_pct) >= 15:
                cur.execute("INSERT INTO priceguard_alerts (product_id, price_old, price_new, change_pct, alert_type) VALUES (%s,%s,%s,%s,%s)",
                           (prod_id, old_price, new_price, change_pct, 'price_drop' if change_pct < 0 else 'price_rise'))

            conn.commit()
            cur.close(); conn.close()
            return {"alert": True, "change_pct": change_pct, "old": old_price, "new": new_price} if abs(change_pct) >= 15 else {"alert": False}
    else:
        # New product
        cur.execute("INSERT INTO priceguard_products (name, url, region, current_price, last_checked) VALUES (%s,%s,%s,%s,NOW())",
                   (product_data['title'][:200], product_data['permalink'], 'AR', product_data['price']))
        conn.commit()

    cur.close(); conn.close()
    return {"alert": False, "new_product": True}


def run_monitoring_cycle():
    """Check all active products for price changes."""
    import psycopg2
    DB = {
        'host': os.getenv('POSTGRES_HOST'), 'port': int(os.getenv('POSTGRES_PORT', '5432')),
        'user': os.getenv('POSTGRES_USER'), 'password': os.getenv('POSTGRES_PASSWORD'),
        'dbname': os.getenv('POSTGRES_DB'), 'connect_timeout': 5,
    }
    conn = psycopg2.connect(**DB); cur = conn.cursor()
    cur.execute("SELECT id, url, current_price FROM priceguard_products WHERE active=true")
    products = cur.fetchall()
    cur.close(); conn.close()

    alerts = []
    for prod_id, url, old_price in products:
        # Extract item ID from permalink
        item_id = url.split('/')[-1] if '/' in url else url.split('-')[-1]
        if 'MLA-' in item_id:
            result = scrape_product(item_id)
            if 'error' not in result:
                if result['price'] != old_price:
                    change = ((result['price'] - old_price) / old_price * 100) if old_price > 0 else 0
                    if abs(change) >= 15:
                        alerts.append({"product": result['title'][:80], "old": old_price, "new": result['price'], "change": change})
                        save_to_db(result)

    return alerts


# ─── CLI ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "search":
        query = sys.argv[2] if len(sys.argv) > 2 else "notebook"
        results = search_products(query, 5)
        for r in results:
            print(f"  {r['title'][:80]} — ${r['price']} {r['currency']} ({r['permalink']})")
    elif len(sys.argv) > 1 and sys.argv[1] == "monitor":
        alerts = run_monitoring_cycle()
        print(f"Alerts: {len(alerts)}")
        for a in alerts: print(f"  {'🔻' if a['change']<0 else '🔺'} {a['product']}: ${a['old']} → ${a['new']} ({a['change']:.1f}%)")
    else:
        # Test with real product
        print("Testing MercadoLibre API...")
        results = search_products("celular samsung", 3, "MLA")
        for r in results:
            print(f"  {r['title'][:80]} — ${r['price']} {r['currency']}")
