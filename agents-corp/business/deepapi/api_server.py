"""DeepAPI v0.2 — AI API Gateway. OpenAI-compatible."""
import os, sys, json, hashlib, secrets, time
from datetime import datetime, timezone
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import HTMLResponse
import uvicorn

sys.path.insert(0, '/opt/trading/agents-corp')
sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')
from shared import validate_api_key, check_rate_limit, track_token_usage, get_db
from sqlalchemy import text

app = FastAPI(title="DeepAPI", version="0.2.0", docs_url="/docs")

@app.get("/")
def index():
    return HTMLResponse(content=DOCS_PAGE, status_code=200)

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    api_key = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not api_key: raise HTTPException(status_code=401, detail="Missing API key")
    user = validate_api_key(api_key)
    if not user: raise HTTPException(status_code=401, detail="Invalid API key")
    limits = {'free': 100, 'pro': 10000, 'business': 100000}
    max_req = limits.get(user.get('plan', 'free'), 100)
    if not check_rate_limit(user['id'], max_req):
        engine = get_db()
        with engine.connect() as conn:
            row = conn.execute(text("SELECT plan FROM api_users WHERE id=:id"), {'id': user['id']}).fetchone()
            plan = row[0] if row else 'free'
        upgrade = '. Upgrade: https://deepapi.ai/upgrade' if plan != 'business' else ''
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded ({max_req}/day).{upgrade}",
            headers={"X-Upgrade-URL": "https://deepapi.ai/upgrade"})

    body = await request.json()
    messages = body.get("messages", [])
    try:
        import urllib.request
        ds_key = os.getenv("DEEPSEEK_API_KEY", "")
        payload = json.dumps({"model":"deepseek-chat","messages":messages,"max_tokens":body.get("max_tokens",1024),"temperature":body.get("temperature",0.7)}).encode()
        req = urllib.request.Request("https://api.deepseek.com/v1/chat/completions",data=payload,headers={"Content-Type":"application/json","Authorization":f"Bearer {ds_key}"})
        resp = urllib.request.urlopen(req, timeout=60)
        result = json.loads(resp.read())
        tokens = result.get("usage",{}).get("total_tokens",0)
        track_token_usage(user['id'], tokens)
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Provider error: {str(e)[:100]}")

@app.post("/v1/auth/register")
async def register(request: Request):
    body = await request.json()
    email = body.get("email")
    plan = body.get("plan","free")
    ref = body.get("ref","")
    if not email: raise HTTPException(status_code=400, detail="Email required")
    api_key = "ak_"+secrets.token_hex(16)
    hashed = hashlib.sha256(api_key.encode()).hexdigest()
    limits = {'free':100,'pro':10000,'business':100000}
    ref_code = "REF"+secrets.token_hex(4).upper()
    engine = get_db()
    with engine.begin() as conn:
        if conn.execute(text("SELECT id FROM api_users WHERE email=:e"),{"e":email}).fetchone():
            raise HTTPException(status_code=409, detail="Email already registered")
        conn.execute(text("INSERT INTO api_users (id,email,api_key_hash,plan,tokens_limit,active,referral_code) VALUES (gen_random_uuid(),:e,:h,:p,:l,true,:r)"),{"e":email,"h":hashed,"p":plan,"l":limits.get(plan,100),"r":ref_code})
        if ref:
            conn.execute(text("UPDATE api_users SET referral_count=referral_count+1,months_free=CASE WHEN referral_count+1>=3 THEN 1 ELSE 0 END WHERE referral_code=:r"),{"r":ref})
    return {"api_key":api_key,"plan":plan,"referral_code":ref_code,"message":"Registration successful"}

@app.get("/v1/auth/stats")
async def stats(api_key: str = Query(...)):
    user = validate_api_key(api_key)
    if not user: raise HTTPException(status_code=401)
    engine = get_db()
    with engine.connect() as conn:
        row = conn.execute(text("SELECT tokens_used,plan,referral_count,months_free FROM api_users WHERE id=:i"),{'i':user['id']}).fetchone()
    return {"tokens_used":row[0],"plan":row[1],"referrals":row[2],"free_months":row[3]}

@app.get("/upgrade")
def upgrade_page():
    return HTMLResponse(content=UPGRADE_PAGE, status_code=200)

