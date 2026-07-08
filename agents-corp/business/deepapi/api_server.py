"""DeepAPI — AI API Gateway. OpenAI-compatible endpoint."""
import os, sys, json, hashlib, secrets, time
from datetime import datetime, timezone
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
import uvicorn

sys.path.insert(0, '/opt/agents-corp')
from shared import validate_api_key, check_rate_limit, track_token_usage, get_db
from sqlalchemy import text

app = FastAPI(title="DeepAPI", version="0.1.0")

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    api_key = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing API key")

    user = validate_api_key(api_key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")

    if not check_rate_limit(user['id'], max_requests=100):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    body = await request.json()
    messages = body.get("messages", [])
    model = body.get("model", "deepseek-chat")

    try:
        # Forward to DeepSeek
        import urllib.request
        ds_key = os.getenv("DEEPSEEK_API_KEY", "")
        payload = json.dumps({
            "model": "deepseek-chat",
            "messages": messages,
            "max_tokens": body.get("max_tokens", 1024),
            "temperature": body.get("temperature", 0.7),
        }).encode()

        req = urllib.request.Request(
            "https://api.deepseek.com/v1/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {ds_key}"
            }
        )
        resp = urllib.request.urlopen(req, timeout=60)
        result = json.loads(resp.read())

        # Track usage
        tokens = result.get("usage", {}).get("total_tokens", 0)
        track_token_usage(user['id'], tokens)

        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Provider error: {str(e)[:100]}")

@app.post("/v1/auth/register")
async def register(request: Request):
    body = await request.json()
    email = body.get("email")
    plan = body.get("plan", "free")

    if not email:
        raise HTTPException(status_code=400, detail="Email required")

    api_key = "ak_" + secrets.token_hex(16)
    hashed = hashlib.sha256(api_key.encode()).hexdigest()

    engine = get_db()
    with engine.begin() as conn:
        existing = conn.execute(
            text("SELECT id FROM api_users WHERE email = :email"),
            {"email": email}
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Email already registered")

        conn.execute(text("""
            INSERT INTO api_users (id, email, api_key_hash, plan, tokens_limit, active)
            VALUES (gen_random_uuid(), :email, :hash, :plan, :limit, true)
        """), {
            "email": email,
            "hash": hashed,
            "plan": plan,
            "limit": 500000 if plan == "pro" else 2000000 if plan == "business" else 100,
        })

    return {"api_key": api_key, "plan": plan, "message": "Registration successful"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9001)
