"""
Polymarket SNIPE Agent — Late-entry + Arbitrage bot para mercados Up/Down 15m.

Estrategias:
  SNIPE: En minuto 13-14.5 de cada ventana 15m, comprar el lado ganador 
         a $0.93-$0.97 para cobro casi seguro de $1.00. WR=94% documentado.
  ARB:   Cuando YES+NO mid < $0.985, comprar ambos lados para profit garantizado.

Basado en LuciferForge/polymarket-btc-autotrader, adaptado a nuestra infraestructura.
Paper trading — usa Kraken/OKX via CCXT para precios (Binance bloqueado HTTP 451).
"""
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import requests
import yaml
import ccxt
from loguru import logger
from sqlalchemy import create_engine, text

sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')

try:
    from core.notifications import send_telegram
except ImportError:
    def send_telegram(msg, silent=False):
        pass

# ── Config ────────────────────────────────────────────────────────────────
with open('/opt/trading/config/exchange_config.yaml') as f:
    _CFG = yaml.safe_load(f).get('polymarket_snipe', {})

GAMMA_API   = _CFG.get('gamma_api', 'https://gamma-api.polymarket.com')
SCAN_INTERVAL = _CFG.get('scan_interval_seconds', 30)
PAPER_BALANCE = _CFG.get('initial_paper_balance', 500.0)
DRY_RUN       = _CFG.get('paper_trading', True)

# ── SNIPE params ──
SNIPE_MIN_MINUTE = _CFG.get('snipe', {}).get('min_minute', 13)
SNIPE_MAX_MINUTE = _CFG.get('snipe', {}).get('max_minute', 14.5)
SNIPE_THRESHOLD  = _CFG.get('snipe', {}).get('momentum_threshold_pct', 0.10)
SNIPE_MAX_ENTRY  = _CFG.get('snipe', {}).get('max_entry_price', 0.97)
SNIPE_MIN_ENTRY  = _CFG.get('snipe', {}).get('min_entry_price', 0.88)
SNIPE_SIZE       = _CFG.get('snipe', {}).get('order_size_shares', 40)

# ── ARB params ──
ARB_TARGET_COST = _CFG.get('arb', {}).get('target_cost', 0.985)
ARB_MIN_GAP     = _CFG.get('arb', {}).get('min_gap', 0.015)
ARB_SIZE        = _CFG.get('arb', {}).get('order_size_shares', 25)

# ── Risk ──
MAX_CONCURRENT = _CFG.get('risk', {}).get('max_concurrent_positions', 3)
ASSETS         = _CFG.get('assets', ['btc', 'eth', 'sol', 'xrp'])

logger.info(f"PolySnipeAgent: {len(ASSETS)} assets: {[a.upper() for a in ASSETS]}")

# ── Asset → Kraken pair mapping ──
ASSET_PAIRS = {'BTC': 'BTC/USDT', 'ETH': 'ETH/USDT', 'SOL': 'SOL/USDT', 'XRP': 'XRP/USDT'}

# ── DB ────────────────────────────────────────────────────────────────────
db_url = (
    f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
    f"@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}"
    f"/{os.getenv('POSTGRES_DB', 'trading_agent')}"
)
engine = create_engine(db_url)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS snipe_trades (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset           VARCHAR(10) NOT NULL,
    strategy        VARCHAR(20) NOT NULL,
    market_slug     VARCHAR(200),
    condition_id    VARCHAR(100),
    direction       VARCHAR(4) NOT NULL,
    entry_price     NUMERIC(10, 4) NOT NULL,
    shares          NUMERIC(14, 4) NOT NULL,
    cost_usdc       NUMERIC(10, 4) NOT NULL,
    move_pct        NUMERIC(8, 4),
    window_start    BIGINT NOT NULL,
    window_end      BIGINT NOT NULL,
    outcome         VARCHAR(8),
    pnl_usdc        NUMERIC(10, 4),
    status          VARCHAR(8) DEFAULT 'OPEN',
    paper_trade     BOOLEAN DEFAULT TRUE,
    timestamp_open  TIMESTAMPTZ DEFAULT NOW(),
    timestamp_close TIMESTAMPTZ
)
"""

CREATE_SESSION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS snipe_sessions (
    id              SERIAL PRIMARY KEY,
    session_name    VARCHAR(50) UNIQUE,
    status          VARCHAR(20) DEFAULT 'ACTIVE',
    initial_balance NUMERIC DEFAULT 0,
    current_balance NUMERIC DEFAULT 0,
    total_trades    INTEGER DEFAULT 0,
    winning_trades  INTEGER DEFAULT 0,
    snipe_trades_i  INTEGER DEFAULT 0,
    arb_trades_i    INTEGER DEFAULT 0,
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    ended_at        TIMESTAMPTZ
)
"""


