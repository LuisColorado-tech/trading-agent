"""
run_options.py — Loop principal del agente de Theta Farming (Deribit).

Pipeline INDEPENDIENTE del trading cripto y de polymarket.

Modo de operación:
  - Monitor cada 5 minutos: verifica stops y profit locks
  - Scan de nuevas entradas cada 30 minutos
  - Snapshot IV cada hora (para backtesting)
  - Heartbeat Redis en cada ciclo

Ejecutar manualmente:
  /opt/trading/venv/bin/python3 scripts/run_options.py --underlying BTC
  /opt/trading/venv/bin/python3 scripts/run_options.py --underlying ETH

Servicio systemd:
  /etc/systemd/system/options-agent.service
"""
import argparse
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

AGENT_VERSION = '2.0.0'


def main():
    parser = argparse.ArgumentParser(description='Options Theta Farming Agent')
    parser.add_argument(
        '--underlying', default='BTC', choices=['BTC', 'ETH'],
        help='Subyacente para opciones en Deribit (default: BTC)',
    )
    args = parser.parse_args()
    underlying = args.underlying.upper()

    logger.info(f'OPTIONS AGENT v{AGENT_VERSION} ({underlying}) — STARTING')
    send_telegram(
        f'🚀 <b>Options Agent iniciado</b>\n'
        f'Versión: {AGENT_VERSION}\n'
        f'Subyacente: <b>{underlying}</b>\n'
        f'Modo: PAPER\n'
        f'Hora: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}'
    )

    agent = OptionsAgent(underlying=underlying)

    cycle_count = 0
    last_heartbeat_hour = -1
    while True:
        try:
            cycle_count += 1
            logger.info(f'--- OPTIONS CYCLE #{cycle_count} ---')
            agent.run_cycle()

            # ── Telegram heartbeat cada 4h con estado de posiciones ──
            now = datetime.now(timezone.utc)
            if now.hour % 4 == 0 and now.hour != last_heartbeat_hour and now.minute < 10:
                last_heartbeat_hour = now.hour
                session = agent.session_mgr.ensure_active_session()
                open_pos = agent.session_mgr.get_open_positions(session['session_name'])
                balance = float(session['current_balance_usd'])
                pnl = float(session['total_pnl_usd'])
                pos_lines = []
                for p in open_pos:
                    inst = p.get('instrument_name', '?')
                    entry_usd = float(p.get('entry_premium_usd', 0))
                    mark = agent.strategy.get_current_mark_price(inst)
                    if mark:
                        btc_idx = agent.strategy._get_index_price() or 80000
                        curr_usd = mark * btc_idx
                        decay = (1 - mark / float(p.get('entry_premium_btc', 1))) * 100
                        pos_lines.append(f'  {inst}: mark={mark:.4f}BTC (${curr_usd:.0f}) decay={decay:+.0f}%')
                    else:
                        pos_lines.append(f'  {inst}: (sin mark)')
                session_name = session['session_name']
                send_telegram(
                    f'📊 <b>Options Heartbeat</b>\n'
                    f'Sesión: {session_name}\n'
                    f'Balance: <b>${balance:.2f}</b> | PnL: ${pnl:+.2f}\n'
                    f'Posiciones ({len(open_pos)}):\n' +
                    '\n'.join(pos_lines),
                    silent=True,
                )
        except KeyboardInterrupt:
            logger.info('OPTIONS AGENT: detenido por usuario')
            send_telegram('⏹ <b>Options Agent</b> detenido manualmente')
            break
        except Exception as e:
            logger.exception(f'OPTIONS CYCLE ERROR: {e}')
            send_telegram(
                f'⚠️ <b>Options Agent ERROR</b> ({underlying})\n'
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
