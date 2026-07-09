"""PriceGuard — Price Monitoring API."""
import os, sys, json
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

sys.path.insert(0, '/opt/trading/agents-corp')
sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')
from shared import get_db
from sqlalchemy import text

app = FastAPI(title="PriceGuard", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

engine = get_db()

class ProductAdd(BaseModel):
    url: str
    name: str
    region: str = "AR"
    target_price: float = None

@app.get("/health")
def health():
    return {"status": "ok", "service": "priceguard"}

@app.post("/products")
def add_product(p: ProductAdd):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO priceguard_products (url, name, region, target_price)
            VALUES (:url, :name, :region, :target)
        """), {"url": p.url, "name": p.name, "region": p.region, "target": p.target_price})
    return {"status": "added", "name": p.name}

@app.get("/products")
def list_products(region: str = None):
    with engine.connect() as conn:
        q = "SELECT id, name, url, region, current_price, target_price, last_checked FROM priceguard_products WHERE active=true"
        params = {}
        if region:
            q += " AND region = :region"
            params['region'] = region
        rows = conn.execute(text(q), params).fetchall()
    return [dict(r._mapping) for r in rows]

@app.get("/alerts")
def get_alerts(hours: int = 24):
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT * FROM priceguard_alerts WHERE created_at > NOW() - (:h || ' hours')::interval ORDER BY created_at DESC LIMIT 50"
        ), {"h": str(hours)}).fetchall()
    return [dict(r._mapping) for r in rows]

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9002)