def init_db():
    with engine.begin() as conn:
        conn.execute(text(CREATE_TABLE_SQL))
        conn.execute(text(CREATE_SESSION_TABLE_SQL))


def ensure_session() -> dict:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM snipe_sessions WHERE status='ACTIVE' ORDER BY started_at DESC LIMIT 1")
        ).fetchone()
    if row:
        return dict(row._mapping)
    name = datetime.now(timezone.utc).strftime('SNIPE_SESSION_%Y%m%d_%H%M')
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO snipe_sessions (session_name, initial_balance, current_balance) "
            "VALUES (:n, :b, :b)"
        ), {'n': name, 'b': PAPER_BALANCE})
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM snipe_sessions WHERE session_name=:n"), {'n': name}
        ).fetchone()
    return dict(row._mapping)


# ── Price Feed (Kraken/OKX via CCXT — Binance bloqueado HTTP 451) ────────
_kraken_exchange = None
_okx_exchange = None
_price_cache: dict[str, tuple[float, float]] = {}
_price_cache_ts = 0.0
PRICE_CACHE_TTL = 5.0


def _get_kraken():
    global _kraken_exchange
    if _kraken_exchange is None:
        _kraken_exchange = ccxt.kraken({'enableRateLimit': True})
    return _kraken_exchange


def _get_okx():
    global _okx_exchange
    if _okx_exchange is None:
        _okx_exchange = ccxt.okx({'enableRateLimit': True})
    return _okx_exchange


def _get_current_price(pair: str) -> Optional[float]:
    global _price_cache, _price_cache_ts
    now = time.time()
    if pair in _price_cache and now - _price_cache_ts < PRICE_CACHE_TTL:
        return _price_cache[pair][0]
    for ex in (_get_kraken(), _get_okx()):
        try:
            ticker = ex.fetch_ticker(pair)
            price = float(ticker['close'])
            _price_cache[pair] = (price, now)
            _price_cache_ts = now
            return price
        except Exception:
            continue
    return None


def _get_ohlcv_at(timestamp: int, pair: str) -> Optional[float]:
    """Obtiene precio open del asset en un timestamp via Kraken/OKX."""
    for ex in (_get_kraken(), _get_okx()):
        try:
            candles = ex.fetch_ohlcv(pair, '1m', since=timestamp * 1000, limit=1)
            if candles and len(candles) > 0:
                return float(candles[0][1])
        except Exception:
            continue
    return None


def _get_close_at(window_end: int, pair: str) -> Optional[float]:
    """Obtiene precio close del asset al final de la ventana."""
    for ex in (_get_kraken(), _get_okx()):
        try:
            since_ms = (window_end - 120) * 1000
            candles = ex.fetch_ohlcv(pair, '1m', since=since_ms, limit=3)
            if candles and len(candles) >= 1:
                return float(candles[-1][4])
        except Exception:
            continue
    return None


# ── Market Discovery ──────────────────────────────────────────────────────
def scan_15m_updown_markets() -> list[dict]:
    now_ts = int(time.time())
    current_window_start = now_ts - (now_ts % 900)
    markets = []
    for asset in ASSETS:
        for offset in range(-1, 3):
            ts = current_window_start + (offset * 900)
            slug = f'{asset}-updown-15m-{ts}'
            window_end = ts + 900
            if window_end < now_ts - 60:
                continue
            try:
                resp = requests.get(f'{GAMMA_API}/markets', params={'slug': slug}, timeout=10)
                data = resp.json()
                if not data:
                    continue
                market_list = data if isinstance(data, list) else [data]
                for m in market_list:
                    if m.get('question'):
                        m['_slug'] = slug
                        m['_asset'] = asset.upper()
                        m['_window_start'] = ts
                        m['_window_end'] = window_end
                        markets.append(m)
                        break
            except Exception as e:
                logger.debug(f'scan_15m {slug}: {e}')
    return markets


