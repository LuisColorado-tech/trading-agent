"""LeadGen — Lead Generation API"""
import os,sys,json,csv,io
from datetime import datetime,timezone
from fastapi import FastAPI,HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse,StreamingResponse
import uvicorn

sys.path.insert(0,'/opt/trading/agents-corp');sys.path.insert(0,'/opt/trading')
from dotenv import load_dotenv;load_dotenv('/opt/trading/config/.env')
from shared import get_db;from sqlalchemy import text

app=FastAPI(title="LeadGen")
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["*"],allow_headers=["*"])
engine=get_db()

@app.get("/")
def index():
    return HTMLResponse(content=LANDING,status_code=200)

@app.get("/health")
def health():
    with engine.connect() as conn:cnt=conn.execute(text("SELECT COUNT(*) FROM leadgen_leads")).fetchone()[0]
    return{"status":"ok","leads_count":cnt}

@app.get("/leads")
def get_leads(category:str=None,region:str=None,min_grade:str="C",limit:int=100):
    q="SELECT * FROM leadgen_leads WHERE status='new'";params={}
    if category:q+=" AND category=:c";params["c"]=category
    if region:q+=" AND region=:r";params["r"]=region
    grades={'A':7,'B':4,'C':0};q+=" AND quality_score>=:ms";params["ms"]=grades.get(min_grade,0)
    q+=" ORDER BY quality_score DESC LIMIT :l";params["l"]=limit
    with engine.connect() as conn:rows=conn.execute(text(q),params).fetchall()
    return[dict(r._mapping)for r in rows]

@app.get("/leads/export")
def export_leads(category:str=None,region:str=None):
    leads=get_leads(category=category,region=region,limit=1000)
    out=io.StringIO();w=csv.DictWriter(out,fieldnames=["name","address","phone","website","category","region","grade","quality_score"])
    w.writeheader()
    for l in leads:w.writerow({k:l.get(k,"")for k in w.fieldnames})
    out.seek(0)
    return StreamingResponse(out,media_type="text/csv",headers={"Content-Disposition":"attachment; filename=leads.csv"})

LANDING="""<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LeadGen</title>
<style>body{background:linear-gradient(135deg,#0d1117,#161b22);color:#c9d1d9;font-family:-apple-system,sans-serif;max-width:600px;margin:0 auto;padding:40px 20px;text-align:center}
h1{font-size:2.5em;background:linear-gradient(135deg,#58a6ff,#d29922);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.card{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:25px;margin:20px 0;text-align:left}
.btn{display:inline-block;background:#238636;color:white;padding:12px 25px;border-radius:6px;text-decoration:none;font-weight:600}
</style></head><body>
<h1>🎯 LeadGen</h1><p style="font-size:1.2em;color:#8b949e">Generacion de leads B2B automatizada con inteligencia artificial.</p>
<div class="card"><h3>🚀 Features</h3><ul><li>Google Maps scraper</li><li>AI enrichment + scoring A/B/C</li><li>Export CSV listo para CRM</li><li>Ideal para Fiverr y Workana</li></ul></div>
<p style="color:#8b949e">API disponible. Contactanos en Telegram.</p>
<a href="/" style="color:#58a6ff">← Agents Corp</a></body></html>"""

if __name__=="__main__":uvicorn.run(app,host="127.0.0.1",port=9003)
