"""ViralBot — AI Content Generator. Finanzas Personales LatAm."""
import os, sys, json, urllib.request
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')

DS_KEY = os.getenv("DEEPSEEK_API_KEY", "")

def generate_content(topic: str, format_type: str = "twitter_thread") -> str:
    """Generate viral content about personal finance using DeepSeek."""
    prompts = {
        "twitter_thread": f"Eres un experto en finanzas personales para Latinoamerica. Escribe un hilo de Twitter de 5 tweets sobre: {topic}. Cada tweet maximo 280 caracteres. Usa lenguaje cercano, incluye un dato impactante, y termina con una llamada a la accion. NO uses hashtags genericos. Responde SOLO con los tweets numerados.",
        "linkedin_post": f"Eres un experto en educacion financiera. Escribe un post de LinkedIn (max 1200 caracteres) sobre: {topic}. Profesional pero cercano. Incluye una estadistica real si la conoces. Termina con una pregunta para generar engagement.",
        "tiktok_script": f"Eres un creador de contenido viral de finanzas. Escribe un script para TikTok/Reels sobre: {topic}. HOOK fuerte en primeros 3 segundos. Max 60 segundos. Incluye indicaciones visuales entre [corchetes]. Lenguaje callejero pero educado.",
    }
    prompt = prompts.get(format_type, prompts["twitter_thread"])

    payload = json.dumps({
        "model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1000, "temperature": 0.8,
    }).encode()

    req = urllib.request.Request(
        "https://api.deepseek.com/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {DS_KEY}"}
    )
    resp = urllib.request.urlopen(req, timeout=30)
    result = json.loads(resp.read())
    return result["choices"][0]["message"]["content"]

def generate_daily_batch():
    """Generate today's content batch."""
    topics = [
        "Como ahorrar ganando el salario minimo",
        "La verdad sobre las tarjetas de credito que nadie te dice",
        "Invertir 100 dolares: esto es lo que realmente puedes ganar",
        "5 errores financieros que cometes sin darte cuenta",
    ]
    batch = {}
    for topic in topics:
        batch[topic] = {
            "thread": generate_content(topic, "twitter_thread"),
            "linkedin": generate_content(topic, "linkedin_post"),
            "tiktok": generate_content(topic, "tiktok_script"),
        }
    return batch

if __name__ == "__main__":
    batch = generate_daily_batch()
    out = f"/opt/agents-corp/business/viralbot/drafts/{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.json"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w') as f:
        json.dump(batch, f, indent=2, ensure_ascii=False)
    print(f"Generated {len(batch)} topics -> {out}")