def get_market_tokens(market: dict) -> dict | None:
    tokens_raw = market.get('clobTokenIds', [])
    prices_raw = market.get('outcomePrices', '[]')
    if isinstance(tokens_raw, str):
        try:
            tokens = json.loads(tokens_raw)
        except json.JSONDecodeError:
            return None
    else:
        tokens = tokens_raw
    if isinstance(prices_raw, str):
        try:
            prices = json.loads(prices_raw)
        except json.JSONDecodeError:
            prices = [0.5, 0.5]
    else:
        prices = prices_raw
    if len(tokens) < 2:
        return None
    return {
        'up_token': tokens[0],
        'down_token': tokens[1],
        'up_mid': float(prices[0]) if prices else 0.5,
        'down_mid': float(prices[1]) if len(prices) > 1 else 0.5,
    }


# ── Estrategia SNIPE ──────────────────────────────────────────────────────
def evaluate_snipe(market: dict) -> dict | None:
    window_start = market['_window_start']
    now_ts = int(time.time())
    elapsed_min = (now_ts - window_start) / 60
    if elapsed_min < SNIPE_MIN_MINUTE or elapsed_min > SNIPE_MAX_MINUTE:
        return None

    asset = market.get('_asset', 'BTC').upper()
    pair = ASSET_PAIRS.get(asset, 'BTC/USDT')
    open_price = _get_ohlcv_at(window_start, pair)
    current_price = _get_current_price(pair)
    if not open_price or not current_price:
        return None

    move_pct = ((current_price - open_price) / open_price) * 100
    if abs(move_pct) < SNIPE_THRESHOLD:
        return None

    direction = 'UP' if move_pct > 0 else 'DOWN'
    est_win_rate = 99.0 if abs(move_pct) >= 0.20 else 98.0
    return {
        'direction': direction, 'open_price': open_price,
        'current_price': current_price, 'move_pct': round(move_pct, 4),
        'elapsed_min': elapsed_min, 'est_win_rate': est_win_rate,
    }


def check_price_in_entry_zone(win_side_price: float, is_snipe: bool = True) -> bool:
    if is_snipe:
        return SNIPE_MIN_ENTRY <= win_side_price <= SNIPE_MAX_ENTRY
    return win_side_price <= SNIPE_MAX_ENTRY


# ── Estrategia ARB ────────────────────────────────────────────────────────
def evaluate_arb(market: dict, tokens: dict) -> dict | None:
    combined = tokens['up_mid'] + tokens['down_mid']
    if combined >= ARB_TARGET_COST:
        return None
    profit = 1.0 - combined
    if profit < ARB_MIN_GAP:
        return None
    return {
        'up_mid': tokens['up_mid'], 'down_mid': tokens['down_mid'],
        'combined': combined, 'profit_per_share': profit,
    }


# ── Executor ──────────────────────────────────────────────────────────────
_slug_cooldown: dict = {}  # slug -> timestamp until which it's blocked

MAX_DAILY_LOSS = _CFG.get('risk', {}).get('max_daily_loss', 15.0)  # circuit breaker diario


def slug_already_traded(slug: str) -> bool:
    """True si ya existe un trade OPEN o CLOSED en los últimos 2 min para este slug."""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT COUNT(*) FROM snipe_trades "
                 "WHERE market_slug = :s AND timestamp_open > NOW() - INTERVAL '2 minutes'"),
            {'s': slug},
        ).fetchone()
    return int(row[0]) > 0 if row else False


def count_open() -> int:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT COUNT(*) FROM snipe_trades WHERE status='OPEN'")
        ).scalar() or 0


def daily_pnl() -> float:
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    with engine.connect() as conn:
        return float(conn.execute(
            text("SELECT COALESCE(SUM(pnl_usdc), 0) FROM snipe_trades "
                 "WHERE timestamp_open::date = :d AND pnl_usdc IS NOT NULL"),
            {'d': today}
        ).scalar() or 0)


