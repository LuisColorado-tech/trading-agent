#!/usr/bin/env python3
"""
run_polymarket_snipe.py — Entry point para Polymarket SNIPE Agent.

Estrategias:
  SNIPE: Compra el lado ganador en minuto 13-14.5 de mercados Up/Down 15m
         a $0.93-$0.97 para cobro de $1.00. WR=94%.
  ARB:   Compra YES+NO cuando suma < $0.985 para profit garantizado.

Uso:
  venv/bin/python3 scripts/run_polymarket_snipe.py                # Paper loop
  venv/bin/python3 scripts/run_polymarket_snipe.py --scan         # Ver mercados activos
  venv/bin/python3 scripts/run_polymarket_snipe.py --stats        # Estadísticas
  venv/bin/python3 scripts/run_polymarket_snipe.py --resolve      # Forzar resolución de trades expirados
"""
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, '/opt/trading')

from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')

import yaml
from loguru import logger

_log_dir = Path('/opt/trading/logs')
_log_dir.mkdir(exist_ok=True)

logger.add(
    str(_log_dir / 'polymarket_snipe_{time}.log'),
    rotation='1 day',
    retention='14 days',
    level='INFO',
    format='{time:YYYY-MM-DD HH:mm:ss} | {level:<7} | {message}',
)

from agents.polymarket_snipe import (
    init_db, ensure_session, scan_15m_updown_markets,
    get_market_tokens, evaluate_snipe, evaluate_arb,
    open_snipe_trade, open_arb_trade,
    resolve_expired_trades, get_stats, count_open,
    daily_pnl, slug_already_traded, MAX_DAILY_LOSS, MAX_CONCURRENT,
    SCAN_INTERVAL, PAPER_BALANCE, DRY_RUN, ASSETS,
    SNIPE_MIN_MINUTE, SNIPE_MAX_MINUTE, SNIPE_THRESHOLD,
    SNIPE_MAX_ENTRY, SNIPE_MIN_ENTRY, SNIPE_SIZE,
    ARB_TARGET_COST, ARB_MIN_GAP, ARB_SIZE,
)
from core.notifications import send_telegram


def cmd_scan():
    """Mostrar mercados Up/Down 15m activos."""
    print(f'\n{"="*70}')
    print(f'POLYMARKET SNIPE — Mercados activos')
    print(f'{"="*70}')
    print(f'Assets: {[a.upper() for a in ASSETS]}')
    print(f'Snipe: min {SNIPE_MIN_MINUTE}-{SNIPE_MAX_MINUTE}, >{SNIPE_THRESHOLD}% move')
    print(f'Entry zone: ${SNIPE_MIN_ENTRY}-${SNIPE_MAX_ENTRY}')
    print(f'ARB trigger: YES+NO < ${ARB_TARGET_COST}')
    print()

    markets = scan_15m_updown_markets()
    if not markets:
        print('No se encontraron mercados activos.')
        return

    now_ts = int(time.time())
    for m in markets:
        q = m.get('question', 'N/A')
        slug = m.get('_slug', '')
        window_end = m.get('_window_end', 0)
        remaining = window_end - now_ts
        elapsed_min = (now_ts - m.get('_window_start', now_ts)) / 60

        tokens = get_market_tokens(m)

        status = 'ACTIVE' if remaining > 0 else 'CLOSED'
        print(f'  [{m.get("_asset", "?")}] {q}')
        print(f'    {status} | {remaining//60}m {remaining%60}s left | Elapsed: {elapsed_min:.1f}min')

        if tokens:
            combined = tokens['up_mid'] + tokens['down_mid']
            arb_flag = 'ARB !!!' if combined < ARB_TARGET_COST else ''
            in_zone = SNIPE_MIN_ENTRY <= tokens['up_mid'] <= SNIPE_MAX_ENTRY or \
                      SNIPE_MIN_ENTRY <= tokens['down_mid'] <= SNIPE_MAX_ENTRY
            zone_flag = 'IN ZONE' if in_zone else ''
            print(f'    YES=${tokens["up_mid"]:.4f}  NO=${tokens["down_mid"]:.4f}  Sum=${combined:.4f}  {arb_flag} {zone_flag}')

            snipe = evaluate_snipe(m)
            if snipe:
                entry_price = tokens['up_mid'] if snipe['direction'] == 'UP' else tokens['down_mid']
                tradeable = SNIPE_MIN_ENTRY <= entry_price <= SNIPE_MAX_ENTRY
                print(f'    >>> SNIPE: {snipe["direction"]} | move={snipe["move_pct"]:+.3f}% | '
                      f'price=${entry_price:.4f} {"TRADEABLE" if tradeable else "out of zone"} | '
                      f'WR est: {snipe["est_win_rate"]:.0f}%')

            if combined < ARB_TARGET_COST:
                arb = evaluate_arb(m, tokens)
                if arb:
                    profit = ARB_SIZE * arb['profit_per_share']
                    print(f'    >>> ARB: profit=${profit:.4f} ({ARB_SIZE} shares)')
        print()


def cmd_resolve():
    """Forzar resolución de trades expirados."""
    print('Resolviendo trades expirados...')
    closed = resolve_expired_trades()
    stats = get_stats()
    print(f'Resuelto: {closed}')
    print(f'Stats: {stats}')