DOCS_PAGE = """<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DeepAPI Docs</title><style>body{background:#0d1117;color:#c9d1d9;font-family:-apple-system,sans-serif;max-width:800px;margin:0 auto;padding:40px 20px}h1{color:#58a6ff;font-size:2em;border-bottom:1px solid #30363d;padding-bottom:10px}h2{color:#58a6ff;margin-top:30px}code{background:#161b22;padding:2px 6px;border-radius:3px}pre{background:#161b22;padding:15px;border-radius:6px;overflow-x:auto;font-size:0.85em;border:1px solid #30363d}.endpoint{background:#0d419d20;border:1px solid #1f6feb;border-radius:6px;padding:10px;margin:10px 0}.method{color:#ff7b72;font-weight:bold}.plan{border:1px solid #30363d;border-radius:8px;padding:20px;margin:10px 0;flex:1}.plans{display:flex;gap:15px}.pro{border-color:#1f6feb}.business{border-color:#d29922}.price{font-size:2em;color:#58a6ff}.btn{display:inline-block;background:#238636;color:white;padding:10px 25px;border-radius:6px;text-decoration:none;margin-top:15px;font-weight:bold}</style></head><body><h1>🤖 DeepAPI — Documentación</h1><p>API de IA compatible con OpenAI. Sin tarjeta de crédito, sin pagar en dólares.</p><h2>🚀 Quick Start</h2><pre>curl -X POST http://localhost:9001/v1/auth/register -H "Content-Type: application/json" -d '{"email":"tu@email.com"}'</pre><p>Guarda tu <code>api_key</code>. La necesitarás para todas las llamadas.</p><h2>📡 Endpoints</h2><div class="endpoint"><span class="method">POST</span> <code>/v1/chat/completions</code><br>Compatible con OpenAI SDK.<pre>curl -X POST http://localhost:9001/v1/chat/completions -H "Authorization: Bearer TU_API_KEY" -H "Content-Type: application/json" -d '{"model":"deepseek-chat","messages":[{"role":"user","content":"Hola"}]}'</pre></div><div class="endpoint"><span class="method">POST</span> <code>/v1/auth/register</span><br>Registro por email. Sin tarjeta.<pre>curl -X POST http://localhost:9001/v1/auth/register -H "Content-Type: application/json" -d '{"email":"tu@email.com","plan":"free","ref":"CODIGO_REFERIDO"}'</pre><p>Opcional: <code>"ref"</code> — 3 referidos = 1 mes Pro gratis.</p></div><div class="endpoint"><span class="method">GET</span> <code>/v1/auth/stats?api_key=TU_KEY</code><br>Uso, plan, referidos.</div><h2>💎 Planes</h2><div class="plans"><div class="plan"><h3>Free</h3><div class="price">$0</div><ul><li>100 calls/día</li><li>Soporte email</li></ul><a class="btn" href="http://localhost:9001/v1/auth/register">Empezar</a></div><div class="plan pro"><h3>Pro</h3><div class="price">$49/mes</div><ul><li>10,000 calls/día</li><li>10 requests simultáneos</li><li>Factura electrónica</li></ul><a class="btn" href="/upgrade">Suscribir</a></div><div class="plan business"><h3>Business</h3><div class="price">$199/mes</div><ul><li>Ilimitado</li><li>Soporte 24/7</li><li>SLA 99.9%</li></ul><a class="btn" href="/upgrade">Contactar</a></div></div><p style="margin-top:40px;color:#8b949e;font-size:0.85em">DeepAPI — Agents Corp</p></body></html>"""

UPGRADE_PAGE = """<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"><title>Upgrade | DeepAPI</title><style>body{background:#0d1117;color:#c9d1d9;font-family:-apple-system,sans-serif;max-width:600px;margin:0 auto;padding:40px 20px;text-align:center}h1{color:#58a6ff}.btn{display:inline-block;background:#238636;color:white;padding:12px 30px;border-radius:6px;text-decoration:none;margin:10px;font-size:1.1em}</style></head><body><h1>⚡ Upgrade</h1><p>Pago con MercadoPago, cripto y transferencia próximamente.</p><p>Contáctanos en Telegram para activar tu plan manualmente.</p><a class="btn" href="https://t.me/Arthas_trading_bot">Contactar en Telegram</a></body></html>"""

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9001)
