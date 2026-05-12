#!/usr/bin/env python3
"""
pairs_executor.py — Entry point para Pairs Trading Bot.

Servicio systemd independiente. Opera pares cointegrados (GLD-SLV via Alpaca,
BTC-ETH via Kraken). Market-neutral: long una pierna, short la otra.

Paper trading únicamente. Los trades se registran en `trades` con strategy='PAIRS_TRADING'.
"""
import os
import sys
import json
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import yaml
from loguru import logger
from sqlalchemy import create_engine, text

sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')

from core.pairs_profiles import PAIRS_PROFILES, get_pairs_profile
from data.pairs_feed import PairsFeed
from strategies.pairs_trading import PairsTradingStrategy, PairsSignal, PairsPosition
from core.notifications import send_telegram

# ── Config ──
with open('/opt/trading/config/exchange_config.yaml') as f:
    CFG = yaml.safe_load(f).get('pairs_trading', {})

PAPER_TRADING = CFG.get('paper_trading', True)
INITIAL_BALANCE = CFG.get('initial_balance', 500.0)
CYCLE_SECONDS = 300  # 5 minutos
MAX_CONCURRENT = 2

ENABLED_PAIRS = [
    name for name, pcfg in CFG.get('pairs', {}).items()
]

logger.info(f'PairsExecutor: {len(ENABLED_PAIRS)} pares: {ENABLED_PAIRS}')

# ── DB ──
db_url = (
    f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
    f"@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}"
    f"/{os.getenv('POSTGRES_DB', 'trading_agent')}"
)
engine = create_engine(db_url)

feed = PairsFeed()
strategy = PairsTradingStrategy(CFG)

# ── Estado ──
open_positions: dict[str, PairsPosition] = {}


def _fetch_price(ticker: str, source: str = 'alpaca') -> Optional[float]:
    """Obtiene precio actual de un ticker."""
    import yfinance as yf
    try:
        t = yf.Ticker(ticker)
        df = t.history(period='2d')
        if not df.empty:
            return float(df['Close'].iloc[-1])
    except Exception:
        pass
    return None


def _save_trade(pos: PairsPosition, price_a: float, price_b: float):
    """Registra el cierre del par en la tabla trades."""
    with engine.connect() as conn:
        trade_uuid = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc)

        pnl_a = (price_a - pos.entry_price_a) * pos.size_a if pos.side_a == 'LONG' else (pos.entry_price_a - price_a) * pos.size_a
        pnl_b = (price_b - pos.entry_price_b) * pos.size_b * -1 if pos.side_a == 'LONG' else (pos.entry_price_b - price_b) * pos.size_b * -1
        total_pnl = pnl_a + pnl_b

        conn.execute(text("""
            INSERT INTO trades (trade_id, asset, side, strategy, entry_price, size,
                                exit_price, pnl, status, close_reason, paper_trade,
                                session_name, timestamp_open, timestamp_close)
            VALUES (:tid, :asset, :side, :strategy, :entry, :size,
                    :exit, :pnl, 'CLOSED', :reason, :paper,
                    :session, :topened, :tclosed)
        """), {
            'tid': trade_uuid,
            'asset': pos.pair,
            'side': pos.side_a,
            'strategy': 'PAIRS_TRADING',
            'entry': pos.entry_price_a,
            'size': pos.size_a,
            'exit': price_a,
            'pnl': round(total_pnl, 2),
            'reason': pos.close_reason,
            'paper': PAPER_TRADING,
            'session': 'PAIRS_SESSION_001',
            'topened': pos.entry_time,
            'tclosed': now.isoformat(),
        })
        conn.commit()

    emoji = '✅' if total_pnl > 0 else '❌'
    send_telegram(
        f'{emoji} <b>Pairs Closed</b>\n'
        f'Par: {pos.pair}\n'
        f'Side: {pos.side_a} A / OPP B\n'
        f'PnL: ${total_pnl:+,.2f}\n'
        f'Razón: {pos.close_reason}\n'
        f'<code>z_entry={pos.z_at_entry:.1f}</code>'
    )


def _open_pair(signal: PairsSignal):
    """Abre un nuevo par de trading."""
    profile = get_pairs_profile(signal.pair)
    price_a = _fetch_price(profile.asset_a, profile.source)
    price_b = _fetch_price(profile.asset_b, profile.source)

    if not price_a or not price_b:
        logger.warning(f'Pairs: no price for {signal.pair}')
        return

    capital = INITIAL_BALANCE * profile.max_capital_pct
    if signal.direction == 'LONG_A':
        side_a = 'LONG'
        size_a = capital / price_a
        size_b = capital / price_b  # short B mismo notional
    else:
        side_a = 'SHORT'
        size_a = capital / price_a
        size_b = capital / price_b

    pos = PairsPosition(
        pair=signal.pair,
        side_a=side_a,
        entry_price_a=price_a,
        entry_price_b=price_b,
        size_a=size_a,
        size_b=size_b,
        beta_at_entry=signal.beta or 1.0,
        z_at_entry=signal.z_score or 2.0,
        entry_time=datetime.now(timezone.utc).isoformat(),
    )

    open_positions[signal.pair] = pos

    send_telegram(
        f'🔗 <b>Pairs OPENED</b>\n'
        f'Par: {signal.pair}\n'
        f'{side_a} {profile.asset_a} + OPP {profile.asset_b}\n'
        f'z={signal.z_score:.1f} beta={signal.beta:.3f} hl={signal.half_life_days:.1f}d\n'
    )
    logger.info(f'Pairs opened: {signal.pair} {side_a} {profile.asset_a} z={signal.z_score}')


def run_cycle():
    """Un ciclo de evaluación de pares."""
    for pair_name in ENABLED_PAIRS:
        # Si ya tenemos posición en este par
        if pair_name in open_positions:
            pos = open_positions[pair_name]
            profile = get_pairs_profile(pair_name)
            result = feed.evaluate_pair(pair_name, profile)

            if result and result.get('z_score') is not None:
                z_now = result['z_score']
                entry_dt = datetime.fromisoformat(pos.entry_time)
                hold_days = (datetime.now(timezone.utc) - entry_dt).days

                close_it, reason = strategy.check_exit(pos, z_now, profile, hold_days)
                if close_it:
                    price_a = _fetch_price(profile.asset_a, profile.source)
                    price_b = _fetch_price(profile.asset_b, profile.source)
                    if price_a and price_b:
                        pos.close_reason = reason
                        _save_trade(pos, price_a, price_b)
                        del open_positions[pair_name]
                        logger.info(f'Pairs closed: {pair_name} reason={reason}')
            continue

        # Evaluar nueva entrada
        if len(open_positions) >= MAX_CONCURRENT:
            continue

        signal = strategy.evaluate(pair_name, INITIAL_BALANCE)
        if signal and signal.is_entry:
            _open_pair(signal)


def main():
    logger.info('Pairs Trading Agent starting...')
    send_telegram('🔗 <b>Pairs Trading Agent</b> iniciado\nPares: GLD-SLV, BTC-ETH\nPaper trading')

    while True:
        try:
            run_cycle()
        except Exception as e:
            logger.error(f'Pairs cycle error: {e}')

        time.sleep(CYCLE_SECONDS)


if __name__ == '__main__':
    main()
