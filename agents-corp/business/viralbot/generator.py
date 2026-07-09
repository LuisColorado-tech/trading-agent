"""
ViralBot — AI Content Generator + Scheduler
Generates social media content with DeepSeek and queues for publishing.
"""
import os, sys, json, time, urllib.request
from datetime import datetime, timezone

sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')

DS_KEY = os.getenv("DEEPSEEK_API_KEY", "")
TWITTER_BEARER = os.getenv("TWITTER_BEARER_TOKEN", "")
TWITTER_API_KEY = os.getenv("TWITTER_API_KEY", "")
TWITTER_API_SECRET = os.getenv("TWITTER_API_SECRET", "")
TWITTER_ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN", "")
TWITTER_ACCESS_SECRET = os.getenv("TWITTER_ACCESS_SECRET", "")

DRAFTS_DIR = "/opt/trading/agents-corp/business/viralbot/drafts"
PUBLISHED_DIR = "/opt/trading/agents-corp/business/viralbot/published"
os.makedirs(DRAFTS_DIR, exist_ok=True)
os.makedirs(PUBLISHED_DIR, exist_ok=True)


def call_llm(prompt, max_tokens=1000, temperature=0.8):
    if not DS_KEY: return "NO_API_KEY"
    payload = json.dumps({"model":"deepseek-chat","messages":[{"role":"user","content":prompt}],"max_tokens":max_tokens,"temperature":temperature}).encode()
    req = urllib.request.Request("https://api.deepseek.com/v1/chat/completions",data=payload,headers={"Content-Type":"application/json","Authorization":f"Bearer {DS_KEY}"})
    try:
        resp = urllib.request.urlopen(req, timeout=60)
        return json.loads(resp.read())["choices"][0]["message"]["content"]
    except Exception as e:
        return f"ERROR: {e}"


def generate_thread(topic: str) -> str:
    return call_llm(f"""Eres un experto en finanzas personales para Latinoamerica.
Escribe un hilo de Twitter de 5 tweets sobre: {topic}.
Cada tweet maximo 280 caracteres. Usa lenguaje cercano, incluye un dato impactante,
y termina con una llamada a la accion. NO uses hashtags genericos. Responde SOLO con los tweets numerados de 1 a 5.""")


def generate_linkedin(topic: str) -> str:
    return call_llm(f"""Eres un experto en educacion financiera.
Escribe un post de LinkedIn (max 1200 caracteres) sobre: {topic}.
Profesional pero cercano. Incluye una estadistica real.
Termina con una pregunta para generar engagement. SOLO el post.""")


def generate_tiktok_script(topic: str) -> str:
    return call_llm(f"""Eres un creador de contenido viral de finanzas.
Escribe un script para TikTok/Reels sobre: {topic}.
HOOK fuerte en primeros 3 segundos. Max 60 segundos.
Incluye indicaciones visuales entre [corchetes]. Lenguaje cercano. SOLO el script.""")


DAILY_TOPICS = [
    "Como ahorrar ganando el salario minimo",
    "La verdad sobre las tarjetas de credito que nadie te dice",
    "Invertir 100 dolares: cuanto puedes ganar realmente",
    "5 errores financieros que cometes sin darte cuenta",
    "El truco del interes compuesto explicado simple",
    "Por que tu banco NO quiere que sepas esto",
    "Cuanto necesitas para jubilarte en Latinoamerica",
    "La diferencia entre ser pobre y estar quebrado",
    "El activo mas rentable no es lo que crees",
    "Como duplique mis ahorros sin trabajar mas horas",
    "Lo que aprendi perdiendo 500 dolares en inversiones",
    "La regla 50-30-20 explicada para principiantes",
    "Por que comprar casa NO siempre es buena inversion",
]


def generate_daily_batch():
    """Generate today's content batch across formats."""
    import random
    topics = random.sample(DAILY_TOPICS, min(3, len(DAILY_TOPICS)))
    batch = {"generated_at": datetime.now(timezone.utc).isoformat(), "topics": {}}
    for topic in topics:
        thread = generate_thread(topic)
        linkedin = generate_linkedin(topic) if random.random() > 0.5 else None
        tiktok = generate_tiktok_script(topic) if random.random() > 0.5 else None
        batch["topics"][topic] = {"thread": thread, "linkedin": linkedin, "tiktok": tiktok}
    return batch


