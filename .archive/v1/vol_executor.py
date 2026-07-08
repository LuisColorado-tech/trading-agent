#!/usr/bin/env python3
"""
VolExecutor — Ejecutor de VIX Mean Reversion.

Monitorea VIX spot + percentil + contango cada hora.
Entra long SVXY cuando VIX > percentil 80 y contango favorable.
Paper trading en Alpaca.

La estrategia vende volatilidad: long SVXY (inverso de VIX) cuando hay pánico.
"""
import os
import sys
import time
import uuid
import traceback
from datetime import datetime, timezone

import yaml
from loguru import logger
from sqlalchemy import create_engine, text

sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')

from data.vol_feed import VolFeed
from core.vol_profiles import get_vol_profile
from strategies.vol_mean_reversion import VolMeanReversionStrategy, VolPosition
from core.notifications import send_telegram

with open('/opt/trading/config/exchange_config.yaml') as f:
    CFG = yaml.safe_load(f).get('vol_mean_reversion', {})

PAPER_TRADING = True
INITIAL_BALANCE = CFG.get('initial_balance', 500.0)
CHECK_INTERVAL = CFG.get('monitor_interval_minutes', 60) * 60

db_url = (
    f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
    f"@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}"
    f"/{os.getenv('POSTGRES_DB', 'trading_agent')}"
)
engine = create_engine(db_url)

feed = VolFeed()
strategy = VolMeanReversionStrategy(CFG)
open_position: VolPosition | None = None


def _save_trade(ticker: str, entry_price: float, exit_price: float, pnl: float,
                reason: str, size: float):
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO trades (asset, side, strategy, entry_price, exit_price,
                position_size, pnl, status, close_reason, paper_trade,
                timestamp_open, timestamp_close, session_name)
            VALUES (:a, 'LONG', 'VOL_MEAN_REVERSION', :ep, :xp,
                :sz, :pnl, 'CLOSED', :reason, :paper,
                NOW() - INTERVAL '1 day', NOW(), 'VOL_SESSION_001')
        """), {
            'a': ticker, 'ep': entry_price, 'xp': exit_price,
            'sz': size, 'pnl': round(pnl, 2), 'reason': reason,
            'paper': PAPER_TRADING,
        })
        conn.commit()


def run_cycle():
    global open_position

    ticker = 'SVXY'
    signal = strategy.evaluate(ticker)
    if signal is None:
        return

    price = feed.get_product_price(ticker)
    if price is None:
        return

    # Monitor open position
    if open_position is not None:
        profile = get_vol_profile(ticker)
        vix_pct = feed.get_vix_percentile()
        hold_days = (datetime.now(timezone.utc) - datetime.fromisoformat(open_position.entry_time)).days

        close_sl_tp, sl_tp_reason = strategy.check_sl_tp(open_position, price)
        close_exit, exit_reason = strategy.should_close(
            open_position, price, vix_pct, hold_days)

        if close_sl_tp or close_exit:
            reason = sl_tp_reason if close_sl_tp else exit_reason
            pnl = (price - open_position.entry_price) * open_position.size
            _save_trade(ticker, open_position.entry_price, price, pnl, reason, open_position.size)
            emoji = '✅' if pnl > 0 else ('⚠️' if pnl == 0 else '❌')
            send_telegram(
                f'{emoji} <b>VIX CLOSED</b> {ticker}\n'
                f'Entry: ${open_position.entry_price:.2f} → Exit: ${price:.2f}\n'
                f'P&L: <b>${pnl:+.2f}</b> | {reason}'
            )
            logger.info(f'VIX closed: {ticker} PnL=${pnl:+.2f} reason={reason}')
            open_position = None
        return

    # Check entry
    if not signal.is_entry:
        return

    profile = get_vol_profile(ticker)
    size = strategy.calculate_position_size(INITIAL_BALANCE, price)

    open_position = VolPosition(
        ticker=ticker,
        entry_price=price,
        size=size,
        entry_time=datetime.now(timezone.utc).isoformat(),
        vix_at_entry=signal.vix_spot,
    )

    vix_str = f'{signal.vix_spot:.1f}' if signal.vix_spot is not None else 'N/A'
    pct_str = f'{signal.vix_percentile:.0f}' if signal.vix_percentile is not None else 'N/A'
    cg_str = f'{signal.contango_annual:.1f}' if signal.contango_annual is not None else 'N/A'
    send_telegram(
        f'📉 <b>VIX ENTRY</b> {ticker}\n'
        f'VIX: {vix_str} (p{pct_str})\n'
        f'Entry: ${price:.2f} | Size: {size:.2f} shares\n'
        f'Contango: {cg_str}%/yr\n'
        f'<code>{signal.reason}</code>'
    )
    logger.info(f'VIX ENTRY: {ticker} @ ${price:.2f} VIX={signal.vix_spot}')


def main():
    logger.info('VIX Mean Reversion Agent starting...')
    send_telegram('📉 <b>VIX Mean Reversion Agent</b> iniciado\nMonitoreando SVXY · VIX percentil 80+')

    while True:
        try:
            run_cycle()
        except Exception:
            logger.error(f'VIX cycle error:\n{traceback.format_exc()}')
        time.sleep(CHECK_INTERVAL)


if __name__ == '__main__':
    main()
