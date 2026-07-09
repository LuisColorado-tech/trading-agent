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
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:linear-gradient(135deg,#0d1117 0%,#161b22 100%);color:#c9d1d9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;min-height:100vh}
.nav{display:flex;justify-content:space-between;align-items:center;padding:16px 24px;border-bottom:1px solid #30363d;background:#0d1117f0;backdrop-filter:blur(10px);position:sticky;top:0;z-index:10}
.nav .logo{font-size:1.4em;font-weight:700;color:#58a6ff;text-decoration:none}
.nav .links a{color:#8b949e;text-decoration:none;margin-left:20px;font-size:.9em;transition:color .2s}
.nav .links a:hover{color:#58a6ff}
.hero{text-align:center;padding:80px 20px 60px;max-width:700px;margin:0 auto}
.hero h1{font-size:3em;font-weight:800;background:linear-gradient(135deg,#58a6ff,#3fb950);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin-bottom:16px}
.hero p{font-size:1.25em;color:#8b949e;line-height:1.6;margin-bottom:30px}
.hero .cta-group{display:flex;gap:12px;justify-content:center;flex-wrap:wrap}
.btn{display:inline-block;padding:14px 32px;border-radius:8px;font-weight:600;font-size:1em;text-decoration:none;transition:all .2s}
.btn-primary{background:#238636;color:#fff;border:none}.btn-primary:hover{background:#2ea043;transform:translateY(-1px);box-shadow:0 4px 12px #23863640}
.btn-outline{background:transparent;color:#58a6ff;border:1px solid #30363d}.btn-outline:hover{border-color:#58a6ff;background:#58a6ff10}
.container{max-width:1100px;margin:0 auto;padding:0 20px}
h2{font-size:2em;color:#f0f6fc;margin:60px 0 30px;text-align:center}
h2 span{background:linear-gradient(135deg,#58a6ff,#3fb950);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.plans{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:20px;margin:40px 0}
.plan{background:#161b22;border:1px solid #30363d;border-radius:14px;padding:32px 24px;text-align:center;transition:all .3s;position:relative;overflow:hidden}
.plan:hover{transform:translateY(-4px);box-shadow:0 8px 30px #00000040}
.plan.featured{background:linear-gradient(180deg,#1f2937 0%,#161b22 100%);border-color:#1f6feb}
.plan.featured:before{content:'MAS POPULAR';position:absolute;top:12px;right:12px;background:#1f6feb;color:#fff;padding:4px 14px;border-radius:20px;font-size:.72em;font-weight:700;letter-spacing:.5px}
.plan .emoji{font-size:2.5em;margin-bottom:12px}
.plan h3{font-size:1.15em;color:#f0f6fc;margin-bottom:16px}
.plan .price{font-size:3em;font-weight:800;color:#58a6ff;line-height:1}
.plan .period{color:#8b949e;font-size:.9em;margin:4px 0 16px}
.plan .tokens{display:inline-block;background:#23863620;color:#3fb950;padding:4px 12px;border-radius:20px;font-size:.9em;font-weight:600;margin-bottom:20px}
.plan ul{list-style:none;text-align:left;margin:20px 0;font-size:.92em}
.plan ul li{padding:6px 0;display:flex;align-items:center;gap:8px}
.plan ul li:before{content:'';display:inline-block;width:6px;height:6px;background:#3fb950;border-radius:50%;flex-shrink:0}
.plan .btn{width:100%}.plan.featured .btn-primary{background:#1f6feb}.plan.featured .btn-primary:hover{background:#388bfd}
.why{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:16px;margin:30px 0 60px}
.why-card{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:24px;transition:all .2s}
.why-card:hover{border-color:#58a6ff40}.why-card .icon{font-size:1.5em;margin-bottom:10px}
.why-card h4{color:#f0f6fc;margin-bottom:8px;font-size:1.05em}.why-card p{color:#8b949e;font-size:.92em;line-height:1.5}
.code-block{background:#0d1117;border:1px solid #30363d;border-radius:12px;padding:24px;margin:20px 0;position:relative;overflow-x:auto}
.code-block .lang{position:absolute;top:12px;right:16px;color:#8b949e;font-size:.8em}
.code-block pre{color:#c9d1d9;font-size:.9em;line-height:1.6}
.c{color:#58a6ff}.s{color:#a5d6ff}.u{color:#3fb950}
.endpoint{background:#161b22;border-left:3px solid #1f6feb;border-radius:0 8px 8px 0;padding:16px 20px;margin:16px 0}
.endpoint .method{display:inline-block;background:#1f6feb20;color:#58a6ff;padding:2px 10px;border-radius:4px;font-size:.8em;font-weight:700;margin-right:10px}
.endpoint .path{color:#f0f6fc;font-family:monospace;font-size:.95em}
.endpoint .desc{color:#8b949e;font-size:.9em;margin-top:8px}
.footer{text-align:center;padding:40px 20px;color:#8b949e;font-size:.85em;border-top:1px solid #30363d;margin-top:60px}
.footer a{color:#58a6ff;text-decoration:none}.footer a:hover{text-decoration:underline}
@media(max-width:640px){.hero h1{font-size:2em}.plans{grid-template-columns:1fr}}
</style></head><body>
<nav class="nav"><a class="logo" href="/">🤖 DeepAPI</a><div class="links"><a href="#pricing">Precios</a><a href="#docs">API</a><a href="#why">¿Por qué?</a></div></nav>
<div class="hero"><h1>IA de clase mundial sin barreras</h1><p>El mismo formato que OpenAI. La misma calidad que GPT-4o. Sin tarjeta de crédito, sin KYC, sin pagar en dólares. Solo necesitas un email.</p><div class="cta-group"><a class="btn btn-primary" href="http://localhost:9001/v1/auth/register">Comenzar gratis →</a><a class="btn btn-outline" href="#docs">Ver documentación</a></div></div>
<div class="container">
<h2 id="pricing"><span>Planes simples, precios justos</span></h2>
<div class="plans">
<div class="plan"><div class="emoji">🚀</div><h3>Gratis</h3><div class="price">$0</div><div class="period">para siempre</div><div class="tokens">5M tokens/mes</div><ul><li>~333 llamadas/día</li><li>API OpenAI compatible</li><li>SDK open-source</li><li>Documentación en español</li></ul><a class="btn btn-outline" href="http://localhost:9001/v1/auth/register">Comenzar</a></div>
<div class="plan featured"><div class="emoji">⚡</div><h3>Starter</h3><div class="price">$8</div><div class="period">por mes</div><div class="tokens">50M tokens/mes</div><ul><li>~3,300 llamadas/día</li><li>Sin rate limiting</li><li>Historial 30 días</li><li>Soporte por email</li></ul><a class="btn btn-primary" href="http://localhost:9001/v1/auth/register">Comenzar gratis</a></div>
<div class="plan"><div class="emoji">💎</div><h3>Pro</h3><div class="price">$25</div><div class="period">por mes</div><div class="tokens">150M tokens/mes</div><ul><li>~10,000 llamadas/día</li><li>Acceso prioritario</li><li>Historial 90 días</li><li>Soporte WhatsApp</li></ul><a class="btn btn-outline" href="http://localhost:9001/v1/auth/register">Comenzar gratis</a></div>
<div class="plan"><div class="emoji">🏢</div><h3>Business</h3><div class="price">$69</div><div class="period">por mes</div><div class="tokens">350M tokens/mes</div><ul><li>~23K llamadas/día</li><li>Soporte Slack</li><li>Hasta 5 miembros</li><li>SLA 99.9% garantizado</li></ul><a class="btn btn-outline" href="http://localhost:9001/v1/auth/register">Comenzar gratis</a></div></div>
<h2 id="why"><span>¿Por qué DeepAPI?</span></h2>
<div class="why">
<div class="why-card"><div class="icon">🚫</div><h4>Sin tarjeta de crédito</h4><p>OpenAI y Anthropic exigen tarjeta internacional. Nosotros solo necesitamos tu email.</p></div>
<div class="why-card"><div class="icon">🧠</div><h4>Calidad GPT-4o</h4><p>Usamos DeepSeek V3 y R1, modelos comparables a GPT-4o en benchmarks independientes.</p></div>
<div class="why-card"><div class="icon">💰</div><h4>62× más barato</h4><p>Nuestro plan Starter cuesta 62 veces menos por token que GPT-4o. Sin sacrificar calidad.</p></div>
<div class="why-card"><div class="icon">🔌</div><h4>OpenAI compatible</h4><p>Cambia la URL base y tu código funciona sin tocar nada. Migra en 2 minutos.</p></div>
<div class="why-card"><div class="icon">🌎</div><h4>Soporte en español</h4><p>Documentación, errores y ayuda en tu idioma. Construido en Latinoamérica para el mundo.</p></div>
<div class="why-card"><div class="icon">🛡️</div><h4>Sin KYC ni pasaporte</h4><p>No pedimos documentos, ni selfies, ni verificación de identidad. Tu privacidad importa.</p></div></div>
<h2 id="docs"><span>Empezar en 30 segundos</span></h2>
<div class="code-block"><span class="lang">bash</span><pre><span class="c">curl</span> -X POST <span class="u">http://localhost:9001/v1/auth/register</span> -H <span class="s">"Content-Type: application/json"</span> -d <span class="s">'{"email":"tu@email.com"}'</span></pre></div>
<p style="color:#8b949e;text-align:center;margin:10px 0">Guarda tu <code style="background:#161b22;padding:2px 6px;border-radius:3px">api_key</code>. La necesitarás para todas las llamadas.</p>
<div class="endpoint"><span class="method">POST</span><span class="path">/v1/chat/completions</span><div class="desc">Endpoint principal. 100% compatible con OpenAI SDK. Mismo request, misma respuesta.</div></div>
<div class="code-block"><span class="lang">bash</span><pre><span class="c">curl</span> -X POST <span class="u">http://localhost:9001/v1/chat/completions</span> -H <span class="s">"Authorization: Bearer TU_API_KEY"</span> -H <span class="s">"Content-Type: application/json"</span> -d <span class="s">'{"model":"deepseek-chat","messages":[{"role":"user","content":"Hola"}]}'</span></pre></div>
<div class="endpoint"><span class="method">GET</span><span class="path">/v1/auth/stats?api_key=TU_KEY</span><div class="desc">Consulta tu uso, plan actual, tokens consumidos y referidos.</div></div>
<div class="endpoint" style="border-left-color:#3fb950"><span class="method" style="background:#3fb95020;color:#3fb950">REFER</span><span class="path">3 referidos = 1 mes gratis</span><div class="desc">Comparte tu código. Cada 3 amigos que se registren, te regalamos 1 mes de tu plan actual.</div></div>
<footer class="footer">DeepAPI es un producto de <a href="https://github.com/LuisColorado-tech/trading-agent">Agents Corp</a> — Construido en Latinoamérica para el mundo.</footer>
</div></body></html>"""

UPGRADE_PAGE = """<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"><title>Upgrade | DeepAPI</title><style>body{background:#0d1117;color:#c9d1d9;font-family:-apple-system,sans-serif;max-width:600px;margin:0 auto;padding:40px 20px;text-align:center}h1{color:#58a6ff}.btn{display:inline-block;background:#238636;color:white;padding:12px 30px;border-radius:6px;text-decoration:none;margin:10px;font-size:1.1em}</style></head><body><h1>⚡ Upgrade</h1><p>Pago con MercadoPago, cripto y transferencia próximamente.</p><p>Contáctanos en Telegram para activar tu plan manualmente.</p><a class="btn" href="https://t.me/Arthas_trading_bot">Contactar en Telegram</a></body></html>"""

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9001)
