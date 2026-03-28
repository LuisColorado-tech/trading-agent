"""
run_trading.py — Loop principal del Trading Agent.
Ejecutar: nohup python3 scripts/run_trading.py &
"""
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text

sys.path.insert(0, '/opt/trading')
load_dotenv('/opt/trading/config/.env')

logger.add(
    '/opt/trading/logs/trading_{time}.log',
    rotation='1 day',
    retention='30 days',
    level='INFO',
)

from agents.execution_agent import ExecutionAgent
from agents.market_scanner import MarketScanner
from agents.strategy_engine import StrategyEngine
from core.paper_session_manager import PaperSessionManager
from agents.trade_monitor import TradeMonitor
from core.portfolio_utils import build_portfolio_state
from data.market_feed import ASSET_MAP
from risk.risk_manager import PAPER_HALT_COOLDOWN_HOURS

SCAN_INTERVAL = 60  # segundos entre scans
PORTFOLIO_SNAPSHOT_INTERVAL = 5  # snapshot cada N ciclos (~5 min)
ASSETS = list(ASSET_MAP.keys())
TIMEFRAMES = ['15m', '1h']  # Empezar con TF conservadores

# DB engine for portfolio tracking
_db_url = (
    f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
    f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT', '5432')}"
    f"/{os.getenv('POSTGRES_DB')}"
)
_engine = create_engine(_db_url)
_session_manager = PaperSessionManager(_db_url)


def get_portfolio(session: dict) -> dict:
    """Obtiene el estado actual del portfolio desde DB o defaults."""
    session_start = session['started_at']
    with _engine.connect() as conn:
        row = conn.execute(
            text('SELECT * FROM portfolio WHERE timestamp >= :session_start ORDER BY timestamp DESC LIMIT 1'),
            {'session_start': session_start},
        ).fetchone()
        open_trades = conn.execute(
            text(
                "SELECT entry_price, stop_loss, position_size FROM trades "
                "WHERE status = 'OPEN' AND timestamp_open >= :session_start"
            ),
            {'session_start': session_start},
        ).fetchall()
        stats = conn.execute(
            text("""
                SELECT
                    COALESCE(MAX(GREATEST(total_balance, COALESCE(peak_balance, total_balance))), 0) AS historical_peak,
                    COALESCE(MAX(drawdown_pct), 0) AS historical_max_drawdown,
                    COALESCE(BOOL_OR(drawdown_pct >= 0.10), false) AS halt_triggered,
                    MAX(CASE WHEN drawdown_pct >= 0.10 THEN timestamp END) AS last_halt_breach_at
                FROM portfolio
                WHERE timestamp >= :session_start
            """)
            , {'session_start': session_start}
        ).fetchone()

    if row:
        balance = float(row.total_balance)
        latest_peak = float(row.peak_balance) if row.peak_balance is not None else None
        historical_peak = float(stats.historical_peak) if stats else None
        historical_max_drawdown = float(stats.historical_max_drawdown) if stats else 0.0
        halt_triggered = bool(stats.halt_triggered) if stats else False
        portfolio = build_portfolio_state(
            balance=balance,
            open_trades=[dict(t._mapping) for t in open_trades],
            latest_peak_balance=latest_peak,
            historical_peak_balance=historical_peak,
            historical_max_drawdown=historical_max_drawdown,
            halt_triggered=halt_triggered,
        )
        portfolio['last_halt_breach_at'] = stats.last_halt_breach_at if stats else None
        return portfolio
    return build_portfolio_state(
        balance=float(session.get('initial_balance', 10000.0)),
        open_trades=[],
        latest_peak_balance=float(session.get('initial_balance', 10000.0)),
        historical_peak_balance=float(session.get('initial_balance', 10000.0)),
    )


def get_open_trades(session: dict) -> list:
    """Obtiene trades abiertos desde DB."""
    with _engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT * FROM trades WHERE status = 'OPEN' "
                "AND timestamp_open >= :session_start ORDER BY timestamp_open"
            ),
            {'session_start': session['started_at']},
        ).fetchall()
    return [dict(r._mapping) for r in rows]


