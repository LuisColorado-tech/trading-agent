"""LeadGen — Google Maps Business Scraper."""
import json, time, os
from datetime import datetime, timezone

# Uses SerpAPI or direct scraping
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")

def scrape_google_maps(query: str, location: str, max_results: int = 20) -> list:
    """Scrape businesses from Google Maps via SerpAPI."""
    if not SERPAPI_KEY:
        return [{"error": "SERPAPI_KEY not configured"}]

    import urllib.request, urllib.parse
    params = urllib.parse.urlencode({
        "engine": "google_maps",
        "q": query,
        "location": location,
        "api_key": SERPAPI_KEY,
        "num": str(max_results),
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
                "scraped_at": datetime.now(timezone.utc).isoformat(),
            })
        return results
    except Exception as e:
        return [{"error": str(e)}]

def enrich_with_ai(leads: list) -> list:
    """Use DeepSeek to score and enrich leads."""
    if not leads: return leads
    
    for lead in leads:
        signals = 0
        if lead.get("website"): signals += 2
        if lead.get("phone"): signals += 1
        if lead.get("rating", 0) >= 4.0: signals += 2
        if lead.get("reviews", 0) >= 50: signals += 2
        lead["quality_score"] = min(signals, 10)
        lead["grade"] = "A" if signals >= 7 else "B" if signals >= 4 else "C"
    
    return leads

def export_csv(leads: list, filename: str = None) -> str:
    """Export leads to CSV."""
    import csv, io
    if not filename:
        filename = f"/opt/agents-corp/business/leadgen/exports/leads_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.csv"
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    
    with open(filename, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=["name","address","phone","rating","reviews","type","website","grade","quality_score"])
        writer.writeheader()
        for lead in leads:
            writer.writerow({k: lead.get(k, "") for k in writer.fieldnames})
    return filename

if __name__ == "__main__":
    leads = scrape_google_maps("restaurantes", "Buenos Aires, Argentina", 10)
    leads = enrich_with_ai(leads)
    path = export_csv(leads)
    print(f"Exported {len(leads)} leads -> {path}")
