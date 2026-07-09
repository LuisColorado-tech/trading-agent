"""PriceGuard — Price Monitoring API"""
import os,sys,json
from datetime import datetime,timezone
from fastapi import FastAPI,HTTPException,Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

sys.path.insert(0,'/opt/trading/agents-corp');sys.path.insert(0,'/opt/trading')
from dotenv import load_dotenv;load_dotenv('/opt/trading/config/.env')
from shared import get_db;from sqlalchemy import text

app=FastAPI(title="PriceGuard")
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["*"],allow_headers=["*"])
engine=get_db()

class ProductAdd(BaseModel):
    url:str;name:str;region:str="AR";target_price:float=None

@app.get("/")
def index():
    return HTMLResponse(content=LANDING,status_code=200)

@app.get("/health")
def health():return{"status":"ok","service":"priceguard"}

@app.post("/products")
def add_product(p:ProductAdd):
    with engine.begin() as conn:conn.execute(text("INSERT INTO priceguard_products(url,name,region,target_price)VALUES(:u,:n,:r,:t)"),{"u":p.url,"n":p.name,"r":p.region,"t":p.target_price})
    return{"status":"added","name":p.name}

@app.get("/products")
def list_products(region:str=None):
    with engine.connect() as conn:
        q="SELECT id,name,url,region,current_price,target_price,last_checked FROM priceguard_products WHERE active=true"
        params={}
        if region:q+=" AND region=:r";params["r"]=region
        rows=conn.execute(text(q),params).fetchall()
    return[dict(r._mapping)for r in rows]

@app.get("/alerts")
def get_alerts(hours:int=24):
    with engine.connect() as conn:rows=conn.execute(text("SELECT * FROM priceguard_alerts WHERE created_at>NOW()-:h::interval ORDER BY created_at DESC LIMIT 50"),{"h":str(hours)}).fetchall()
    return[dict(r._mapping)for r in rows]

LANDING="""<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PriceGuard</title>
<style>body{background:linear-gradient(135deg,#0d1117,#161b22);color:#c9d1d9;font-family:-apple-system,sans-serif;max-width:600px;margin:0 auto;padding:40px 20px;text-align:center}
h1{font-size:2.5em;background:linear-gradient(135deg,#58a6ff,#3fb950);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.card{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:25px;margin:20px 0;text-align:left}
.btn{display:inline-block;background:#238636;color:white;padding:12px 25px;border-radius:6px;text-decoration:none;font-weight:600}
</style></head><body>
<h1>📊 PriceGuard</h1><p style="font-size:1.2em;color:#8b949e">Monitoreo de precios multi-region para revendedores e importadores.</p>
<div class="card"><h3>🚀 Features</h3><ul><li>MercadoLibre, Amazon, AliExpress</li><li>Alertas automaticas por cambios &gt;15%</li><li>Historial de precios</li><li>Multi-region: 🇦🇷 🇧🇷 🇲🇽 🇨🇴</li></ul></div>
<p style="color:#8b949e">API lista para integrar. Monitoreo 24/7 activo.</p>
<a href="/" style="color:#58a6ff">← Agents Corp</a></body></html>"""

if __name__=="__main__":uvicorn.run(app,host="127.0.0.1",port=9002)
