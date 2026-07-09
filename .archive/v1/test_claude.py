"""
Test de conectividad con Anthropic API (Claude Opus).
Ejecutar: cd /opt/trading && source venv/bin/activate && python3 scripts/test_claude.py
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv('/opt/trading/config/.env')

api_key = os.getenv('ANTHROPIC_API_KEY', '')
model = os.getenv('CLAUDE_MODEL', 'claude-opus-4-5')

if not api_key or api_key == 'sk-ant-CHANGE_ME':
    print(f'[SKIP] ANTHROPIC_API_KEY not configured yet (current: {api_key[:12]}...)')
    print(f'  -> Set it in /opt/trading/config/.env')
    print(f'  -> Model configured: {model}')
    print('  -> Network reachability to api.anthropic.com: ', end='')
    import httpx
    try:
        r = httpx.get('https://api.anthropic.com/v1/messages', timeout=10)
        print(f'OK (HTTP {r.status_code} — expected 401/405 without auth)')
    except Exception as e:
        print(f'FAIL ({e})')
    sys.exit(0)

import anthropic

client = anthropic.Anthropic(api_key=api_key)
msg = client.messages.create(
    model=model,
    max_tokens=100,
    messages=[{'role': 'user', 'content': 'Respond only with: CLAUDE_API_OK'}],
)
print(msg.content[0].text)
print(f'Tokens used: {msg.usage.input_tokens} in / {msg.usage.output_tokens} out')
print('Claude API: OK')
