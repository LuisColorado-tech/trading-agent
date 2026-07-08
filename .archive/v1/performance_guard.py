"""
Circuit breaker por estrategia para paper trading.
Bloquea combinaciones activo/estrategia con edge reciente insuficiente.

v2: Bloqueos temporales con cooldown (evita deadlock permanente).
    - Bloqueo dura GUARD_COOLDOWN_HOURS horas, luego se levanta automáticamente.
    - Solo evalúa trades cerrados en las últimas GUARD_WINDOW_HOURS horas.
    - Tras el cooldown, la estrategia opera con position size reducido
      durante PROBATION_TRADES trades (controlado por risk_manager).
"""
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Dict, Iterable, Mapping, Optional, Tuple

from loguru import logger
from sqlalchemy import create_engine, text


ASSET_STRATEGY_LOOKBACK = 6
STRATEGY_LOOKBACK = 10
MIN_ASSET_STRATEGY_TRADES = 4
MIN_STRATEGY_TRADES = 5

# ── Guard cooldown: evitar deadlock permanente ──────────────────────
GUARD_COOLDOWN_HOURS = 4       # Bloqueo se levanta tras N horas
GUARD_WINDOW_HOURS = 8         # Solo evaluar trades cerrados en las últimas N horas
PROBATION_TRADES = 3           # Trades de prueba tras levantar bloqueo (size reducido 50%)


@dataclass(frozen=True)
class PerformanceSnapshot:
    total: int
    wins: int
    losses: int
    flats: int
    pnl: float
    gross_profit: float
    gross_loss: float
    win_rate: float
    profit_factor: float
    consecutive_losses: int


def summarize_closed_trades(rows: Iterable[Mapping]) -> PerformanceSnapshot:
    normalized = []
    for row in rows:
        pnl = float(row['pnl'])
        normalized.append({'pnl': pnl})

    wins = sum(1 for row in normalized if row['pnl'] > 0)
    losses = sum(1 for row in normalized if row['pnl'] < 0)
    flats = sum(1 for row in normalized if row['pnl'] == 0)
    pnl = sum(row['pnl'] for row in normalized)
    gross_profit = sum(row['pnl'] for row in normalized if row['pnl'] > 0)
    gross_loss = abs(sum(row['pnl'] for row in normalized if row['pnl'] < 0))
    nonflat = wins + losses
    win_rate = (wins / nonflat) if nonflat else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float('inf') if gross_profit > 0 else 0.0)

    consecutive_losses = 0
    for row in normalized:
        if row['pnl'] < 0:
            consecutive_losses += 1
            continue
        break

    return PerformanceSnapshot(
        total=len(normalized),
        wins=wins,
        losses=losses,
        flats=flats,
        pnl=pnl,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        win_rate=win_rate,
        profit_factor=profit_factor,
        consecutive_losses=consecutive_losses,
    )


def should_block_asset_strategy(snapshot: PerformanceSnapshot) -> Optional[str]:
    if snapshot.total < MIN_ASSET_STRATEGY_TRADES:
        return None
    if snapshot.losses >= 3 and snapshot.wins <= 1 and snapshot.pnl < 0 and snapshot.win_rate < 0.40:
        return (
            'ASSET_STRATEGY_UNDERPERFORMING:'
            f'wr={snapshot.win_rate:.2f}:pf={snapshot.profit_factor:.2f}:losses={snapshot.losses}'
        )
    if snapshot.consecutive_losses >= 3 and snapshot.pnl < 0:
        return f'ASSET_STRATEGY_LOSS_STREAK:{snapshot.consecutive_losses}'
    return None


def should_block_strategy(snapshot: PerformanceSnapshot) -> Optional[str]:
    if snapshot.total < MIN_STRATEGY_TRADES:
        return None
    if snapshot.wins == 0 and snapshot.losses >= 4:
        return f'STRATEGY_NO_EDGE:{snapshot.losses}_losses'
    if snapshot.consecutive_losses >= 4 and snapshot.pnl < 0:
        return f'STRATEGY_LOSS_STREAK:{snapshot.consecutive_losses}'
    return None