def save_batch(batch):
    filename = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}_batch.json"
    path = os.path.join(DRAFTS_DIR, filename)
    with open(path, 'w') as f:
        json.dump(batch, f, indent=2, ensure_ascii=False)
    return path


def publish_to_queue(draft_file):
    """Move approved draft to publish queue."""
    src = os.path.join(DRAFTS_DIR, draft_file)
    dst = os.path.join(PUBLISHED_DIR, draft_file)
    if os.path.exists(src):
        os.rename(src, dst)
        return dst
    return None


def tweet(text: str) -> dict:
    """Post a tweet via Twitter API v2."""
    if not TWITTER_BEARER:
        return {"error": "Twitter API not configured", "status": "simulated", "text": text[:50]}

    payload = json.dumps({"text": text}).encode()
    req = urllib.request.Request(
        "https://api.twitter.com/2/tweets",
        data=payload,
        headers={
            "Authorization": f"Bearer {TWITTER_BEARER}",
            "Content-Type": "application/json"
        },
        method="POST"
    )
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)[:150]}


def tweet_thread(thread_text: str) -> list:
    """Post a thread by splitting on numbered tweets."""
    lines = [l.strip() for l in thread_text.split('\n') if l.strip() and l[0].isdigit()]
    results = []
    reply_to = None
    for line in lines:
        # Extract tweet text after number
        parts = line.split('. ', 1) if '. ' in line else line.split('.', 1)
        text = parts[1] if len(parts) > 1 else line
        # Truncate to 280
        text = text[:277] + "..." if len(text) > 280 else text

        if TWITTER_BEARER:
            payload = {"text": text}
            if reply_to:
                payload["reply"] = {"in_reply_to_tweet_id": reply_to}
            data = json.dumps(payload).encode()
            req = urllib.request.Request("https://api.twitter.com/2/tweets",data=data,headers={"Authorization":f"Bearer {TWITTER_BEARER}","Content-Type":"application/json"},method="POST")
            try:
                resp = urllib.request.urlopen(req, timeout=15)
                result = json.loads(resp.read())
                tweet_id = result.get("data",{}).get("id")
                if tweet_id: reply_to = tweet_id
                results.append({"text":text[:50],"id":tweet_id,"status":"posted"})
            except Exception as e:
                results.append({"text":text[:50],"error":str(e)[:80]})
        else:
            results.append({"text": text[:50], "status": "simulated"})
    return results


# ─── CLI ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "generate":
        print("Generating daily batch...")
        batch = generate_daily_batch()
        path = save_batch(batch)
        print(f"Saved: {path}")
        for topic, content in batch["topics"].items():
            print(f"  ✅ {topic[:60]}")
            print(f"     Thread: {content['thread'][:80]}...")

    elif len(sys.argv) > 1 and sys.argv[1] == "publish":
        drafts = [f for f in os.listdir(DRAFTS_DIR) if f.endswith('.json')]
        if not drafts:
            print("No drafts to publish")
        else:
            draft = drafts[0]
            with open(os.path.join(DRAFTS_DIR, draft)) as f:
                batch = json.load(f)
            for topic, content in batch["topics"].items():
                if content.get("thread"):
                    results = tweet_thread(content["thread"])
                    for r in results:
                        print(f"  {'✅' if 'id' in r else '❌'} {r.get('text','')[:60]}")
            publish_to_queue(draft)
            print(f"Published and moved: {draft}")

    elif len(sys.argv) > 1 and sys.argv[1] == "status":
        drafts = len([f for f in os.listdir(DRAFTS_DIR) if f.endswith('.json')])
        published = len([f for f in os.listdir(PUBLISHED_DIR) if f.endswith('.json')])
        print(f"Drafts: {drafts} | Published: {published}")

    else:
        print("Commands: generate | publish | status")
