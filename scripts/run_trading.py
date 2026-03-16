"""
run_trading.py — Loop principal del Trading Agent.
Ejecutar: nohup python3 scripts/run_trading.py &
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

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
from agents.trade_monitor import TradeMonitor
from data.market_feed import ASSET_MAP

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


def get_portfolio() -> dict:
    """Obtiene el estado actual del portfolio desde DB o defaults."""
    with _engine.connect() as conn:
        row = conn.execute(
            text('SELECT * FROM portfolio ORDER BY timestamp DESC LIMIT 1')
        ).fetchone()

        # Calcular exposición real basada en trades abiertos
        open_trades = conn.execute(
            text("SELECT entry_price, position_size FROM trades WHERE status = 'OPEN'")
        ).fetchall()
        total_exposure = sum(
            float(t.entry_price) * float(t.position_size) for t in open_trades
        )

    if row:
        balance = float(row.total_balance)
        peak = max(float(row.peak_balance), balance) if row.peak_balance else balance
        exposure_pct = total_exposure / balance if balance > 0 else 0
        drawdown = (peak - balance) / peak if peak > 0 else 0
        return {
            'total_balance': balance,
            'available_cash': balance - total_exposure,
            'exposure_pct': exposure_pct,
            'drawdown_pct': drawdown,
            'peak_balance': peak,
        }
    return {
        'total_balance': 10000.0,
        'available_cash': 10000.0,
        'exposure_pct': 0.0,
        'drawdown_pct': 0.0,
        'peak_balance': 10000.0,
    }


def get_open_trades() -> list:
    """Obtiene trades abiertos desde DB."""
    with _engine.connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM trades WHERE status = 'OPEN' ORDER BY timestamp_open")
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


def main():
    scanner = MarketScanner()
    strategy = StrategyEngine()
    executor = ExecutionAgent()
    monitor = TradeMonitor()

    portfolio = get_portfolio()
    logger.info(f'=== TRADING AGENT STARTED (PAPER MODE) === Balance: ${portfolio["total_balance"]:,.2f}')

    # Save initial portfolio snapshot
    save_portfolio_snapshot(portfolio)

    cycle_count = 0

    while True:
        try:
            cycle_count += 1

            # 0. MONITOREAR TRADES ABIERTOS — cerrar SL/TP
            closed_trades = monitor.check_open_trades(portfolio)
            if closed_trades:
                for ct in closed_trades:
                    logger.info(
                        f'Trade closed: {ct["asset"]} {ct["close_reason"]} '
                        f'PnL=${ct["pnl"]:+.2f} ({ct["pnl_pct"]:+.2f}%)'
                    )
                # Refresh portfolio after closing trades
                portfolio = get_portfolio()

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
                        open_trades = get_open_trades()

                        # 4. Ejecutar (Risk Manager decide)
                        exec_result = executor.execute(signal, portfolio, open_trades)
                        if exec_result.get('executed'):
                            logger.info(f'Executed trade: {exec_result["trade_id"]}')

            # Refresh portfolio
            portfolio = get_portfolio()

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