class StrategyPerformanceGuard:
    def __init__(self, db_url: str, session_start=None):
        self.engine = create_engine(db_url)
        self.session_start = session_start
        # Registro de bloqueos activos: "strategy" o "asset:strategy" → blocked_at
        self._blocks: Dict[str, datetime] = {}
        # Registro de probation: "strategy" → trades restantes en probation
        self._probation: Dict[str, int] = {}

    def _fetch_recent_rows(self, query: str, params: dict) -> list:
        with self.engine.connect() as conn:
            rows = conn.execute(text(query), params).fetchall()
        return [dict(row._mapping) for row in rows]

    def set_session_start(self, session_start):
        """Actualiza el scope de sesión para que solo mire trades de la sesión activa."""
        self.session_start = session_start
        # Reset blocks y probation al cambiar de sesión
        self._blocks.clear()
        self._probation.clear()

    def is_on_probation(self, strategy: str) -> bool:
        """Retorna True si la estrategia está en periodo de prueba post-cooldown."""
        return self._probation.get(strategy, 0) > 0

    def get_probation_remaining(self, strategy: str) -> int:
        """Retorna cuántos trades de prueba quedan para esta estrategia."""
        return self._probation.get(strategy, 0)

    def record_probation_trade(self, strategy: str):
        """Registra un trade ejecutado durante probation, decrementando contador."""
        if strategy in self._probation and self._probation[strategy] > 0:
            self._probation[strategy] -= 1
            remaining = self._probation[strategy]
            if remaining == 0:
                del self._probation[strategy]
                logger.info(f'GUARD PROBATION END: {strategy} completed probation, full size restored')
            else:
                logger.info(f'GUARD PROBATION: {strategy} {remaining} trades remaining at reduced size')

    def _is_block_expired(self, key: str) -> bool:
        """Verifica si un bloqueo ha expirado por cooldown temporal."""
        blocked_at = self._blocks.get(key)
        if blocked_at is None:
            return True
        elapsed = datetime.now(timezone.utc) - blocked_at
        if elapsed >= timedelta(hours=GUARD_COOLDOWN_HOURS):
            # Bloqueo expirado → entrar en probation
            del self._blocks[key]
            # Extraer el nombre de la estrategia del key
            strategy_name = key.split(':')[-1] if ':' in key else key
            if strategy_name not in self._probation:
                self._probation[strategy_name] = PROBATION_TRADES
            logger.warning(
                f'GUARD COOLDOWN EXPIRED: {key} unblocked after {GUARD_COOLDOWN_HOURS}h, '
                f'entering probation ({PROBATION_TRADES} trades at 50% size)'
            )
            return True
        return False

    def _register_block(self, key: str, reason: str):
        """Registra un bloqueo con timestamp para el cooldown temporal."""
        if key not in self._blocks:
            self._blocks[key] = datetime.now(timezone.utc)
            logger.warning(f'GUARD BLOCK: {key} blocked for {GUARD_COOLDOWN_HOURS}h — {reason}')

    def assess_signal(self, asset: str, strategy: str) -> Optional[str]:
        # ── Verificar bloqueos existentes con cooldown temporal ──
        asset_key = f'{asset}:{strategy}'
        strategy_key = strategy

        # Si hay bloqueo activo y NO ha expirado, mantener bloqueo
        if asset_key in self._blocks and not self._is_block_expired(asset_key):
            remaining_h = (
                timedelta(hours=GUARD_COOLDOWN_HOURS)
                - (datetime.now(timezone.utc) - self._blocks[asset_key])
            ).total_seconds() / 3600
            return f'ASSET_STRATEGY_COOLDOWN:{asset}:{strategy}:{remaining_h:.1f}h_left'

        if strategy_key in self._blocks and not self._is_block_expired(strategy_key):
            remaining_h = (
                timedelta(hours=GUARD_COOLDOWN_HOURS)
                - (datetime.now(timezone.utc) - self._blocks[strategy_key])
            ).total_seconds() / 3600
            return f'STRATEGY_COOLDOWN:{strategy}:{remaining_h:.1f}h_left'

        # ── Evaluar trades recientes (solo ventana temporal) ──
        session_filter = ''
        window_filter = ' AND timestamp_close >= :window_start'
        window_start = datetime.now(timezone.utc) - timedelta(hours=GUARD_WINDOW_HOURS)

        params: dict = {
            'asset': asset, 'strategy': strategy,
            'limit': ASSET_STRATEGY_LOOKBACK, 'window_start': window_start,
        }
        if self.session_start:
            session_filter = ' AND timestamp_close >= :session_start'
            params['session_start'] = self.session_start

        asset_rows = self._fetch_recent_rows(
            f"""
            SELECT pnl
            FROM trades
            WHERE status = 'CLOSED' AND asset = :asset AND strategy = :strategy{session_filter}{window_filter}
            ORDER BY timestamp_close DESC
            LIMIT :limit
            """,
            params,
        )
        asset_snapshot = summarize_closed_trades(asset_rows)
        asset_reason = should_block_asset_strategy(asset_snapshot)
        if asset_reason:
            self._register_block(asset_key, asset_reason)
            return asset_reason

        strategy_params: dict = {
            'strategy': strategy, 'limit': STRATEGY_LOOKBACK,
            'window_start': window_start,
        }
        strategy_session_filter = ''
        if self.session_start:
            strategy_session_filter = ' AND timestamp_close >= :session_start'
            strategy_params['session_start'] = self.session_start

        strategy_rows = self._fetch_recent_rows(
            f"""
            SELECT pnl
            FROM trades
            WHERE status = 'CLOSED' AND strategy = :strategy{strategy_session_filter}{window_filter}
            ORDER BY timestamp_close DESC
            LIMIT :limit
            """,
            strategy_params,
        )
        strategy_snapshot = summarize_closed_trades(strategy_rows)
        strategy_reason = should_block_strategy(strategy_snapshot)
        if strategy_reason:
            self._register_block(strategy_key, strategy_reason)
            return strategy_reason

        return None