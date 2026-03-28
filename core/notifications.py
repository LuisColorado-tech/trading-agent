"""
notifications.py — Notificaciones Telegram compartidas (cripto + polymarket).
"""
import requests
from loguru import logger

TELEGRAM_TOKEN = '8179816401:AAHF3xprmPeauuOapGDD9idQrLsv8Dl2EYE'
TELEGRAM_CHAT = '999936393'


def send_telegram(message: str, silent: bool = False):
    """Envía mensaje por Telegram con formato HTML."""
    try:
        requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            json={
                'chat_id': TELEGRAM_CHAT,
                'text': message,
                'parse_mode': 'HTML',
                'disable_notification': silent,
            },
            timeout=10,
        )
    except Exception as e:
        logger.warning(f'Telegram send failed: {e}')
