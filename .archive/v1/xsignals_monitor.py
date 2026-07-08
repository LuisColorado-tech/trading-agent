#!/usr/bin/env python3
"""
xsignals_monitor.py — Cron de escaneo automático de perfiles X para stocks_agent.

Escanea todos los perfiles configurados en xsignals_v2.py y guarda las señales
directamente en PostgreSQL local (tabla xsignals_signals), sin pasar por Supabase.

Uso:
  python3 scripts/xsignals_monitor.py              # escanea todos los perfiles
  python3 scripts/xsignals_monitor.py aguti00       # escanea solo un perfil
  python3 scripts/xsignals_monitor.py --limit 20   # máximo 20 posts por perfil

Cron recomendado (cada 30 min, solo en horario NYSE + pre/post market):
  */30 11-23 * * 1-5 /opt/trading/venv/bin/python3 /opt/trading/scripts/xsignals_monitor.py >> /opt/trading/logs/xsignals.log 2>&1
"""
import os
import sys
import time
from datetime import datetime, timezone

# Asegurar que xsignals_v2 y web_agent sean encontrados
sys.path.insert(0, '/opt/arthas-bot')
sys.path.insert(0, '/opt/trading')

from loguru import logger

# Cargar .env del trading agent
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')

logger.add(
    '/opt/trading/logs/xsignals_{time:YYYY-MM-DD}.log',
    rotation='1 day',
    retention='14 days',
    level='INFO',
    format='{time:HH:mm:ss} | {level} | {message}',
)


def run_monitor(target_profile: str = None, limit: int = 10):
    from xsignals_v2 import load_profiles, scan_profile

    profiles = [target_profile] if target_profile else load_profiles()
    logger.info(f"xsignals_monitor: escaneando {len(profiles)} perfil(es) — limit={limit}")

    total_new = 0
    total_stored = 0
    errors = 0

    for profile in profiles:
        try:
            logger.info(f"Escaneando @{profile}...")
            items, stored = scan_profile(profile, limit=limit, save=True, local=True)
            logger.info(f"@{profile}: {len(items)} nuevos, {stored} guardados en PostgreSQL")
            total_new += len(items)
            total_stored += stored
            # Pausa entre perfiles para no triggear rate limit de X
            if len(profiles) > 1:
                time.sleep(5)
        except Exception as exc:
            logger.error(f"@{profile}: error — {exc}")
            errors += 1

    logger.info(
        f"Resumen: {total_new} posts nuevos | {total_stored} señales guardadas | {errors} errores"
    )
    return total_stored


def main():
    args = sys.argv[1:]
    limit = 10
    target = None

    i = 0
    while i < len(args):
        if args[i] == '--limit' and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        elif not args[i].startswith('--'):
            target = args[i].lstrip('@')
            i += 1
        else:
            i += 1

    run_monitor(target_profile=target, limit=limit)


if __name__ == '__main__':
    main()
