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

@app.get("/dashboard")
def dashboard(api_key: str = Query(...)):
    """Admin dashboard — shows all users and usage."""
    user = validate_api_key(api_key)
    if not user or user.get('plan') != 'admin':
        raise HTTPException(status_code=403)

    engine = get_db()
    with engine.connect() as conn:
        users = conn.execute(text("SELECT email, plan, tokens_used, tokens_limit, referral_count, created_at FROM api_users ORDER BY created_at DESC LIMIT 50")).fetchall()
        total_users = conn.execute(text("SELECT COUNT(*) FROM api_users")).scalar()
        total_tokens = conn.execute(text("SELECT COALESCE(SUM(tokens_used),0) FROM api_users")).scalar()

    rows = ""
    for u in users:
        rows += f"<tr><td>{u[0]}</td><td><b>{u[1]}</b></td><td>{u[2]}/{u[3]}</td><td>{u[4]}</td><td>{str(u[5])[:10]}</td></tr>"

    html = f"""<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"><title>DeepAPI Dashboard</title>
<style>body{{background:#0d1117;color:#c9d1d9;font-family:-apple-system,sans-serif;max-width:1000px;margin:0 auto;padding:20px}}
h1{{color:#58a6ff}}table{{width:100%;border-collapse:collapse;margin:20px 0}}
th,td{{padding:8px 12px;text-align:left;border-bottom:1px solid #30363d}}
th{{color:#58a6ff}}.stat{{font-size:2em;color:#58a6ff}}.card{{border:1px solid #30363d;border-radius:8px;padding:20px;margin:10px;display:inline-block;min-width:150px}}</style></head><body>
<h1>📊 DeepAPI Dashboard</h1>
<div><div class="card"><div class="stat">{total_users}</div>Usuarios</div>
<div class="card"><div class="stat">{total_tokens/1000:.0f}K</div>Tokens usados</div></div>
<table><tr><th>Email</th><th>Plan</th><th>Tokens</th><th>Refs</th><th>Desde</th></tr>{rows}</table></body></html>"""
    return HTMLResponse(content=html, status_code=200)
    return HTMLResponse(content=UPGRADE_PAGE, status_code=200)

