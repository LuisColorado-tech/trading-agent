"""
run_polymarket.py — Loop principal del agente Polymarket.

Pipeline INDEPENDIENTE del trading cripto.
Ejecutar: nohup python3 scripts/run_polymarket.py &
"""
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text

sys.path.insert(0, '/opt/trading')
load_dotenv('/opt/trading/config/.env')

import yaml

with open('/opt/trading/config/exchange_config.yaml') as f:
    _CFG = yaml.safe_load(f).get('polymarket', {})

logger.add(
    '/opt/trading/logs/polymarket_{time}.log',
    rotation='1 day',
    retention='30 days',
    level='INFO',
)

from agents.poly_executor import PolyExecutor
from agents.poly_monitor import PolyMonitor
from core.notifications import send_telegram
from core.poly_session_manager import PolySessionManager
from data.polymarket_feed import PolymarketFeed
from risk.poly_risk import PolyRiskManager
from strategies.prediction import PredictionStrategy

SCAN_INTERVAL = _CFG.get('scan_interval_seconds', 300)
INITIAL_BALANCE = _CFG.get('initial_paper_balance', 1000.0)
MAX_DD_PCT = _CFG.get('risk', {}).get('max_session_drawdown_pct', 50.0)

_db_url = (
    f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
    f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT', '5432')}"
    f"/{os.getenv('POSTGRES_DB')}"
)
_engine = create_engine(_db_url)
_session_mgr = PolySessionManager(_db_url)


def get_session_balance(session_name: str) -> float:
    """Obtiene balance actual de la sesión."""
    with _engine.connect() as conn:
        row = conn.execute(
            text("SELECT current_balance FROM poly_sessions WHERE session_name = :s"),
            {'s': session_name},
        ).fetchone()
    return float(row[0]) if row else 0.0


def get_open_positions(session_name: str) -> list[dict]:
    """Obtiene posiciones abiertas de la sesión."""
    with _engine.connect() as conn:
        rows = conn.execute(
            text('''
                SELECT id, condition_id, question, side, strategy,
                       entry_price, shares, cost_basis, session_name
                FROM poly_positions
                WHERE status = 'OPEN' AND session_name = :s
            '''),
            {'s': session_name},
        ).fetchall()
    return [dict(r._mapping) for r in rows]


def get_traded_condition_ids(session_name: str) -> set[str]:
    """Obtiene todos los condition_ids ya operados (OPEN + CLOSED) en la sesión."""
    with _engine.connect() as conn:
        rows = conn.execute(
            text('SELECT DISTINCT condition_id FROM poly_positions WHERE session_name = :s'),
            {'s': session_name},
        ).fetchall()
    return {r[0] for r in rows}


def update_balance_after_execution(session_name: str, cost: float):
    """Resta el costo de una posición del balance (reserva capital)."""
    with _engine.connect() as conn:
        conn.execute(
            text('''
                UPDATE poly_sessions
                SET current_balance = current_balance - :cost
                WHERE session_name = :s AND status = 'ACTIVE'
            '''),
            {'cost': cost, 's': session_name},
        )
        conn.commit()


def maybe_rollover(session: dict) -> tuple[dict, bool]:
    """Verifica drawdown y hace rollover si excede el límite.

    Solo hace rollover si no hay posiciones abiertas.
    Returns:
        (session, rolled_over)
    """
    dd_check = _session_mgr.check_drawdown_halt(str(session['id']), max_dd_pct=MAX_DD_PCT)
    if not dd_check['halt']:
        return session, False

    open_count = _session_mgr._count_open_positions(str(session['id']))
    if open_count > 0:
        logger.warning(
            f'POLY DD HALT: {dd_check["current_dd"]:.1f}% >= {MAX_DD_PCT:.0f}% '
            f'pero aún hay {open_count} posiciones abiertas. Esperando cierre.'
        )
        return session, False

    logger.critical(
        f'POLY ROLLOVER: DD {dd_check["current_dd"]:.1f}% >= {MAX_DD_PCT:.0f}% | '
        f'Balance ${dd_check["balance"]:.2f} (peak ${dd_check["peak"]:.2f})'
    )
    send_telegram(
        f'⛔ <b>POLY SESSION ROLLOVER</b>\n'
        f'📉 DD: {dd_check["current_dd"]:.1f}% (límite {MAX_DD_PCT:.0f}%)\n'
        f'💰 Balance: ${dd_check["balance"]:.2f} (peak ${dd_check["peak"]:.2f})\n'
        f'Session {session["session_name"]} → FAILED\n'
        f'Creando nueva sesión con ${INITIAL_BALANCE:.0f}...',
    )

    new_session = _session_mgr.rollover_session(
        str(session['id']),
        status='FAILED',
        next_initial_balance=INITIAL_BALANCE,
    )
    return new_session, True


