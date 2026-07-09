"""
DirectionGuard — Auto-protección de direcciones perdedoras.

Detecta direcciones (BUY/SELL) con WR < 30% y ≥15 trades cerrados,
las desactiva automáticamente por 72h. Tras el cooldown, se re-evalúa.

Usa Redis para persistencia (sobrevive reinicios).
Patrón: mismo que cooldowns y halts del sistema.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple

from loguru import logger
from sqlalchemy import create_engine, text

# ── Redis ──
import redis as redis_lib
_redis = redis_lib.Redis(host='localhost', port=6379, decode_responses=True)

# ── DB ──
import os
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')
DB_URL = (
    f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
    f"@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}"
    f"/{os.getenv('POSTGRES_DB', 'trading_agent')}"
)
_engine = create_engine(DB_URL)

# ── Parámetros ──────────────────────────────────────────────────────────
MIN_TRADES = 15          # Evaluar solo con ≥N trades cerrados
MIN_WR_PCT = 30.0        # WR mínimo para seguir activo
COOLDOWN_HOURS = 72      # Tiempo de bloqueo
REDIS_PREFIX = 'direction_guard'


def _key(symbol: str, direction: str) -> str:
    return f'{REDIS_PREFIX}:{symbol}:{direction}'


def _get_stats(symbol: str, direction: str) -> Tuple[int, int, float]:
    """Retorna (total_trades, wins, win_rate) para un symbol+direction."""
    with _engine.connect() as conn:
        row = conn.execute(text("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                   ROUND(SUM(pnl)::numeric, 2) as pnl
            FROM stocks_trades
            WHERE symbol = :symbol
              AND direction = :direction
              AND status = 'CLOSED'
        """), {'symbol': symbol, 'direction': direction}).fetchone()
        total = int(row[0] or 0)
        wins = int(row[1] or 0)
        wr = round(100.0 * wins / total, 1) if total > 0 else 0.0
        return total, wins, wr


def is_allowed(symbol: str, direction: str) -> bool:
    """Consulta si una dirección está permitida para un símbolo.
    
    Returns:
        True si la dirección está activa (no bloqueada).
    """
    k = _key(symbol, direction)
    blocked_until = _redis.get(k)
    
    if blocked_until:
        try:
            until = datetime.fromisoformat(blocked_until)
            if datetime.now(timezone.utc) < until:
                return False
            # Cooldown expirado → levantar bloqueo y re-evaluar
            _redis.delete(k)
            logger.info(f'DirectionGuard: cooldown expirado para {symbol}/{direction} — re-evaluando')
        except (ValueError, TypeError):
            _redis.delete(k)
    
    # Evaluar si debe bloquearse
    total, wins, wr = _get_stats(symbol, direction)
    
    if total >= MIN_TRADES and wr < MIN_WR_PCT:
        until = datetime.now(timezone.utc) + timedelta(hours=COOLDOWN_HOURS)
        _redis.set(k, until.isoformat())
        logger.warning(
            f'DirectionGuard: BLOQUEADO {symbol}/{direction} '
            f'(WR={wr}% en {total} trades) — hasta {until.strftime("%Y-%m-%d %H:%M UTC")}'
        )
        return False
    
    return True


def get_blocked() -> dict:
    """Retorna dict de {symbol/direction: until} para direcciones bloqueadas."""
    blocked = {}
    for key in _redis.scan_iter(f'{REDIS_PREFIX}:*'):
        val = _redis.get(key)
        if val:
            try:
                until = datetime.fromisoformat(val)
                if datetime.now(timezone.utc) < until:
                    parts = key.split(':')
                    blocked[f'{parts[1]}/{parts[2]}'] = until.isoformat()
                else:
                    _redis.delete(key)
            except (ValueError, TypeError):
                _redis.delete(key)
    return blocked


def force_unblock(symbol: str, direction: str):
    """Desbloquea manualmente una dirección."""
    k = _key(symbol, direction)
    if _redis.delete(k):
        logger.info(f'DirectionGuard: desbloqueo manual {symbol}/{direction}')


def status() -> str:
    """Resumen legible para /status y health check."""
    blocked = get_blocked()
    if not blocked:
        return 'DirectionGuard: sin bloqueos activos'
    lines = ['DirectionGuard — BLOQUEOS ACTIVOS:']
    for k, until in sorted(blocked.items()):
        lines.append(f'  {k}: hasta {until[:19]}')
    return '\n'.join(lines)


# ── Crypto DirectionGuard ────────────────────────────────────────────────
# Misma lógica que stocks pero contra la tabla `trades` (TREND_MOMENTUM).

CRYPTO_MIN_TRADES = 15
CRYPTO_MIN_WR_PCT = 30.0
CRYPTO_COOLDOWN_HOURS = 72
CRYPTO_PREFIX = 'direction_guard_crypto'


def _crypto_key(asset: str, direction: str) -> str:
    return f'{CRYPTO_PREFIX}:{asset}:{direction}'


def _get_crypto_stats(asset: str, direction: str):
    """Retorna (total_trades, wins, win_rate) para crypto."""
    with _engine.connect() as conn:
        row = conn.execute(text("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                   ROUND(SUM(pnl)::numeric, 2) as pnl
            FROM trades
            WHERE asset = :asset
              AND strategy = 'TREND_MOMENTUM'
              AND side = :direction
              AND status = 'CLOSED'
        """), {'asset': asset, 'direction': direction}).fetchone()
        total = int(row[0] or 0)
        wins = int(row[1] or 0)
        wr = round(100.0 * wins / total, 1) if total > 0 else 0.0
        return total, wins, wr


def crypto_is_allowed(asset: str, direction: str) -> bool:
    """DirectionGuard para crypto (TREND_MOMENTUM)."""
    k = _crypto_key(asset, direction)
    blocked_until = _redis.get(k)
    
    if blocked_until:
        try:
            until = datetime.fromisoformat(blocked_until)
            if datetime.now(timezone.utc) < until:
                return False
            _redis.delete(k)
            logger.info(f'CryptoDirectionGuard: cooldown expirado {asset}/{direction}')
        except (ValueError, TypeError):
            _redis.delete(k)
    
    total, wins, wr = _get_crypto_stats(asset, direction)
    
    if total >= CRYPTO_MIN_TRADES and wr < CRYPTO_MIN_WR_PCT:
        until = datetime.now(timezone.utc) + timedelta(hours=CRYPTO_COOLDOWN_HOURS)
        _redis.set(k, until.isoformat())
        logger.warning(
            f'CryptoDirectionGuard: BLOQUEADO {asset}/{direction} '
            f'(WR={wr}% en {total} trades) — hasta {until.strftime("%Y-%m-%d %H:%M UTC")}'
        )
        return False
    
    return True


def crypto_get_blocked() -> dict:
    """Retorna dict de direcciones crypto bloqueadas."""
    blocked = {}
    for key in _redis.scan_iter(f'{CRYPTO_PREFIX}:*'):
        val = _redis.get(key)
        if val:
            try:
                until = datetime.fromisoformat(val)
                if datetime.now(timezone.utc) < until:
                    parts = key.split(':')
                    blocked[f'{parts[1]}/{parts[2]}'] = until.isoformat()
                else:
                    _redis.delete(key)
            except (ValueError, TypeError):
                _redis.delete(key)
    return blocked
