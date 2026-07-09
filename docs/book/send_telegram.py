#!/usr/bin/env python3
"""Send the EPUB book via Telegram (Arthas bot)."""
import os
import sys
from pathlib import Path
import requests

BOT_TOKEN = "8179816401:AAHF3xprmPeauuOapGDD9idQrLsv8Dl2EYE"
CHAT_ID = "999936393"
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"
EPUB_PATH = Path(__file__).parent / "AI_Trading_Agent_Educativo.epub"


def send():
    if not EPUB_PATH.exists():
        print(f"ERROR: {EPUB_PATH} no existe. Ejecutá build_epub.py primero.")
        sys.exit(1)

    size_mb = EPUB_PATH.stat().st_size / (1024 * 1024)
    print(f"Enviando {EPUB_PATH.name} ({size_mb:.1f} MB) a Telegram...")

    with open(EPUB_PATH, "rb") as f:
        resp = requests.post(
            f"{API_BASE}/sendDocument",
            data={
                "chat_id": CHAT_ID,
                "caption": "📚 AI Trading Agent — De la Teoría a la Implementación\n"
                           "Libro educativo generado automáticamente."
            },
            files={"document": (EPUB_PATH.name, f, "application/epub+zip")},
            timeout=120,
        )

    if resp.status_code == 200 and resp.json().get("ok"):
        print("✅ Libro enviado exitosamente por Telegram!")
    else:
        print(f"ERROR: {resp.status_code} — {resp.text}")
        sys.exit(1)


if __name__ == "__main__":
    send()