def open_snipe_trade(market: dict, signal: dict, tokens: dict):
    window_start = market['_window_start']
    slug = market.get('_slug', '')
    condition_id = market.get('conditionId', slug)
    direction = signal['direction']

    entry_price = tokens['up_mid'] if direction == 'UP' else tokens['down_mid']
    if not check_price_in_entry_zone(entry_price, is_snipe=True):
        return

    shares = SNIPE_SIZE
    cost = round(shares * entry_price, 4)
    if cost > PAPER_BALANCE * 0.4:
        logger.info(f'SNIPE [{market["_asset"]}] rechazado: cost ${cost:.2f} > 40% balance')
        return

    trade_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO snipe_trades (id, asset, strategy, market_slug, condition_id,
                direction, entry_price, shares, cost_usdc, move_pct,
                window_start, window_end, status, paper_trade, timestamp_open)
            VALUES (:id, :asset, 'SNIPE', :slug, :cid,
                :dir, :ep, :shares, :cost, :move,
                :ws, :we, 'OPEN', true, :now)
        """), {
            'id': trade_id, 'asset': market['_asset'], 'slug': slug, 'cid': condition_id,
            'dir': direction, 'ep': entry_price, 'shares': shares, 'cost': cost,
            'move': signal['move_pct'], 'ws': window_start,
            'we': market['_window_end'], 'now': now,
        })

    send_telegram(
        f'🎯 <b>SNIPE OPEN</b> [{market["_asset"]}] {direction}\n'
        f'Entry: ${entry_price:.4f} x {shares} = ${cost:.2f}\n'
        f'Move: {signal["move_pct"]:+.3f}% | WR est: {signal["est_win_rate"]:.0f}%\n'
        f'<code>{slug}</code>', silent=True,
    )


def open_arb_trade(market: dict, arb: dict, tokens: dict):
    slug = market.get('_slug', '')
    condition_id = market.get('conditionId', slug)
    window_start = market['_window_start']

    size_per_side = ARB_SIZE
    up_cost = round(size_per_side * arb['up_mid'], 4)
    down_cost = round(size_per_side * arb['down_mid'], 4)
    combined = up_cost + down_cost
    profit = round(size_per_side * arb['profit_per_share'], 4)

    if combined > PAPER_BALANCE * 0.5:
        logger.info(f'ARB [{market["_asset"]}] rechazado: cost ${combined:.2f} > 50% balance')
        return

    trade_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO snipe_trades (id, asset, strategy, market_slug, condition_id,
                direction, entry_price, shares, cost_usdc, move_pct,
                window_start, window_end, status, paper_trade, timestamp_open)
            VALUES (:id, :asset, 'ARB', :slug, :cid,
                'BOTH', :ep, :shares, :cost, 0,
                :ws, :we, 'OPEN', true, :now)
        """), {
            'id': trade_id, 'asset': market['_asset'], 'slug': slug, 'cid': condition_id,
            'ep': round(arb['combined'], 4), 'shares': size_per_side,
            'cost': round(combined, 4), 'ws': window_start,
            'we': market['_window_end'], 'now': now,
        })

    send_telegram(
        f'🔒 <b>ARB OPEN</b> [{market["_asset"]}]\n'
        f'YES=${arb["up_mid"]:.4f} + NO=${arb["down_mid"]:.4f} = ${arb["combined"]:.4f}\n'
        f'Profit garantizado: ${profit:.4f}\n<code>{slug}</code>', silent=True,
    )