def save_portfolio_snapshot(portfolio: dict):
    """Guarda snapshot del portfolio."""
    with _engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO portfolio
                    (total_balance, available_cash, exposure_pct, pnl_day,
                     drawdown_pct, peak_balance, positions, timestamp)
                VALUES (:balance, :available_cash, :exposure, 0,
                        :drawdown, :peak_balance, :positions, NOW())
            """),
            {
                'balance': portfolio['total_balance'],
                'available_cash': portfolio['available_cash'],
                'exposure': portfolio['exposure_pct'],
                'drawdown': portfolio['drawdown_pct'],
                'peak_balance': portfolio.get('peak_balance', portfolio['total_balance']),
                'positions': json.dumps({}),
            },
        )


def maybe_rollover_failed_session(session: dict, portfolio: dict, executor: ExecutionAgent) -> tuple:
    if not executor.paper_mode:
        return session, portfolio, False
    if not portfolio.get('halt_triggered'):
        return session, portfolio, False

    open_trades = get_open_trades(session)
    if open_trades:
        return session, portfolio, False

    breach_at = portfolio.get('last_halt_breach_at')
    if breach_at is None:
        return session, portfolio, False
    if isinstance(breach_at, str):
        breach_at = datetime.fromisoformat(breach_at)
    if breach_at.tzinfo is None:
        breach_at = breach_at.replace(tzinfo=timezone.utc)

    if datetime.now(timezone.utc) - breach_at < timedelta(hours=PAPER_HALT_COOLDOWN_HOURS):
        return session, portfolio, False

    new_session = _session_manager.rollover_session(session['id'], status='FAILED', next_initial_balance=10000.0)
    executor.risk.resume_trading(manual_override=True)
    new_portfolio = get_portfolio(new_session)
    logger.warning(
        f'PAPER SESSION ROLLOVER: {session["session_name"]} -> FAILED | '
        f'new session {new_session["session_name"]}'
    )
    return new_session, new_portfolio, True


def main():
    session = _session_manager.ensure_active_session()
    scanner = MarketScanner()
    strategy = StrategyEngine()
    executor = ExecutionAgent()
    monitor = TradeMonitor()

    # Scope performance guard a la sesión activa
    strategy.guard.set_session_start(session['started_at'])

    portfolio = get_portfolio(session)
    logger.info(
        f'=== TRADING AGENT STARTED (PAPER MODE) === Session: {session["session_name"]} '
        f'Balance: ${portfolio["total_balance"]:,.2f}'
    )

    # Verificar halt persistente al arrancar (drawdown >= 10% sobrevive restarts)
    executor.risk.check_persistent_halt(portfolio)
    if executor.risk._trading_halted:
        logger.critical(f'TRADING HALTED at startup: {executor.risk._halt_reason}')

    # Save initial portfolio snapshot
    save_portfolio_snapshot(portfolio)

    # ── Startup warm-up ─────────────────────────────────────────────
    # Esperar 3 minutos antes del primer ciclo de trading.
    # Evita que señales acumuladas durante el reinicio disparen múltiples
    # entradas simultáneas sin contexto de mercado actualizado.
    import time as _time
    _warmup_sec = 180
    logger.info(f'Startup warm-up: {_warmup_sec}s antes del primer ciclo de trading...')
    _time.sleep(_warmup_sec)
    # ────────────────────────────────────────────────────────────────

    cycle_count = 0

    while True:
        try:
            cycle_count += 1

            # 0. MONITOREAR TRADES ABIERTOS — cerrar SL/TP
            closed_trades = monitor.check_open_trades(portfolio, session)
            if closed_trades:
                for ct in closed_trades:
                    logger.info(
                        f'Trade closed: {ct["asset"]} {ct["close_reason"]} '
                        f'PnL=${ct["pnl"]:+.2f} ({ct["pnl_pct"]:+.2f}%)'
                    )
                    # Registrar cooldown en TODOS los cierres (evita loop de reapertura)
                    executor.risk.register_close(
                        ct['asset'], ct.get('side', ''), reason=ct['close_reason']
                    )
                # Refresh portfolio after closing trades
                portfolio = get_portfolio(session)

            # 0b. Verificar halt persistente cada ciclo
            executor.risk.check_persistent_halt(portfolio)

            session, portfolio, rolled = maybe_rollover_failed_session(session, portfolio, executor)
            if rolled:
                cycle_count = 0
                strategy.guard.set_session_start(session['started_at'])
                logger.info(
                    f'=== NEW PAPER SESSION ACTIVE === {session["session_name"]} '
                    f'Balance: ${portfolio["total_balance"]:,.2f}'
                )
                continue

            # 1. Scan mercados
            signals = scanner.scan()
            logger.debug(f'Scan complete: {len(signals)} signals')

            # 2. Evaluar estrategias
            for asset in ASSETS:
                for tf in TIMEFRAMES:
                    result = strategy.evaluate(asset, tf, portfolio)
                    if result.get('opportunity'):
                        signal = result['signal']
                        logger.info(
                            f'Opportunity: {asset}/{tf} {signal["direction"]} '
                            f'score={signal["score"]}'
                        )

                        # 3. Obtener trades abiertos
                        open_trades = get_open_trades(session)

                        # 4. Ejecutar (Risk Manager decide)
                        exec_result = executor.execute(signal, portfolio, open_trades)
                        if exec_result.get('executed'):
                            logger.info(f'Executed trade: {exec_result["trade_id"]}')
                            # Registrar trade de probation si aplica
                            if signal.get('on_probation'):
                                strategy.guard.record_probation_trade(signal['strategy'])

            # Refresh portfolio
            portfolio = get_portfolio(session)

            # Periodic portfolio snapshot
            if cycle_count % PORTFOLIO_SNAPSHOT_INTERVAL == 0:
                save_portfolio_snapshot(portfolio)
                logger.debug(f'Portfolio snapshot saved (cycle {cycle_count})')

            logger.info(f'Cycle {cycle_count} complete. Next scan in {SCAN_INTERVAL}s. '
                        f'Balance: ${portfolio["total_balance"]:,.2f}')
            time.sleep(SCAN_INTERVAL)

        except KeyboardInterrupt:
            logger.info('Trading loop stopped by user')
            break
        except Exception as e:
            logger.error(f'Main loop error: {e}')
            time.sleep(10)


if __name__ == '__main__':
    main()