def cmd_stats():
    """Mostrar estadísticas del agente."""
    stats = get_stats()
    print(f'\n{"="*50}')
    print(f'POLYMARKET SNIPE — Estadísticas')
    print(f'{"="*50}')
    print(f'Trades totales:  {stats["total_trades"]}')
    print(f'Abiertos:        {stats["open"]}')
    print(f'Cerrados:        {stats["closed"]}')
    print(f'Wins:            {stats["wins"]} ({stats["win_rate_pct"]:.1f}%)')
    print(f'SNIPE trades:    {stats["snipe_trades"]}')
    print(f'ARB trades:      {stats["arb_trades"]}')
    print(f'P&L total:       ${stats["total_pnl"]:+.2f}')
    print(f'Balance actual:  ${stats["balance"]:.2f}')
    print(f'Modo:            {"PAPER" if DRY_RUN else "LIVE"}')
    print()


def main():
    init_db()
    session = ensure_session()
    logger.info('═' * 64)
    logger.info('POLYMARKET SNIPE AGENT — INICIANDO')
    logger.info(f'Session:       {session["session_name"]}')
    logger.info(f'Mode:          {"PAPER" if DRY_RUN else "LIVE"}')
    logger.info(f'Balance:       ${PAPER_BALANCE:.2f} USDC')
    logger.info(f'Assets:        {[a.upper() for a in ASSETS]}')
    logger.info(f'SNIPE:         min {SNIPE_MIN_MINUTE}-{SNIPE_MAX_MINUTE}, >{SNIPE_THRESHOLD}%')
    logger.info(f'ARB:           YES+NO < ${ARB_TARGET_COST}')
    logger.info(f'Max daily loss: ${MAX_DAILY_LOSS}')
    logger.info('═' * 64)

    send_telegram(
        f'🤖 <b>PolySnipe Agent iniciado</b>\n'
        f'Mode: PAPER | Balance: ${PAPER_BALANCE:.0f}\n'
        f'SNIPE: min {SNIPE_MIN_MINUTE}-{SNIPE_MAX_MINUTE}, >{SNIPE_THRESHOLD}% move\n'
        f'ARB: YES+NO < ${ARB_TARGET_COST}',
        silent=True,
    )

    cycle = 0
    last_report_cycle = 0
    REPORT_CYCLES = 20
    report_sent_today = False

    while True:
        try:
            cycle += 1

            # ── 1. Resolver trades expirados ──
            resolve_expired_trades()

            # ── 2. Daily loss check ──
            if daily_pnl() <= -MAX_DAILY_LOSS:
                logger.warning(f'Daily loss limit reached (${daily_pnl():.2f}). Pausando.')
                send_telegram(
                    f'⚠️ <b>PolySnipe DAILY LOSS LIMIT</b>\n'
                    f'P&L today: ${daily_pnl():.2f} (limit: ${MAX_DAILY_LOSS})\n'
                    f'Pausando nuevas entradas hasta mañana.',
                    silent=False,
                )
                time.sleep(300)
                continue

            # ── 3. Scan mercados ──
            markets = scan_15m_updown_markets()
            if not markets:
                time.sleep(SCAN_INTERVAL)
                continue

            for m in markets:
                # Limite de posiciones concurrentes
                if count_open() >= MAX_CONCURRENT:
                    break

                slug = m.get('_slug', '')
                tokens = get_market_tokens(m)
                if not tokens:
                    continue

                # ── ARB check ──
                arb = evaluate_arb(m, tokens)
                if arb and not slug_already_traded(slug):
                    open_arb_trade(m, arb, tokens)
                    continue

                # ── SNIPE check ──
                snipe = evaluate_snipe(m)
                if snipe and not slug_already_traded(slug):
                    entry_price = tokens['up_mid'] if snipe['direction'] == 'UP' else tokens['down_mid']
                    if check_price_in_entry_zone(entry_price):
                        open_snipe_trade(m, snipe, tokens)

            # ── 4. Reporte periódico ──
            if cycle - last_report_cycle >= REPORT_CYCLES:
                last_report_cycle = cycle
                stats = get_stats()
                logger.info(
                    f'Cycle {cycle} | Open={stats["open"]} | '
                    f'Wins={stats["wins"]}/{stats["closed"]} ({stats["win_rate_pct"]:.1f}%) | '
                    f'P&L=${stats["total_pnl"]:+.2f} | Bal=${stats["balance"]:.2f}'
                )
                # Reporte Telegram cada 4h
                now = datetime.now(timezone.utc)
                if now.hour % 4 == 0 and not report_sent_today:
                    send_telegram(
                        f'📊 <b>PolySnipe Report</b>\n'
                        f'Trades: {stats["total_trades"]} total | {stats["open"]} open\n'
                        f'SNIPE: {stats["snipe_trades"]} | ARB: {stats["arb_trades"]}\n'
                        f'Wins: {stats["wins"]}/{stats["closed"]} ({stats["win_rate_pct"]:.1f}%)\n'
                        f'P&L: ${stats["total_pnl"]:+.2f} | Bal: ${stats["balance"]:.2f}',
                        silent=True,
                    )
                    report_sent_today = True
                elif now.hour % 4 != 0:
                    report_sent_today = False

        except KeyboardInterrupt:
            logger.info('PolySnipe: Detenido por usuario')
            stats = get_stats()
            logger.info(f'FINAL | Trades={stats["total_trades"]} | P&L=${stats["total_pnl"]:.2f}')
            break
        except Exception as e:
            logger.error(f'Cycle {cycle} error: {e}', exc_info=True)

        time.sleep(SCAN_INTERVAL)


if __name__ == '__main__':
    if '--scan' in sys.argv:
        cmd_scan()
    elif '--stats' in sys.argv:
        cmd_stats()
    elif '--resolve' in sys.argv:
        cmd_resolve()
    else:
        main()
