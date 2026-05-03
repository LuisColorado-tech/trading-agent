#!/usr/bin/env python3
"""
grid_stable_agent.py — Entry point para el Grid Stable Bot.

Corre como servicio systemd independiente. Opera pares ETH/BTC y LINK/BTC
con perfiles de baja volatilidad. Paper trading únicamente.

Integración: se conecta a la misma DB y Redis que los demás agentes.
Los trades se registran en la tabla `trades` con strategy='GRID_STABLE'.
"""
import os
import sys
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import redis as redis_lib
import yaml
from loguru import logger
from sqlalchemy import create_engine, text

sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')

import ccxt
from agents.indicators import IndicatorEngine
from core.grid_stable_profiles import GRID_STABLE_PROFILES, get_grid_stable_profile
from data.market_feed import MarketFeed
from strategies.grid_stable import GridStableStrategy
from core.notifications import send_telegram

# ── Config ──
with open('/opt/trading/config/exchange_config.yaml') as f:
    CFG = yaml.safe_load(f).get('grid_stable', {})

ENABLED_PAIRS = [
    pair for pair, cfg in CFG.get('pairs', {}).items()
    if cfg.get('enabled', True)
]
CYCLE_SECONDS = CFG.get('cycle_interval_seconds', 120)
MAX_CONCURRENT = CFG.get('risk', {}).get('max_concurrent_total', 5)
INITIAL_BALANCE = CFG.get('initial_balance', 500.0)
COOLDOWN_MINUTES = CFG.get('risk', {}).get('cooldown_minutes', 10)

# ── Estado intra-ciclo (previene re-entry en el mismo ciclo) ──
_sl_closed_this_cycle: set = set()

logger.info(f"GridStableAgent: {len(ENABLED_PAIRS)} pares: {ENABLED_PAIRS}")

# ── DB + Redis ──
db_url = (
    f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
    f"@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}"
    f"/{os.getenv('POSTGRES_DB', 'trading_agent')}"
)
engine = create_engine(db_url)
redis_client = redis_lib.Redis(
    host=os.getenv('REDIS_HOST', 'localhost'),
    port=int(os.getenv('REDIS_PORT', 6379)),
    decode_responses=True,
)

feed = MarketFeed()

# Exchange directo para pares estables (no pasan por MarketFeed que usa mapping USDT)
_exchange_stable = None


def _get_exchange_stable():
    global _exchange_stable
    if _exchange_stable is None:
        _exchange_stable = ccxt.kraken({'enableRateLimit': True})
    return _exchange_stable


def _fetch_stable_ohlcv(pair: str, limit: int = 200):
    """Descarga OHLCV para pares estables directamente via CCXT."""
    import pandas as pd
    try:
        ex = _get_exchange_stable()
        raw = ex.fetch_ohlcv(pair, '15m', limit=limit)
        df = pd.DataFrame(raw, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        return df.set_index('timestamp')
    except Exception as e:
        logger.error(f'fetch_ohlcv {pair}: {e}')
        return pd.DataFrame()


def count_open() -> int:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT COUNT(*) FROM trades WHERE status='OPEN' AND strategy='GRID_STABLE'")
        ).scalar() or 0


def open_levels(pair: str) -> set:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT metadata FROM trades WHERE status='OPEN' AND strategy='GRID_STABLE' AND asset=:p"),
            {'p': pair},
        ).fetchall()
    levels = set()
    for r in rows:
        try:
            meta = json.loads(r[0]) if isinstance(r[0], str) else (r[0] or {})
            if 'level_idx' in meta:
                levels.add(meta['level_idx'])
        except Exception:
            pass
    return levels


