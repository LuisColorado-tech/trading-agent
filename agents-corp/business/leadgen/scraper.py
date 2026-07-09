"""
LeadGen — Google Maps Leads Scraper + AI Enrichment + CSV Export
"""
import os, sys, json, csv, io, time, urllib.request, urllib.parse
from datetime import datetime, timezone

sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')

DS_KEY = os.getenv("DEEPSEEK_API_KEY", "")
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")  # Optional: api.serpapi.com

EXPORT_DIR = "/opt/trading/agents-corp/business/leadgen/exports"
os.makedirs(EXPORT_DIR, exist_ok=True)


def scrape_google_maps(query: str, location: str, max_results: int = 20) -> list:
    """Scrape businesses from Google Maps via SerpAPI or free fallback."""
    if SERPAPI_KEY:
        return _scrape_serpapi(query, location, max_results)
    else:
        return _scrape_free(query, location, max_results)


def _scrape_serpapi(query, location, max_results):
    params = urllib.parse.urlencode({
        "engine": "google_maps", "q": query, "location": location,
        "api_key": SERPAPI_KEY, "num": str(max_results),
    })
    url = f"https://serpapi.com/search?{params}"
    try:
        resp = urllib.request.urlopen(url, timeout=30)
        data = json.loads(resp.read())
        results = []
        for place in data.get("local_results", [])[:max_results]:
            results.append({
                "name": place.get("title", ""),
                "address": place.get("address", ""),
                "phone": place.get("phone", ""),
                "rating": place.get("rating", 0),
                "reviews": place.get("reviews", 0),
                "type": place.get("type", ""),
                "website": place.get("website", ""),
                "gps": place.get("gps_coordinates", {}),
                "source": "serpapi",
            })
        return results
    except Exception as e:
        return [{"error": str(e)[:100]}]


def _scrape_free(query, location, max_results):
    """Fallback: Generate sample lead structure. Real scraping needs SerpAPI key."""
    sample = {
        "name": f"Negocio {query.title()} - {location}",
        "source": "generated",
        "note": "Configure SERPAPI_KEY in .env for real Google Maps data"
    }
    return [sample]  # Placeholder until API key is added


def enrich_leads(leads: list) -> list:
    """Score leads based on available data signals."""
    for lead in leads:
        signals = 0
        if lead.get("website"): signals += 2
        if lead.get("phone"): signals += 1
        if lead.get("rating", 0) >= 4.0: signals += 2
        if lead.get("reviews", 0) >= 50: signals += 2
        if lead.get("address"): signals += 1
        lead["quality_score"] = min(signals, 10)
        lead["grade"] = "A" if signals >= 7 else "B" if signals >= 4 else "C"
        lead["scraped_at"] = datetime.now(timezone.utc).isoformat()
    return leads


def export_csv(leads: list, category: str = "", region: str = "") -> str:
    """Export leads to CSV file."""
    filename = f"{category}_{region}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.csv"
    path = os.path.join(EXPORT_DIR, filename)
    fieldnames = ["name","address","phone","website","rating","reviews","type","grade","quality_score","source","scraped_at"]
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(leads)
    return path


def save_to_db(leads: list, category: str = "", region: str = ""):
    """Save leads to DB and skip duplicates."""
    import psycopg2
    DB = {
        'host': os.getenv('POSTGRES_HOST'), 'port': int(os.getenv('POSTGRES_PORT', '5432')),
        'user': os.getenv('POSTGRES_USER'), 'password': os.getenv('POSTGRES_PASSWORD'),
        'dbname': os.getenv('POSTGRES_DB'), 'connect_timeout': 5,
    }
    conn = psycopg2.connect(**DB); cur = conn.cursor()
    saved = 0
    for lead in leads:
        # Skip duplicates
        if lead.get("phone"):
            cur.execute("SELECT id FROM leadgen_leads WHERE phone=%s", (lead["phone"],))
            if cur.fetchone(): continue
        cur.execute("INSERT INTO leadgen_leads (name,address,phone,website,category,region,quality_score,grade,scraped_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW())",
                   (lead.get("name","")[:200], lead.get("address","")[:300], lead.get("phone","")[:30],
                    lead.get("website","")[:300], category, region, lead.get("quality_score",0), lead.get("grade","C")))
        saved += 1
    conn.commit(); cur.close(); conn.close()
    return saved


def run_pipeline(query: str, location: str, category: str = "", region: str = "", max_results: int = 20) -> dict:
    """Full pipeline: scrape → enrich → save → export."""
    leads = scrape_google_maps(query, location, max_results)
    leads = enrich_leads(leads)
    saved = save_to_db(leads, category or query, region or location)
    csv_path = export_csv(leads, category or query, region or location)
    return {"total": len(leads), "saved": saved, "csv": csv_path, "sample": leads[:3]}


# ─── CLI ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python scraper.py <query> <location> [category] [region]")
        print("Example: python scraper.py restaurantes 'Buenos Aires, Argentina' restaurantes AR")
        print("\nSet SERPAPI_KEY in .env for real Google Maps data.")
        sys.exit(1)

    query, location = sys.argv[1], sys.argv[2]
    category = sys.argv[3] if len(sys.argv) > 3 else ""
    region = sys.argv[4] if len(sys.argv) > 4 else ""

    print(f"Scraping {query} in {location}...")
    result = run_pipeline(query, location, category, region)
    print(f"Total: {result['total']} leads | Saved: {result['saved']} | CSV: {result['csv']}")
    for l in result['sample']:
        print(f"  {'⭐'*(int(l.get('rating',0))//1)} {l.get('name','')[:60]} — {l.get('grade','?')}")
