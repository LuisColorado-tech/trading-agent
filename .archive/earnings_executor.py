#!/usr/bin/env python3
"""
EarningsExecutor — Ejecutor de la estrategia Earnings Strangle.

Monitorea calendario de earnings, compra strangles (call + put OTM)
1 dia antes del evento, y cierra 1 dia despues.

Paper trading en Alpaca Options unicamente.
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

from data.earnings_calendar import EarningsCalendar, EarningsEvent
from data.options_chain_feed import OptionsChainFeed, StrangleQuote
from core.earnings_profiles import EARNINGS_PROFILES, get_earnings_profile
from strategies.earnings_strangle import (
    EarningsStrangleStrategy, EarningsStrangleSignal,
    StranglePosition, StrangleState,
)
from core.notifications import send_telegram

with open('/opt/trading/config/exchange_config.yaml') as f:
    CFG = yaml.safe_load(f).get('earnings_strangle', {})

PAPER_TRADING = CFG.get('paper_trading', True)
INITIAL_BALANCE = CFG.get('initial_balance', 1000.0)
CYCLE_SECONDS = CFG.get('cycle_seconds', 3600)
ENABLED = CFG.get('enabled', True)
MAX_CONCURRENT = CFG.get('max_concurrent_trades', 3)
ASSETS = CFG.get('assets', ['NVDA', 'TSLA', 'AAPL', 'META', 'AMZN'])

db_url = (
    f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
    f"@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}"
    f"/{os.getenv('POSTGRES_DB', 'trading_agent')}"
)
engine = create_engine(db_url)

calendar = EarningsCalendar(min_market_cap=CFG.get('min_market_cap', 100e9))
options_feed = OptionsChainFeed(paper=True)
strategy = EarningsStrangleStrategy(CFG)
open_positions: dict[str, StranglePosition] = {}

logger.info(f'EarningsExecutor: {len(ASSETS)} activos: {ASSETS} '
            f'balance=${INITIAL_BALANCE:.0f} paper={PAPER_TRADING}')


def _ensure_table():
    sql = """
        CREATE TABLE IF NOT EXISTS earnings_trades (
            id TEXT PRIMARY KEY,
            ticker TEXT NOT NULL,
            stock_price_entry REAL,
            strike_call REAL,
            strike_put REAL,
            call_cost REAL,
            put_cost REAL,
            total_cost REAL,
            capital_used REAL,
            call_otm_pct REAL,
            put_otm_pct REAL,
            iv_rank_entry REAL,
            earnings_date TEXT,
            status TEXT DEFAULT 'OPEN',
            close_price REAL,
            call_exit REAL,
            put_exit REAL,
            pnl REAL DEFAULT 0,
            pnl_pct REAL DEFAULT 0,
            close_reason TEXT,
            entry_time TEXT,
            close_time TEXT,
            metadata JSONB
        )
    """
    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()
    logger.info('earnings_trades table ready')


def count_open() -> int:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT COUNT(*) FROM earnings_trades WHERE status='OPEN'")
        ).scalar() or 0


def get_open_positions() -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM earnings_trades WHERE status='OPEN'")
        ).fetchall()
    return [dict(r._mapping) for r in rows]


def open_strangle(signal: EarningsStrangleSignal, capital: float) -> Optional[str]:
    n = count_open()
    if n >= MAX_CONCURRENT:
        logger.debug(f"Max concurrent reached ({n}/{MAX_CONCURRENT})")
        return None

    profile = get_earnings_profile(signal.ticker)
    contracts = strategy.calculate_position_size(
        capital, signal.stock_price, signal.total_cost)

    trade_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    meta = json.dumps({
        'earnings_date': signal.earnings_date.isoformat(),
        'iv_rank': signal.iv_rank,
        'cost_as_pct': round(signal.cost_as_pct, 4),
        'breakeven_up': round(signal.breakeven_up, 2),
        'breakeven_down': round(signal.breakeven_down, 2),
        'contracts': contracts,
    })

    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO earnings_trades
                (id, ticker, stock_price_entry, strike_call, strike_put,
                 call_cost, put_cost, total_cost, capital_used,
                 call_otm_pct, put_otm_pct, iv_rank_entry,
                 earnings_date, status, entry_time, metadata)
            VALUES (:id, :ticker, :sp, :sc, :spu,
                    :cc, :pc, :tc, :cu,
                    :cop, :pop, :iv,
                    :ed, 'OPEN', :now, CAST(:meta AS jsonb))
        """), {
            'id': trade_id, 'ticker': signal.ticker,
            'sp': signal.stock_price, 'sc': signal.strike_call,
            'spu': signal.strike_put, 'cc': signal.call_price,
            'pc': signal.put_price, 'tc': signal.total_cost,
            'cu': signal.total_cost * 100 * contracts,
            'cop': round(signal.call_otm_pct, 4),
            'pop': round(signal.put_otm_pct, 4),
            'iv': round(signal.iv_rank, 1),
            'ed': signal.earnings_date.isoformat(),
            'now': now, 'meta': meta,
        })

    logger.info(
        f"EARNINGS STRANGLE OPEN: {signal.ticker} "
        f"stock=${signal.stock_price:.2f} "
        f"call={signal.strike_call}@{signal.call_price:.2f} "
        f"put={signal.strike_put}@{signal.put_price:.2f} "
        f"cost=${signal.total_cost:.2f}/share "
        f"IVrank={signal.iv_rank:.0f}%")

    return trade_id