def open_trade(pair: str, level, profile, price: float):
    """Abre un trade grid stable y lo persiste en DB."""
    balance = INITIAL_BALANCE
    risk_usd = balance * 0.005 * profile.risk_fraction
    sl_dist = abs(level.sl - level.price)
    size = risk_usd / sl_dist if sl_dist > 0 else 0
    if size <= 0:
        return

    trade_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    meta = json.dumps({'level_idx': level.level_idx, 'range_spacing': profile.grid_levels})

    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO trades (id, asset, side, strategy, entry_price, stop_loss, take_profit,
                                position_size, position_pct, pnl, status, close_reason, paper_trade, timestamp_open, metadata)
            VALUES (:id, :asset, :side, :strategy, :entry, :sl, :tp,
                    :size, 0, 0, 'OPEN', NULL, true, :now, CAST(:meta AS jsonb))
        """), {
            'id': trade_id, 'asset': pair, 'side': level.direction,
            'strategy': 'GRID_STABLE', 'entry': level.price,
            'sl': level.sl, 'tp': level.tp, 'size': round(size, 8),
            'now': now, 'meta': meta,
        })

    redis_client.publish('grid_stable:new_trade', json.dumps({
        'id': trade_id, 'pair': pair, 'entry': level.price, 'level': level.level_idx,
    }))

    logger.info(f"GRID_STABLE OPEN: {pair} level={level.level_idx} entry={level.price:.6f} size={size:.4f}")


def _fetch_current_price(pair: str) -> Optional[float]:
    """Obtiene el último precio close para un par via CCXT Kraken."""
    try:
        ex = _get_exchange_stable()
        ticker = ex.fetch_ticker(pair)
        return float(ticker['close']) if ticker and ticker.get('close') else None
    except Exception as e:
        logger.warning(f"fetch_ticker {pair}: {e}")
        df = _fetch_stable_ohlcv(pair, limit=2)
        if not df.empty:
            return float(df.iloc[-1]['close'])
        return None


def close_trade(trade: dict, exit_price: float, reason: str, pnl: float):
    """Cierra un trade grid stable en DB. Aplica cooldown si fue SL para evitar re-entry."""
    now = datetime.now(timezone.utc)
    pnl_pct = (pnl / (float(trade['entry_price']) * float(trade['position_size']))) * 100 if float(trade['position_size']) else 0
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE trades SET status='CLOSED', exit_price=:ep, close_reason=:reason,
                pnl=:pnl, pnl_pct=:pnl_pct, timestamp_close=:now
            WHERE id=:id
        """), {
            'id': trade['id'], 'ep': exit_price, 'reason': reason,
            'pnl': round(pnl, 8), 'pnl_pct': round(pnl_pct, 2), 'now': now,
        })

    # Cooldown post-SL: bloquea re-entrada inmediata (Redis + intra-ciclo)
    if reason in ('STOP_LOSS', 'TRAILING_STOP'):
        pair = trade['asset']
        redis_client.setex(f'cooldown_grid_stable:{pair}', COOLDOWN_MINUTES * 60, reason)
        _sl_closed_this_cycle.add(pair)
        logger.info(f'COOLDOWN GRID_STABLE: {pair} blocked for {COOLDOWN_MINUTES}m ({reason})')

    logger.info(
        f"GRID_STABLE CLOSE: {trade['asset']} {reason} | "
        f"entry={trade['entry_price']:.8f} exit={exit_price:.8f} PnL=${pnl:.4f}"
    )


