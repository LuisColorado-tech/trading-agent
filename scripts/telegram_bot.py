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
from openai import OpenAI

sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv

load_dotenv('/opt/trading/config/.env')

_openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# Historial de conversación por chat_id (máx. 20 turnos en memoria)
_conversation_history: dict = {}
_MAX_HISTORY = 20

ARTHAS_SYSTEM_PROMPT = """Eres Arthas, el asistente de trading y finanzas personales de Lucho (Luis Colorado).

Tu personalidad:
- Directo y conciso. Sin rodeos.
- Paisa colombiano cultivado: mezclás el rigor técnico con expresiones naturales.
- Conocés en profundidad cripto, trading algorítmico, Polymarket y estrategias quant.
- Sos el co-piloto de Lucho en todas sus operaciones e ideas de negocio.
- Cuando no sabés algo, lo decís sin drama. Nunca inventás datos.
- Podés hablar de cualquier tema: finanzas, código, vida, ideas — sos su asistente integral.

Contexto del sistema:
- Estás corriendo en un servidor Linux con un trading agent en /opt/trading.
- Hay una paper session activa con $10,000 de capital.
- Si Lucho pregunta por datos en tiempo real (trades, portfolio, precios), decile que use /status, /portfolio o /report para datos frescos desde la base de datos.

Respondé siempre en español (castellano colombiano natural, no exagerés el paisa)."""

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


def chat_with_arthas(chat_id: int, user_text: str) -> str:
    """Envía el mensaje al LLM con historial conversacional y devuelve la respuesta de Arthas."""
    history = _conversation_history.setdefault(chat_id, [])

    history.append({'role': 'user', 'content': user_text})

    # Mantener máximo _MAX_HISTORY turnos (par user/assistant)
    if len(history) > _MAX_HISTORY:
        history[:] = history[-_MAX_HISTORY:]

    try:
        response = _openai_client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[{'role': 'system', 'content': ARTHAS_SYSTEM_PROMPT}] + history,
            max_tokens=800,
            temperature=0.7,
        )
        reply = response.choices[0].message.content.strip()
        history.append({'role': 'assistant', 'content': reply})
        return reply
    except Exception as e:
        logger.error(f'Error en chat_with_arthas: {e}')
        return f'⚠️ No pude procesar eso ahora: {e}'


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

    # Extraer primera palabra para detectar comandos
    cmd_raw = text.split()[0].lower()
    arthas_cmd = COMMAND_MAP.get(cmd_raw)

    if arthas_cmd is not None:
        # Es un comando → ejecutar arthas_trading.py
        logger.info(f'Comando recibido: {cmd_raw} → {arthas_cmd}')
        output = run_arthas_command(arthas_cmd)
        send_message(output, chat_id)
    else:
        # Es conversación libre → responder con LLM
        logger.info(f'Conversación libre ({len(text)} chars): {text[:60]}...' if len(text) > 60 else f'Conversación libre: {text}')
        reply = chat_with_arthas(chat_id, text)
        send_message(reply, chat_id)


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
                    logger.error('Conflict 409 — hay otra instancia activa. Cerrando este proceso.')
                    sys.exit(1)
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


_PID_FILE = '/tmp/arthas_telegram_bot.pid'


def _acquire_lock():
    """Evita múltiples instancias usando PID file. Mata el proceso anterior si quedó huérfano."""
    if os.path.exists(_PID_FILE):
        try:
            old_pid = int(open(_PID_FILE).read().strip())
            # Verificar si el proceso sigue vivo
            os.kill(old_pid, 0)
            # Si no lanzó excepción, el proceso EXISTE → salir
            logger.error(f'Bot ya está corriendo (PID {old_pid}). Saliendo.')
            sys.exit(1)
        except (ProcessLookupError, ValueError):
            # PID file huérfano — el proceso ya no existe, continuar
            logger.info('PID file huérfano encontrado, continuando...')

    with open(_PID_FILE, 'w') as f:
        f.write(str(os.getpid()))

    import atexit
    atexit.register(lambda: os.path.exists(_PID_FILE) and os.remove(_PID_FILE))


if __name__ == '__main__':
    _acquire_lock()
    polling_loop()