def close_strangle(trade: dict, reason: str, close_price: float,
                   call_exit: float = 0, put_exit: float = 0):
    if trade['status'] != 'OPEN':
        return

    total_cost = float(trade['total_cost'])
    current_value = call_exit + put_exit if (call_exit + put_exit) > 0 else 0
    pnl = (current_value - total_cost) * 100
    pnl_pct = (pnl / (total_cost * 100)) * 100 if total_cost else 0
    now = datetime.now(timezone.utc).isoformat()

    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE earnings_trades SET
                status='CLOSED', close_price=:cp, close_time=:now,
                call_exit=:ce, put_exit=:pe,
                pnl=:pnl, pnl_pct=:ppct, close_reason=:reason
            WHERE id=:id
        """), {
            'id': trade['id'], 'cp': close_price,
            'now': now, 'ce': call_exit, 'pe': put_exit,
            'pnl': round(pnl, 2), 'ppct': round(pnl_pct, 1),
            'reason': reason,
        })

    logger.info(
        f"EARNINGS STRANGLE CLOSE: {trade['ticker']} {reason} "
        f"PnL=${pnl:+.2f} ({pnl_pct:+.1f}%)")


def scan_earnings_entries():
    now = datetime.now(timezone.utc)
    upcoming = calendar.get_upcoming_earnings(ASSETS)

    for event in upcoming:
        if count_open() >= MAX_CONCURRENT:
            break

        days_away = (event.earnings_date - now).days
        if days_away != strategy.days_before:
            continue

        # Check if already entered
        with engine.connect() as conn:
            existing = conn.execute(
                text("SELECT COUNT(*) FROM earnings_trades WHERE ticker=:t AND status='OPEN'"),
                {'t': event.ticker}
            ).scalar()
        if existing:
            continue

        profile = get_earnings_profile(event.ticker)
        otm = profile.otm_pct_call
        stock_price = options_feed._get_stock_price(event.ticker)
        if not stock_price:
            continue

        iv_rank = options_feed.get_iv_rank(event.ticker)

        quote = options_feed.find_otm_strangle(
            event.ticker, target_otm_pct=otm, max_dte=profile.target_dte + 7)
        if not quote:
            # Estimate from IV
            est_cost = options_feed.estimate_strangle_cost(
                event.ticker, otm, profile.target_dte)
            if est_cost <= 0:
                continue
            strike_call = round(stock_price * (1 + otm), 2)
            strike_put = round(stock_price * (1 - otm), 2)
            call_price = put_price = est_cost / 2

            signal = strategy.evaluate(
                event.ticker, stock_price, event.earnings_date,
                iv_rank, strike_call, call_price,
                strike_put, put_price)
        else:
            signal = strategy.evaluate(
                event.ticker, stock_price, event.earnings_date,
                iv_rank, quote.call.strike, quote.call.mid_price,
                quote.put.strike, quote.put.mid_price)

        if signal and signal.is_valid:
            open_strangle(signal, INITIAL_BALANCE)
            send_telegram(
                f"EARNINGS: <b>{signal.ticker}</b> strangle abierto\n"
                f"Stock=${signal.stock_price:.2f} "
                f"Call={signal.strike_call} Put={signal.strike_put}\n"
                f"Cost=${signal.total_cost:.2f}/share "
                f"IVrank={signal.iv_rank:.0f}%\n"
                f"Earnings en {days_away}d",
                silent=True,
            )


def monitor_positions():
    positions = get_open_positions()
    for pos in positions:
        earnings_date_str = pos.get('earnings_date', '')
        earnings_passed = False
        if earnings_date_str:
            try:
                if isinstance(earnings_date_str, str):
                    ed = datetime.fromisoformat(earnings_date_str.replace('Z', '+00:00'))
                elif isinstance(earnings_date_str, (int, float)):
                    ed = datetime.fromtimestamp(float(earnings_date_str), tz=timezone.utc)
                else:
                    ed = None
                if ed:
                    earnings_passed = datetime.now(timezone.utc) > ed + timedelta(days=strategy.days_after)
            except (ValueError, TypeError):
                pass

        ticker = pos['ticker']
        stock_price = options_feed._get_stock_price(ticker)
        if not stock_price:
            continue

        total_cost = float(pos['total_cost'])
        strike_call = float(pos['strike_call'])
        strike_put = float(pos['strike_put'])

        # Estimate current option values post-earnings
        if earnings_passed:
            call_exit = max(0, stock_price - strike_call)
            put_exit = max(0, strike_put - stock_price)
        else:
            call_intrinsic = max(0, stock_price - strike_call)
            put_intrinsic = max(0, strike_put - stock_price)
            time_premium = total_cost * 0.15
            call_exit = call_intrinsic + time_premium / 2
            put_exit = put_intrinsic + time_premium / 2

        current_value = call_exit + put_exit
        pnl_pct = (current_value - total_cost) / total_cost if total_cost else 0

        should_close, reason = strategy.should_close(
            StranglePosition(
                ticker=ticker,
                entry_time=pos.get('entry_time', ''),
                stock_price_entry=float(pos.get('stock_price_entry', 0)),
                strike_call=strike_call,
                strike_put=strike_put,
                call_cost=float(pos.get('call_cost', 0)),
                put_cost=float(pos.get('put_cost', 0)),
                total_cost=total_cost,
                capital_used=float(pos.get('capital_used', 0)),
                call_otm_pct=float(pos.get('call_otm_pct', 0)),
                put_otm_pct=float(pos.get('put_otm_pct', 0)),
                iv_rank_at_entry=float(pos.get('iv_rank_entry', 0)),
                earnings_date=earnings_date_str,
            ),
            stock_price,
            earnings_passed=earnings_passed,
            call_mid=call_exit,
            put_mid=put_exit,
        )

        if should_close:
            close_strangle(pos, reason, stock_price, call_exit, put_exit)
            send_telegram(
                f"EARNINGS: <b>{ticker}</b> strangle cerrado\n"
                f"Reason={reason} PnL=${(current_value - total_cost) * 100:+.2f}",
                silent=True,
            )


def generate_report() -> str:
    with engine.connect() as conn:
        total = conn.execute(
            text("SELECT COUNT(*) FROM earnings_trades WHERE status='CLOSED'")
        ).scalar() or 0
        wins = conn.execute(
            text("SELECT COUNT(*) FROM earnings_trades WHERE status='CLOSED' AND pnl > 0")
        ).scalar() or 0
        pnl_sum = conn.execute(
            text("SELECT COALESCE(SUM(pnl), 0) FROM earnings_trades WHERE status='CLOSED'")
        ).scalar() or 0
        open_n = conn.execute(
            text("SELECT COUNT(*) FROM earnings_trades WHERE status='OPEN'")
        ).scalar() or 0

    wr = (wins / total * 100) if total > 0 else 0
    lines = [
        "EARNINGS STRANGLE — Reporte Paper",
        f"Balance: ${INITIAL_BALANCE + float(pnl_sum):.2f}",
        f"Trades: {total} cerrados | {open_n} abiertos",
        f"WR: {wr:.1f}% | PnL: ${float(pnl_sum):+.2f}",
    ]
    return '\n'.join(lines)


def main():
    logger.info("EarningsExecutor iniciado — paper trading")
    _ensure_table()
    send_telegram(
        f"<b>Earnings Strangle Agent iniciado</b>\n"
        f"Activos: {', '.join(ASSETS)}\n"
        f"Capital: ${INITIAL_BALANCE:.0f}\n"
        f"Paper mode",
        silent=True,
    )

    cycle = 0
    while True:
        try:
            cycle += 1
            monitor_positions()
            scan_earnings_entries()

            if cycle % 6 == 0:
                n = count_open()
                logger.info(f"Earnings cycle {cycle}: {n} strangles abiertos")

            if cycle % 24 == 0:
                report = generate_report()
                logger.info(report)
        except Exception as e:
            logger.error(f"Earnings cycle error: {e}")
        time.sleep(CYCLE_SECONDS)


if __name__ == '__main__':
    main()
