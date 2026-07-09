"""Agents Corp Dashboard — Port 9000"""
import os, sys, socket, subprocess, json
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn

sys.path.insert(0,'/opt/trading/agents-corp'); sys.path.insert(0,'/opt/trading')
from dotenv import load_dotenv; load_dotenv('/opt/trading/config/.env')

app = FastAPI()

BUSINESSES = [
    {"name":"DeepAPI","desc":"AI API — GPT-4o quality, 62× cheaper","url":"/deepapi/","port":9001,"emoji":"🤖","color":"#1f6feb"},
    {"name":"PriceGuard","desc":"Price monitoring for resellers","url":"/priceguard/","port":9002,"emoji":"📊","color":"#3fb950"},
    {"name":"LeadGen","desc":"B2B leads with AI enrichment","url":"/leadgen/","port":9003,"emoji":"🎯","color":"#d29922"},
    {"name":"ViralBot","desc":"AI content for social media","emoji":"📱","color":"#f85149"},
    {"name":"Funding Agent","desc":"Crypto funding rate arbitrage","emoji":"💹","color":"#3fb950"},
]
SERVICES = ["blanca","funding-agent","marketing","ceo-deepapi","ceo-priceguard","ceo-viralbot","ceo-leadgen"]

def ck_port(p):
    try: s=socket.socket();s.settimeout(2);s.connect(('localhost',p));s.close();return True
    except:return False
def ck_svc(n):
    r=subprocess.run(['systemctl','is-active',n],capture_output=True,text=True)
    return r.stdout.strip()=='active'

@app.get("/")
def index():
    now=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    try:
        import psycopg2; DB={'host':os.getenv('POSTGRES_HOST'),'port':int(os.getenv('POSTGRES_PORT','5432')),'user':os.getenv('POSTGRES_USER'),'password':os.getenv('POSTGRES_PASSWORD'),'dbname':os.getenv('POSTGRES_DB'),'connect_timeout':3}
        conn=psycopg2.connect(**DB);cur=conn.cursor()
        cur.execute("SELECT COUNT(*) FROM api_users");api_users=cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM funding_sessions WHERE status='ACTIVE'");funding=cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM work_orders WHERE status='open'");wo=cur.fetchone()[0]
        cur.close();conn.close()
    except: api_users=funding=wo=0

    biz_cards=''
    for b in BUSINESSES:
        port_ok=ck_port(b.get('port',0)) if b.get('port') else True
        tag='🟢 LIVE' if port_ok else '🔴 DOWN'
        url=b.get('url','#')
        biz_cards+=f'''<div class="biz" onclick="location.href='{url}'" style="cursor:pointer">
<div class="biz-emoji">{b['emoji']}</div><h3>{b['name']}</h3><p>{b['desc']}</p>
<span class="tag" style="background:{b['color']}20;color:{b['color']}">{tag}</span></div>'''

    svc_rows=''
    for s in SERVICES:
        ok=ck_svc(s);svc_rows+=f'<tr><td>{"🟢" if ok else "🔴"}</td><td>{s}</td><td>{"UP" if ok else "DOWN"}</td></tr>'

    html=f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="60"><title>Agents Corp</title>
<style>*{{margin:0;padding:0;box-sizing:border-box}}body{{background:linear-gradient(135deg,#0d1117 0%,#161b22 100%);color:#c9d1d9;font-family:-apple-system,sans-serif;min-height:100vh}}
.nav{{display:flex;align-items:center;padding:16px 24px;border-bottom:1px solid #30363d;background:#0d1117f0;position:sticky;top:0;z-index:10}}
.nav .logo{{font-size:1.3em;font-weight:700;color:#58a6ff;margin-right:auto}}
.nav a{{color:#8b949e;text-decoration:none;margin-left:20px;font-size:.9em}}.nav a:hover{{color:#58a6ff}}
.hero{{text-align:center;padding:50px 20px 30px}}.hero h1{{font-size:2.5em;font-weight:800;background:linear-gradient(135deg,#58a6ff,#3fb950);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.hero p{{color:#8b949e;margin-top:10px;font-size:1.1em}}
.container{{max-width:1100px;margin:0 auto;padding:0 20px}}
h2{{font-size:1.5em;color:#f0f6fc;margin:30px 0 20px}}
.biz-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin:20px 0}}
.biz{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:24px;transition:all .3s}}
.biz:hover{{transform:translateY(-2px);box-shadow:0 4px 20px #00000040;border-color:#58a6ff40}}
.biz-emoji{{font-size:2em;margin-bottom:10px}}.biz h3{{color:#f0f6fc;margin-bottom:6px;font-size:1.1em}}.biz p{{color:#8b949e;font-size:.85em;line-height:1.4;margin-bottom:12px}}
.tag{{display:inline-block;padding:3px 10px;border-radius:12px;font-size:.75em;font-weight:600}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:12px;margin:20px 0}}
.stat{{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:16px;text-align:center}}
.stat .num{{font-size:2em;font-weight:800;color:#58a6ff}}.stat .lbl{{color:#8b949e;font-size:.8em;margin-top:4px}}
table{{width:100%;border-collapse:collapse}}th,td{{padding:10px;text-align:left;border-bottom:1px solid #30363d}}th{{color:#58a6ff}}
.footer{{text-align:center;padding:30px;color:#8b949e;font-size:.8em;border-top:1px solid #30363d;margin-top:40px}}
@media(max-width:640px){{.hero h1{{font-size:1.8em}}.biz-grid{{grid-template-columns:1fr}}}}
</style></head><body>
<nav class="nav"><a class="logo" href="/">🤍 Agents Corp</a><a href="/deepapi/">DeepAPI</a><a href="/priceguard/">PriceGuard</a><a href="/leadgen/">LeadGen</a><a href="https://github.com/LuisColorado-tech/trading-agent" target="_blank">GitHub</a></nav>
<div class="hero"><h1>Agents Corp</h1><p>AI-powered businesses running 24/7 on a VPS</p></div>
<div class="container">
<div class="stats"><div class="stat"><div class="num">{api_users}</div><div class="lbl">API Users</div></div><div class="stat"><div class="num">{funding}</div><div class="lbl">Funding Active</div></div><div class="stat"><div class="num">{wo}</div><div class="lbl">Open Tasks</div></div></div>
<h2>🏢 Business Units</h2><div class="biz-grid">{biz_cards}</div>
<h2>🔧 Services ({sum(1 for s in SERVICES if ck_svc(s))}/{len(SERVICES)} UP)</h2>
<table><tr><th></th><th>Service</th><th>Status</th></tr>{svc_rows}</table></div>
<footer class="footer">Agents Corp · {now} · Built with Python on Ubuntu VPS</footer></body></html>"""
    return HTMLResponse(content=html)

if __name__=="__main__":uvicorn.run(app,host="0.0.0.0",port=9000)
