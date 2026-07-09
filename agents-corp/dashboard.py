"""
Agents Corp — Health Dashboard
Shows status of all services on one page. Runs on port 9000.
"""
import os, sys, socket, subprocess, json
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn

sys.path.insert(0, '/opt/trading/agents-corp')
sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')

app = FastAPI(title="Agents Corp Dashboard")

SERVICES = [
    {"name": "DeepAPI", "port": 9001, "url": "http://localhost:9001/health", "emoji": "🤖"},
    {"name": "PriceGuard", "port": 9002, "url": "http://localhost:9002/health", "emoji": "📊"},
    {"name": "LeadGen", "port": 9003, "url": "http://localhost:9003/health", "emoji": "🎯"},
    {"name": "Blanca", "svc": "blanca", "emoji": "🤍"},
    {"name": "Funding", "svc": "funding-agent", "emoji": "💹"},
    {"name": "Marketing", "svc": "marketing", "emoji": "📣"},
    {"name": "CEO DeepAPI", "svc": "ceo-deepapi", "emoji": "🔍"},
    {"name": "CEO PriceGuard", "svc": "ceo-priceguard", "emoji": "🔍"},
    {"name": "CEO ViralBot", "svc": "ceo-viralbot", "emoji": "🔍"},
    {"name": "CEO LeadGen", "svc": "ceo-leadgen", "emoji": "🔍"},
]

def check_port(port):
    try: s=socket.socket(); s.settimeout(2); s.connect(('localhost',port)); s.close(); return True
    except: return False

def check_service(name):
    r = subprocess.run(['systemctl','is-active',name], capture_output=True, text=True)
    return r.stdout.strip() == 'active'

def check_health(url):
    try:
        import urllib.request
        resp = urllib.request.urlopen(url, timeout=3)
        return resp.status == 200
    except: return False

@app.get("/")
def dashboard():
    rows = ""
    for s in SERVICES:
        if 'port' in s:
            ok = check_port(s['port'])
        elif 'svc' in s:
            ok = check_service(s['svc'])
        else:
            ok = False
        tag = '🟢' if ok else '🔴'
        rows += f"<tr><td>{tag}</td><td>{s['emoji']}</td><td>{s['name']}</td><td>{'UP' if ok else 'DOWN'}</td></tr>"

    # Get DB stats
    import psycopg2
    DB = {'host':os.getenv('POSTGRES_HOST'),'port':int(os.getenv('POSTGRES_PORT','5432')),'user':os.getenv('POSTGRES_USER'),'password':os.getenv('POSTGRES_PASSWORD'),'dbname':os.getenv('POSTGRES_DB'),'connect_timeout':3}
    try:
        conn = psycopg2.connect(**DB); cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM api_users"); api_users = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM funding_sessions WHERE status='ACTIVE'"); funding = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM work_orders WHERE status='open'"); wo = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM ceo_reports WHERE created_at > NOW() - INTERVAL '24 hours'"); reports = cur.fetchone()[0]
        cur.close(); conn.close()
    except:
        api_users = funding = wo = reports = 0

    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><meta http-equiv="refresh" content="30"><title>Agents Corp</title>
<style>body{{background:#0d1117;color:#c9d1d9;font-family:-apple-system,sans-serif;max-width:800px;margin:0 auto;padding:20px}}
h1{{color:#58a6ff}}table{{width:100%;border-collapse:collapse}}th,td{{padding:10px;text-align:left;border-bottom:1px solid #30363d}}
.card{{border:1px solid #30363d;border-radius:8px;padding:15px;margin:10px 5px;display:inline-block;min-width:120px;text-align:center}}
.stat{{font-size:2em;color:#58a6ff}}.label{{color:#8b949e;font-size:0.85em}}.up{{color:#3fb950}}.down{{color:#f85149}}
</style></head><body><h1>🤍 Agents Corp Dashboard</h1><p>{datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>
<div><div class="card"><div class="stat">{api_users}</div><div class="label">API Users</div></div>
<div class="card"><div class="stat">{funding}</div><div class="label">Funding Active</div></div>
<div class="card"><div class="stat">{wo}</div><div class="label">Work Orders</div></div>
<div class="card"><div class="stat">{reports}</div><div class="label">CEO Reports 24h</div></div></div>
<table><tr><th></th><th></th><th>Service</th><th>Status</th></tr>{rows}</table>
<p style="color:#8b949e;font-size:0.8em;margin-top:30px">Agents Corp — {datetime.now(timezone.utc).strftime("%Y")}</p></body></html>"""
    return HTMLResponse(content=html)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9000)
