"""
telegram_bot.py — Bot de Telegram interactivo para Arthas Trading Agent.

Escucha comandos del usuario en Telegram y responde con la salida de arthas_trading.py.
Ejecutar: python3 scripts/telegram_bot.py (o como servicio systemd)
"""
import io
import os
import subprocess
import sys
import time

import requests
from loguru import logger

sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv

load_dotenv('/opt/trading/config/.env')

logger.add(
    '/opt/trading/logs/telegram_bot_{time}.log',
    rotation='1 day',
    retention='14 days',
    level='INFO',
)

TELEGRAM_TOKEN = '8179816401:AAHF3xprmPeauuOapGDD9idQrLsv8Dl2EYE'
TELEGRAM_CHAT_ID = 999936393
API = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}'

# Mapeo de comandos de Telegram → comandos de arthas_trading.py
COMMAND_MAP = {
    '/status': 'status',
    '/portfolio': 'portfolio',
    '/trades': 'trades',
    '/signals': 'signals',
    '/prices': 'prices',
    '/metrics': 'metrics',
    '/scan': 'scan',
    '/report': 'report',
    '/poly': 'poly',
    '/poly_status': 'poly',
    '/polystatus': 'poly',
    '/polyreport': 'polyreport',
    '/help': 'help',
    # Sin slash también
    'status': 'status',
    'portfolio': 'portfolio',
    'trades': 'trades',
    'signals': 'signals',
    'prices': 'prices',
    'metrics': 'metrics',
    'scan': 'scan',
    'report': 'report',
    'poly': 'poly',
    'poly_status': 'poly',
    'polystatus': 'poly',
    'polyreport': 'polyreport',
    'help': 'help',
}


def send_message(text: str, chat_id: int = TELEGRAM_CHAT_ID):
    """Envía mensaje por Telegram, dividiendo si es muy largo."""
    MAX_LEN = 4000
    chunks = []
    while len(text) > MAX_LEN:
        cut = text[:MAX_LEN].rfind('\n')
        if cut == -1:
            cut = MAX_LEN
        chunks.append(text[:cut])
        text = text[cut:].lstrip('\n')
    chunks.append(text)

    for chunk in chunks:
        if not chunk.strip():
            continue
        try:
            r = requests.post(
                f'{API}/sendMessage',
                json={'chat_id': chat_id, 'text': chunk},
                timeout=10,
            )
            if not r.json().get('ok'):
                logger.error(f'Telegram send failed: {r.json()}')
            else:
                logger.info(f'Mensaje enviado OK ({len(chunk)} chars)')
        except Exception as e:
            logger.error(f'Error enviando mensaje: {e}')


def run_arthas_command(command: str) -> str:
    """Ejecuta un comando de arthas_trading.py y devuelve la salida."""
    try:
        result = subprocess.run(
            ['/opt/trading/venv/bin/python3', '/opt/trading/scripts/arthas_trading.py', command],
            capture_output=True,
            text=True,
            timeout=60,
            cwd='/opt/trading',
        )
        output = result.stdout
        if result.stderr:
            output += f'\n⚠️ {result.stderr[-200:]}'
        return output.strip() if output.strip() else '(sin salida)'
    except subprocess.TimeoutExpired:
        return '⏰ Comando excedió el tiempo límite (60s)'
    except Exception as e:
        return f'❌ Error ejecutando comando: {e}'


def process_message(message: dict):
    """Procesa un mensaje entrante de Telegram."""
    chat_id = message.get('chat', {}).get('id')
    text = (message.get('text') or '').strip()

    # Solo responder al chat autorizado
    if chat_id != TELEGRAM_CHAT_ID:
        logger.warning(f'Mensaje de chat no autorizado: {chat_id}')
        return

    if not text:
        return

    # Extraer comando (primera palabra)
    cmd_raw = text.split()[0].lower()

    arthas_cmd = COMMAND_MAP.get(cmd_raw)
    if arthas_cmd is None:
        send_message(
            f'❓ Comando no reconocido: {cmd_raw}\n\n'
            'Comandos disponibles:\n'
            '  /status — Estado general\n'
            '  /portfolio — Portfolio\n'
            '  /trades — Trades\n'
            '  /signals — Señales\n'
            '  /prices — Precios\n'
            '  /metrics — Métricas\n'
            '  /scan — Escanear mercados\n'
            '  /report — Reporte completo\n'
            '  /poly — Polymarket status\n'
            '  /polyreport — Polymarket reporte\n'
            '  /help — Ayuda',
            chat_id,
        )
        return

    logger.info(f'Comando recibido: {cmd_raw} → {arthas_cmd}')
    output = run_arthas_command(arthas_cmd)
    send_message(output, chat_id)


def polling_loop():
    """Long-polling loop para recibir mensajes."""
    logger.info('Telegram bot started — listening for commands...')

    # Obtener offset actual sin consumir mensajes
    offset = None
    try:
        r = requests.get(f'{API}/getUpdates', params={'timeout': 0, 'limit': 1}, timeout=5)
        d = r.json()
        if d.get('ok') and d.get('result'):
            # Hay mensajes pendientes — procesarlos en el loop
            logger.info(f'{len(d["result"])} mensajes pendientes al arrancar')
        time.sleep(1)
    except Exception:
        pass

    backoff = 1

    while True:
        try:
            params = {'timeout': 30, 'allowed_updates': ['message']}
            if offset is not None:
                params['offset'] = offset

            resp = requests.get(f'{API}/getUpdates', params=params, timeout=35)
            data = resp.json()

            if not data.get('ok'):
                err_code = data.get('error_code', 0)
                if err_code == 409:
                    logger.warning(f'Conflict 409 — backoff {backoff}s')
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 30)
                    continue
                logger.error(f'Telegram API error: {data}')
                time.sleep(5)
                continue

            # Reset backoff on success
            backoff = 1

            for update in data.get('result', []):
                offset = update['update_id'] + 1
                msg = update.get('message')
                if msg:
                    process_message(msg)

        except requests.exceptions.Timeout:
            continue
        except KeyboardInterrupt:
            logger.info('Telegram bot stopped by user')
            break
        except Exception as e:
            logger.error(f'Polling error: {e}', exc_info=True)
            time.sleep(5)


if __name__ == '__main__':
    polling_loop()