# ── Resolver trades expirados ─────────────────────────────────────────────
def resolve_expired_trades():
    now_ts = int(time.time())
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM snipe_trades WHERE status='OPEN' ORDER BY timestamp_open")
        ).fetchall()
    trades = [dict(r._mapping) for r in rows]

    closed_any = False
    for trade in trades:
        window_end = int(trade['window_end'])
        if now_ts < window_end + 60:
            continue

        direction = trade['direction']
        asset = trade['asset']
        entry = float(trade['entry_price'])
        shares = float(trade['shares'])
        cost = float(trade['cost_usdc'])
        strategy = trade['strategy']
        pair = ASSET_PAIRS.get(asset, 'BTC/USDT')

        if strategy == 'ARB':
            outcome = 'WIN'
            pnl = (1.0 - entry) * shares
        else:
            open_price = _get_ohlcv_at(int(trade['window_start']), pair)
            close_price = _get_close_at(window_end - 1, pair)

            if open_price and close_price:
                actual_dir = 'UP' if close_price >= open_price else 'DOWN'
                if direction == actual_dir:
                    outcome = 'WIN'
                    pnl = (1.0 - entry) * shares
                else:
                    outcome = 'LOSS'
                    pnl = -cost
                # Divergencia oracle: loggear gap Kraken vs Polymarket
                actual_move = ((close_price - open_price) / open_price) * 100
                if abs(actual_move) < SNIPE_THRESHOLD:
                    logger.warning(
                        f'ORACLE GAP [{asset}] {direction} → {actual_dir} | '
                        f'move={actual_move:+.4f}% (below threshold {SNIPE_THRESHOLD}%) | '
                        f'entry_move={float(trade["move_pct"]):+.4f}% | '
                        f'Kraken open={open_price:.4f} close={close_price:.4f} | outcome={outcome}'
                    )
            elif now_ts > window_end + 7200:
                outcome = 'EXPIRED'
                pnl = 0.0
            else:
                continue

        now = datetime.now(timezone.utc)
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE snipe_trades SET status='CLOSED', outcome=:outcome,
                    pnl_usdc=:pnl, timestamp_close=:now WHERE id=:id
            """), {'outcome': outcome, 'pnl': round(pnl, 4), 'now': now, 'id': trade['id']})

        icon = '✅' if pnl > 0 else '❌' if pnl < 0 else '⏸️'
        logger.info(
            f'RESOLVED [{asset}] {strategy} {direction} → {outcome} | P&L=${pnl:+.4f}')

        # Actualizar snipe_sessions para que heartbeat/consortium refleje el balance real
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE snipe_sessions SET current_balance = current_balance + :pnl,
                    total_trades = total_trades + 1,
                    winning_trades = winning_trades + :win,
                    snipe_trades_i = snipe_trades_i + CASE WHEN :strat = 'SNIPE' THEN 1 ELSE 0 END,
                    arb_trades_i = arb_trades_i + CASE WHEN :strat = 'ARB' THEN 1 ELSE 0 END
                WHERE status = 'ACTIVE'
            """), {'pnl': round(pnl, 4), 'win': 1 if pnl > 0 else 0, 'strat': strategy})
        send_telegram(
            f'{icon} <b>SNIPE RESOLVED</b> [{asset}] {strategy}\n'
            f'{direction} → {outcome} | P&L: ${pnl:+.4f}',
            silent=True if pnl <= 0 else False,
        )
        closed_any = True

    return closed_any


# ── Stats ─────────────────────────────────────────────────────────────────
def get_stats() -> dict:
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status='OPEN' THEN 1 ELSE 0 END) AS open_cnt,
                SUM(CASE WHEN status='CLOSED' THEN 1 ELSE 0 END) AS closed_cnt,
                SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN strategy='SNIPE' THEN 1 ELSE 0 END) AS snipe_cnt,
                SUM(CASE WHEN strategy='ARB' THEN 1 ELSE 0 END) AS arb_cnt,
                COALESCE(SUM(pnl_usdc), 0) AS total_pnl
            FROM snipe_trades WHERE paper_trade = TRUE
        """)).fetchone()

    total, open_cnt, closed_cnt, wins, snipe_cnt, arb_cnt, pnl = row
    total = int(total or 0)
    closed_cnt = int(closed_cnt or 0)
    wins = int(wins or 0)
    win_rate = (wins / closed_cnt * 100) if closed_cnt else 0
    balance = PAPER_BALANCE + float(pnl or 0)

    return {
        'total_trades': total, 'open': int(open_cnt or 0),
        'closed': closed_cnt, 'wins': wins,
        'win_rate_pct': round(win_rate, 1),
        'snipe_trades': int(snipe_cnt or 0),
        'arb_trades': int(arb_cnt or 0),
        'total_pnl': round(float(pnl or 0), 2),
        'balance': round(balance, 2),
    }
