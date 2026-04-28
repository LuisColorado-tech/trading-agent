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
from core.poly_strategy_hub import PolyStrategyHub
from data.polymarket_feed import PolymarketFeed
from risk.poly_risk import PolyRiskManager
from strategies.signal_based_poly import SignalBasedPolyStrategy

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
    hub = PolyStrategyHub()          # Hub multi-estrategia (incluye SignalBasedPolyStrategy)
    strategy = hub.get_strategy('signal_based') or SignalBasedPolyStrategy()  # fallback
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

            # Obtener régimen de mercado actual
            market_regime = 'UNKNOWN'
            try:
                from sqlalchemy import text as _text
                with _engine.connect() as _conn:
                    try:
                        _row = _conn.execute(_text(
                            "SELECT regime FROM market_snapshots ORDER BY timestamp DESC LIMIT 1"
                        )).fetchone()
                        if _row:
                            market_regime = str(_row[0])
                    except Exception:
                        _rows = _conn.execute(_text("""
                            SELECT direction FROM signals
                            WHERE asset = 'BTC'
                              AND timestamp > now() - interval '30 minutes'
                            ORDER BY timestamp DESC LIMIT 6
                        """)).fetchall()
                        if _rows:
                            _dirs = [r[0] for r in _rows]
                            _buys = _dirs.count('BUY')
                            _sells = _dirs.count('SELL')
                            if _buys >= 4:
                                market_regime = 'TREND_UP'
                            elif _sells >= 4:
                                market_regime = 'TREND_DOWN'
                            else:
                                market_regime = 'RANGE'
            except Exception:
                pass

            # ── Mercados principales (top 20 por volumen) ──
            db_markets = feed.get_active_markets_from_db()[:20]

            # ── Mercados especiales para estrategias adicionales ──
            tail_end_markets = []
            late_entry_markets = []
            try:
                tail_end_markets = feed.scan_tail_end_markets()
            except Exception as e:
                logger.debug(f'Tail-end scan error: {e}')
            try:
                late_entry_markets = feed.scan_15min_markets()
            except Exception as e:
                logger.debug(f'15min scan error: {e}')

            # ── Hub: evaluar todas las estrategias ──
            all_signals = hub.evaluate_all(
                markets=db_markets,
                market_regime=market_regime,
                already_traded=already_traded,
                tail_end_markets=tail_end_markets,
                late_entry_markets=late_entry_markets,
            )

            evaluated = len(all_signals)
            executed = 0

            for opportunity in all_signals:
                market = opportunity.get('market', {})
                cid = market.get('condition_id', '')

                # Verificar de nuevo (el hub puede haber generado señales en paralelo)
                if cid in already_traded:
                    continue

                # ── 4. RISK CHECK ──
                signal = {
                    'side': opportunity['side'],
                    'edge': opportunity['edge'],
                    'entry_price': opportunity['entry_price'],
                    'estimated_prob': opportunity.get('estimated_prob', 0.5),
                    'confidence': opportunity.get('confidence', 80),
                    'market': market,
                    'strategy': opportunity.get('strategy', 'signal_based'),
                    'reasoning': opportunity.get('reasoning', ''),
                    'btc_direction': opportunity.get('btc_direction', ''),
                    'btc_momentum_pct': opportunity.get('btc_momentum_pct', 0.0),
                    'market_regime': opportunity.get('market_regime', ''),
                    'event_type': opportunity.get('event_type', ''),
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
                        'condition_id': cid,
                        'cost_basis': result['cost'],
                    })
                    already_traded.add(cid)
                    executed += 1
                    q = market.get('question', '')[:60]
                    strat_tag = opportunity.get('strategy', 'unknown')
                    logger.info(
                        f'POLY TRADE [{strat_tag}]: {opportunity["side"]} '
                        f'"{q}" '
                        f'edge={opportunity["edge"]:+.1%} cost=${result["cost"]:.2f}'
                    )
                    send_telegram(
                        f'🎯 <b>POLY TRADE</b> [{strat_tag}] {opportunity["side"]}\n'
                        f'📋 {q}\n'
                        f'Edge: <b>{opportunity["edge"]:+.1%}</b> | '
                        f'Cost: ${result["cost"]:.2f} | '
                        f'Shares: {result["shares"]:.0f}',
                        silent=True,
                    )

                    # Registrar en stats por estrategia
                    try:
                        hub.record_execution(strat_tag, session.get('id', 0))
                    except Exception:
                        pass

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