def monitor_trades():
    """Monitorea trades GRID_STABLE abiertos y cierra los que lleguen a SL o TP."""
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM trades WHERE status='OPEN' AND strategy='GRID_STABLE'")
        ).fetchall()
    trades = [dict(r._mapping) for r in rows]
    if not trades:
        return

    pairs = {t['asset'] for t in trades}
    prices = {}
    for pair in pairs:
        price = _fetch_current_price(pair)
        if price is not None:
            prices[pair] = price
        else:
            logger.warning(f"GRID_STABLE monitor: no price for {pair}, skipping {len([t for t in trades if t['asset'] == pair])} trades")

    for trade in trades:
        pair = trade['asset']
        current = prices.get(pair)
        if current is None:
            continue

        entry = float(trade['entry_price'])
        sl = float(trade['stop_loss'])
        tp = float(trade['take_profit'])
        size = float(trade['position_size'])
        side = trade['side']

        if side == 'SELL':
            # Trailing break-even: si profit > 50% del camino al TP, mover SL a entry
            distance_to_tp = entry - tp
            profit_so_far = entry - current
            if profit_so_far > 0 and distance_to_tp > 0:
                if profit_so_far > distance_to_tp * 0.5 and sl > entry:
                    with engine.begin() as conn:
                        conn.execute(
                            text("UPDATE trades SET stop_loss = :new_sl WHERE id = :id"),
                            {'new_sl': entry, 'id': trade['id']},
                        )
                    logger.debug(f"GRID_STABLE trailing: {pair} SL moved to break-even at {entry:.8f}")

            if current >= sl:
                pnl = (entry - sl) * size
                close_trade(trade, sl, 'STOP_LOSS', pnl)
            elif current <= tp:
                pnl = (entry - tp) * size
                close_trade(trade, tp, 'TAKE_PROFIT', pnl)
        elif side == 'BUY':
            # Trailing break-even para BUY
            distance_to_tp = tp - entry
            profit_so_far = current - entry
            if profit_so_far > 0 and distance_to_tp > 0:
                if profit_so_far > distance_to_tp * 0.5 and sl < entry:
                    with engine.begin() as conn:
                        conn.execute(
                            text("UPDATE trades SET stop_loss = :new_sl WHERE id = :id"),
                            {'new_sl': entry, 'id': trade['id']},
                        )
                    logger.debug(f"GRID_STABLE trailing: {pair} SL moved to break-even at {entry:.8f}")

            if current <= sl:
                pnl = (sl - entry) * size
                close_trade(trade, sl, 'STOP_LOSS', pnl)
            elif current >= tp:
                pnl = (tp - entry) * size
                close_trade(trade, tp, 'TAKE_PROFIT', pnl)


def run_cycle():
    """Un ciclo de evaluación."""
    total_open = count_open()
    if total_open >= MAX_CONCURRENT:
        return

    for pair in ENABLED_PAIRS:
        if count_open() >= MAX_CONCURRENT:
            break

        # Cooldown check: Redis + intra-ciclo (evita re-entry post-SL)
        if pair in _sl_closed_this_cycle:
            continue
        if redis_client.ttl(f'cooldown_grid_stable:{pair}') > 0:
            continue

        profile = get_grid_stable_profile(pair)
        strategy = GridStableStrategy(profile)

        # Obtener OHLCV
        df = _fetch_stable_ohlcv(pair, limit=profile.grid_range_candles + 50)
        if df is None or df.empty or len(df) < profile.grid_range_candles:
            continue

        ind = IndicatorEngine.calculate(df, pair, '15m')
        if ind is None:
            continue

        config = strategy.build_grid(df, ind)
        if config is None:
            continue

        current = df.iloc[-1]['close']
        level = strategy.find_nearest_level(float(current), config)
        if level is None:
            continue

        # Verificar nivel duplicado
        opened = open_levels(pair)
        if level.level_idx in opened:
            continue

        open_trade(pair, level, profile, float(current))


def main():
    logger.info(f"GridStableAgent iniciado — {len(ENABLED_PAIRS)} pares — paper trading")
    send_telegram(
        f"🤖 <b>Grid Stable Bot iniciado</b>\n"
        f"Pares: {', '.join(ENABLED_PAIRS)}\n"
        f"Capital: ${INITIAL_BALANCE:.0f} | Ciclo: {CYCLE_SECONDS}s\n"
        f"Modo: PAPER TRADING",
        silent=True,
    )

    cycle = 0
    while True:
        try:
            cycle += 1
            before = count_open()
            _sl_closed_this_cycle.clear()  # reset intra-ciclo
            monitor_trades()
            run_cycle()
            after = count_open()
            if cycle % 30 == 0:
                logger.info(f"GridStable cycle {cycle}: {before}→{after} open trades")
        except Exception as e:
            logger.error(f"GridStable cycle error: {e}")
        time.sleep(CYCLE_SECONDS)


if __name__ == '__main__':
    main()