def main():
    if not _CFG.get('enabled', False):
        logger.warning('Polymarket is DISABLED in config. Exiting.')
        return

    feed = PolymarketFeed()
    strategy = PredictionStrategy()
    risk = PolyRiskManager()
    executor = PolyExecutor()
    monitor = PolyMonitor(feed)

    session = _session_mgr.ensure_active_session(initial_balance=INITIAL_BALANCE)
    logger.info(
        f'=== POLYMARKET AGENT STARTED (PAPER) === '
        f'Session: {session["session_name"]} '
        f'Balance: ${session["current_balance"]:.2f}'
    )

    cycle_count = 0

    while True:
        try:
            cycle_count += 1
            session_name = session['session_name']

            # ── CHECK ROLLOVER POR DRAWDOWN ──
            session, rolled = maybe_rollover(session)
            if rolled:
                logger.info(f'Rolled over to {session["session_name"]}')
                continue  # restart cycle with new session

            # ── 0. MONITOREAR posiciones abiertas ──
            closed = monitor.check_positions()
            if closed:
                for c in closed:
                    logger.info(
                        f'Position closed: {c["close_reason"]} '
                        f'PnL=${c["pnl"]:+.2f} ({c["pnl_pct"]:+.1f}%)'
                    )
                    emoji = '✅' if c['pnl'] > 0 else '❌'
                    send_telegram(
                        f'{emoji} <b>POLY CLOSE</b> [{c["close_reason"]}]\n'
                        f'PnL: <b>${c["pnl"]:+.2f}</b> ({c["pnl_pct"]:+.1f}%)',
                        silent=False,
                    )

            # ── 1. SCAN mercados ──
            markets = feed.scan_markets()
            if markets:
                saved = feed.save_markets(markets)
                logger.info(f'Cycle {cycle_count}: Scanned {len(markets)} markets, saved {saved}')

            # ── 2. DETECTAR resoluciones ──
            resolved = feed.check_resolutions()
            if resolved:
                logger.info(f'Resolved {len(resolved)} markets')

            # ── 3. EVALUAR oportunidades ──
            balance = get_session_balance(session_name)
            open_positions = get_open_positions(session_name)
            already_traded = get_traded_condition_ids(session_name)

            # Limitar a top 15 por volumen para no saturar LLM
            db_markets = feed.get_active_markets_from_db()[:15]
            evaluated = 0
            executed = 0

            for market in db_markets:
                # No re-entrar en mercados ya operados (abiertos O cerrados)
                if market['condition_id'] in already_traded:
                    continue

                try:
                    opportunity = strategy.evaluate(market)
                except Exception as e:
                    logger.debug(f'Strategy eval error: {e}')
                    continue

                evaluated += 1

                if not opportunity or not opportunity.get('opportunity'):
                    continue

                # ── 4. RISK CHECK ──
                signal = {
                    'side': opportunity['side'],
                    'edge': opportunity['edge'],
                    'entry_price': opportunity['entry_price'],
                    'estimated_prob': opportunity['estimated_prob'],
                    'confidence': opportunity['confidence'],
                    'market': market,
                    'strategy': opportunity.get('strategy', 'PREDICTION_LLM'),
                    'reasoning': opportunity.get('reasoning', ''),
                    'key_factors': opportunity.get('key_factors', []),
                }

                risk_decision = risk.evaluate(signal, balance, open_positions)

                if not risk_decision.approved:
                    logger.debug(f'Risk rejected: {risk_decision.reason}')
                    continue

                # ── 5. EJECUTAR ──
                result = executor.execute(signal, risk_decision, session_name)

                if result.get('executed'):
                    update_balance_after_execution(session_name, result['cost'])
                    balance -= result['cost']
                    open_positions.append({
                        'condition_id': market['condition_id'],
                        'cost_basis': result['cost'],
                    })
                    executed += 1
                    q = market['question'][:60]
                    logger.info(
                        f'POLY TRADE: {opportunity["side"]} '
                        f'"{q}" '
                        f'edge={opportunity["edge"]:+.1%} cost=${result["cost"]:.2f}'
                    )
                    send_telegram(
                        f'🎯 <b>POLY TRADE</b> {opportunity["side"]}\n'
                        f'📋 {q}\n'
                        f'Edge: <b>{opportunity["edge"]:+.1%}</b> | '
                        f'Cost: ${result["cost"]:.2f} | '
                        f'Shares: {result["shares"]:.0f}',
                        silent=True,
                    )

            # ── Resumen del ciclo ──
            summary = monitor.get_portfolio_summary()
            logger.info(
                f'Cycle {cycle_count} complete | '
                f'Evaluated: {evaluated} | Executed: {executed} | '
                f'Open: {summary["open_positions"]} | '
                f'Exposure: ${summary["total_exposure"]:.2f} | '
                f'Balance: ${balance:.2f} | '
                f'PnL: ${summary["total_pnl"]:+.2f} | '
                f'Next scan in {SCAN_INTERVAL}s'
            )

            time.sleep(SCAN_INTERVAL)

        except KeyboardInterrupt:
            logger.info('Polymarket agent stopped by user')
            break
        except Exception as e:
            logger.error(f'Polymarket main loop error: {e}', exc_info=True)
            time.sleep(30)


if __name__ == '__main__':
    main()