DOCS_PAGE = """<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DeepAPI — IA sin barreras</title>
<style>body{background:#0d1117;color:#c9d1d9;font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:900px;margin:0 auto;padding:20px}
h1{color:#58a6ff;font-size:2em}h2{color:#58a6ff;margin-top:30px;border-bottom:1px solid #30363d;padding-bottom:8px}
h3{color:#f0f6fc;margin:10px 0}code{background:#161b22;padding:2px 6px;border-radius:3px;font-size:0.9em}
pre{background:#161b22;padding:15px;border-radius:6px;overflow-x:auto;font-size:0.85em;border:1px solid #30363d}
.endpoint{background:#0d419d20;border:1px solid #1f6feb;border-radius:6px;padding:10px;margin:10px 0}
.method{color:#ff7b72;font-weight:bold}.tag{display:inline-block;background:#1f6feb20;color:#58a6ff;padding:2px 8px;border-radius:4px;font-size:0.8em;margin:2px}
.plans{display:flex;gap:15px;flex-wrap:wrap}.plan{flex:1;min-width:180px;border:1px solid #30363d;border-radius:10px;padding:20px;text-align:center;background:#161b22}
.plan h3{margin:0 0 10px 0;font-size:1.3em}.plan .price{font-size:2.5em;color:#58a6ff;margin:10px 0;font-weight:bold}
.plan .tokens{color:#3fb950;font-size:0.9em;margin:5px 0}.plan ul{text-align:left;padding:0 15px;color:#c9d1d9;font-size:0.9em;list-style:none}
.plan ul li{padding:4px 0}.plan ul li:before{content:'✓ ';color:#3fb950}
.plan.featured{border-color:#1f6feb;border-width:2px;position:relative}.plan.featured:before{content:'MÁS POPULAR';position:absolute;top:-12px;left:50%;transform:translateX(-50%);background:#1f6feb;color:white;padding:3px 12px;border-radius:10px;font-size:0.75em;font-weight:bold}
.btn{display:inline-block;background:#238636;color:white;padding:10px 25px;border-radius:6px;text-decoration:none;font-weight:bold;margin:5px}
.btn-outline{background:transparent;border:1px solid #58a6ff;color:#58a6ff}
.compare{font-size:0.85em;color:#8b949e;margin-top:20px;text-align:center}
.compare table{width:100%;margin:15px 0}.compare td{padding:6px 12px;border-bottom:1px solid #30363d}
.compare .win{color:#3fb950}.compare .us{color:#58a6ff;font-weight:bold}
</style></head><body>
<h1>🤖 DeepAPI</h1>
<p style="font-size:1.2em;color:#8b949e">IA de clase mundial, sin barreras. Mismo formato que OpenAI, sin tarjeta de crédito.</p>

<h2>💎 Planes</h2>
<div class="plans">
<div class="plan"><h3>Gratis</h3><div class="price">$0</div><div class="tokens">5M tokens/mes</div><ul><li>~333 llamadas/día</li><li>API OpenAI compatible</li><li>SDK open-source</li><li>Docs en español</li></ul><a class="btn" href="http://localhost:9001/v1/auth/register">Comenzar</a></div>
<div class="plan featured"><h3>Starter</h3><div class="price">$8</div><div class="tokens">50M tokens/mes</div><ul><li>~3,300 llamadas/día</li><li>Sin rate limiting</li><li>Historial 30 días</li><li>Soporte por email</li></ul><a class="btn" href="http://localhost:9001/v1/auth/register">Comenzar gratis</a></div>
<div class="plan"><h3>Pro</h3><div class="price">$25</div><div class="tokens">150M tokens/mes</div><ul><li>~10,000 llamadas/día</li><li>Acceso prioritario</li><li>Historial 90 días</li><li>Soporte WhatsApp</li></ul><a class="btn" href="http://localhost:9001/v1/auth/register">Comenzar gratis</a></div>
<div class="plan"><h3>Business</h3><div class="price">$69</div><div class="tokens">350M tokens/mes</div><ul><li>~23K llamadas/día</li><li>Soporte Slack</li><li>Hasta 5 miembros</li><li>SLA 99.9%</li></ul><a class="btn" href="http://localhost:9001/v1/auth/register">Comenzar gratis</a></div></div>
<p style="color:#8b949e;font-size:0.8em;margin-top:10px">*Estimado a 500 tokens/llamada. Overages: $2/1M tokens extra. Próximamente: PagoPlax, PSE, Pix, OXXO.</p>

<h2>⚡ ¿Por qué DeepAPI?</h2>
<div class="compare"><table>
<tr><td class="win">✓ Sin tarjeta de crédito</td><td>vs OpenAI/Anthropic que exigen CC internacional</td></tr>
<tr><td class="win">✓ Calidad GPT-4o</td><td>Usamos DeepSeek V3/R1, comparable a GPT-4o</td></tr>
<tr><td class="win">✓ 100% OpenAI compatible</td><td>Cambia la URL y tu código funciona</td></tr>
<tr><td class="win">✓ Soporte en español</td><td>Docs, errores y ayuda en tu idioma</td></tr>
<tr><td class="win">✓ Sin KYC ni pasaporte</td><td>Solo necesitas un email</td></tr></table></div>

<h2>🚀 Quick Start</h2>
<pre>curl -X POST http://localhost:9001/v1/auth/register -H "Content-Type: application/json" -d '{"email":"tu@email.com"}'</pre>
<p>Guarda tu <code>api_key</code>. Listo.</p>

<div class="endpoint"><span class="method">POST</span> <code>/v1/chat/completions</code> <span class="tag">OpenAI SDK</span><br>
<pre>curl -X POST http://localhost:9001/v1/chat/completions -H "Authorization: Bearer TU_KEY" -H "Content-Type: application/json" -d '{"model":"deepseek-chat","messages":[{"role":"user","content":"Hola"}]}'</pre></div>

<div class="endpoint"><span class="method">GET</span> <code>/v1/auth/stats?api_key=TU_KEY</code> — Tu uso, plan y referidos.</div>

<h2>👥 Referidos</h2>
<p>Comparte tu código de referido. <b>3 amigos que se registren = 1 mes gratis</b> en tu plan actual.</p>
<pre>curl -X POST http://localhost:9001/v1/auth/register -H "Content-Type: application/json" -d '{"email":"amigo@email.com","ref":"TU_CODIGO"}'</pre>

<p style="margin-top:40px;color:#8b949e;font-size:0.85em;text-align:center">DeepAPI — <a href="https://github.com/LuisColorado-tech/trading-agent" style="color:#58a6ff">Agents Corp</a> | Construido en Latinoamérica</p>
</body></html>"""

UPGRADE_PAGE = """<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"><title>Upgrade | DeepAPI</title><style>body{background:#0d1117;color:#c9d1d9;font-family:-apple-system,sans-serif;max-width:600px;margin:0 auto;padding:40px 20px;text-align:center}h1{color:#58a6ff}.btn{display:inline-block;background:#238636;color:white;padding:12px 30px;border-radius:6px;text-decoration:none;margin:10px;font-size:1.1em}</style></head><body><h1>⚡ Upgrade</h1><p>Pago con MercadoPago, cripto y transferencia próximamente.</p><p>Contáctanos en Telegram para activar tu plan manualmente.</p><a class="btn" href="https://t.me/Arthas_trading_bot">Contactar en Telegram</a></body></html>"""

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9001)
