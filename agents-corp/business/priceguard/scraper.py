"""PriceGuard — MercadoLibre Price Scraper."""
import requests, json, time
from datetime import datetime, timezone
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0"}

def scrape_ml_product(url: str) -> dict:
    """Scrape price and name from MercadoLibre product page."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Try JSON-LD first
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                if isinstance(data, list): data = data[0]
                return {
                    "name": data.get("name", "Unknown"),
                    "price": float(data.get("offers", {}).get("price", 0)),
                    "currency": data.get("offers", {}).get("priceCurrency", "ARS"),
                }
            except: pass

        # Fallback: parse HTML
        name = soup.find('h1')
        price = soup.find('meta', itemprop='price') or soup.find('span', class_='andes-money-amount__fraction')
        return {
            "name": name.text.strip() if name else "Unknown",
            "price": float(price.get('content', 0)) if price else 0,
            "currency": "ARS",
        }
    except Exception as e:
        return {"error": str(e), "price": None}

if __name__ == "__main__":
    r = scrape_ml_product("https://articulo.mercadolibre.com.ar/MLA-0000000000")
    print(json.dumps(r, indent=2))
