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
from data.market_feed import ASSET_MAP

SCAN_INTERVAL = 60  # segundos entre scans
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
    if row:
        return {
            'total_balance': float(row.total_balance),
            'available_cash': float(row.total_balance) * (1 - float(row.exposure_pct)),
            'exposure_pct': float(row.exposure_pct),
            'drawdown_pct': float(row.drawdown_pct),
            'peak_balance': float(row.total_balance),
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
                    (total_balance, exposure_pct, pnl_day, drawdown_pct, positions)
                VALUES (:balance, :exposure, 0, :drawdown, :positions)
            """),
            {
                'balance': portfolio['total_balance'],
                'exposure': portfolio['exposure_pct'],
                'drawdown': portfolio['drawdown_pct'],
                'positions': json.dumps({}),
            },
        )


def main():
    scanner = MarketScanner()
    strategy = StrategyEngine()
    executor = ExecutionAgent()

    portfolio = get_portfolio()
    logger.info(f'=== TRADING AGENT STARTED (PAPER MODE) === Balance: ${portfolio["total_balance"]:,.2f}')

    # Save initial portfolio snapshot
    save_portfolio_snapshot(portfolio)

    while True:
        try:
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

            logger.info(f'Cycle complete. Next scan in {SCAN_INTERVAL}s. '
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
