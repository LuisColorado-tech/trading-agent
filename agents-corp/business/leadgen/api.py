"""LeadGen — API for Fiverr automation & lead delivery."""
import os, sys, json, csv, io
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
import uvicorn

sys.path.insert(0, '/opt/agents-corp')
from shared import get_db
from sqlalchemy import text

app = FastAPI(title="LeadGen API", version="0.1.0")
engine = get_db()

@app.get("/health")
def health():
    return {"status": "ok", "leads_count": _count_leads()}

@app.get("/leads")
def get_leads(category: str = None, region: str = None, min_grade: str = "C", limit: int = 100):
    q = "SELECT * FROM leadgen_leads WHERE status='new'"
    params = {}
    if category:
        q += " AND category = :cat"; params['cat'] = category
    if region:
        q += " AND region = :reg"; params['reg'] = region
    grades = {'A': 7, 'B': 4, 'C': 0}
    q += " AND quality_score >= :min_score"
    params['min_score'] = grades.get(min_grade, 0)
    q += " ORDER BY quality_score DESC LIMIT :lim"
    params['lim'] = limit
    
    with engine.connect() as conn:
        rows = conn.execute(text(q), params).fetchall()
    return [dict(r._mapping) for r in rows]

@app.get("/leads/export")
def export_leads(category: str = None, region: str = None):
    leads = get_leads(category=category, region=region, limit=1000)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["name","address","phone","email","website","category","region","grade","quality_score"])
    writer.writeheader()
    for l in leads:
        writer.writerow({k: l.get(k, "") for k in writer.fieldnames})
    output.seek(0)
    return StreamingResponse(output, media_type="text/csv",
                            headers={"Content-Disposition": "attachment; filename=leads.csv"})

def _count_leads():
    with engine.connect() as conn:
        r = conn.execute(text("SELECT COUNT(*) FROM leadgen_leads")).fetchone()
        return r[0] if r else 0

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9003)
