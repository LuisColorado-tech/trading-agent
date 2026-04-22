"""
run_options.py — Loop principal del agente de Theta Farming (Deribit).

Pipeline INDEPENDIENTE del trading cripto y de polymarket.

Modo de operación:
  - Monitor cada 5 minutos: verifica stops y profit locks
  - Scan de nuevas entradas cada 1 hora
  - Snapshot IV cada hora (para backtesting)
  - Heartbeat Redis en cada ciclo

Ejecutar manualmente:
  /opt/trading/venv/bin/python3 scripts/run_options.py

Servicio systemd:
  /etc/systemd/system/options-agent.service
"""
import os
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from loguru import logger

sys.path.insert(0, '/opt/trading')
load_dotenv('/opt/trading/config/.env')

logger.add(
    '/opt/trading/logs/options_{time}.log',
    rotation='1 day',
    retention='30 days',
    level='INFO',
)

from agents.options_agent import OptionsAgent, MONITOR_INTERVAL_SECONDS
from core.notifications import send_telegram

AGENT_VERSION = '1.0.0'


def main():
    logger.info(f'OPTIONS AGENT v{AGENT_VERSION} — STARTING')
    send_telegram(
        f'🚀 <b>Options Agent iniciado</b>\n'
        f'Versión: {AGENT_VERSION}\n'
        f'Modo: PAPER\n'
        f'Hora: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}'
    )

    agent = OptionsAgent()

    cycle_count = 0
    while True:
        try:
            cycle_count += 1
            logger.info(f'--- OPTIONS CYCLE #{cycle_count} ---')
            agent.run_cycle()
        except KeyboardInterrupt:
            logger.info('OPTIONS AGENT: detenido por usuario')
            send_telegram('⏹ <b>Options Agent</b> detenido manualmente')
            break
        except Exception as e:
            logger.exception(f'OPTIONS CYCLE ERROR: {e}')
            send_telegram(
                f'⚠️ <b>Options Agent ERROR</b>\n'
                f'Ciclo #{cycle_count}\n'
                f'Error: {str(e)[:200]}'
            )
            # No detener el agente por un error en un ciclo
            # Esperar 60s antes de reintentar
            time.sleep(60)
            continue

        logger.info(f'Esperando {MONITOR_INTERVAL_SECONDS}s hasta próximo ciclo...')
        time.sleep(MONITOR_INTERVAL_SECONDS)


if __name__ == '__main__':
    main()
