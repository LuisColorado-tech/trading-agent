"""
btc_direction_executor.py — Paper executor para BTC Up/Down 15m de Polymarket.

Persiste trades en la tabla `btc_direction_trades` de la misma DB PostgreSQL
que el pipeline existente. Completamente aislado: no lee ni modifica ninguna
tabla del pipeline principal.

Garantías:
  - Idempotente: nunca abre más de 1 posición por slot_ts.
  - Límite de posiciones abiertas simultáneas.
  - Cierra automáticamente posiciones de slots pasados consultando el outcome.
"""
import os
import sys
import time
import uuid
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import create_engine, text

sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv

load_dotenv('/opt/trading/config/.env')

_CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS btc_direction_trades (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slot_ts         BIGINT NOT NULL,
    market_slug     VARCHAR NOT NULL,
    condition_id    VARCHAR NOT NULL,
    direction       VARCHAR(4) NOT NULL,
    token_id        VARCHAR NOT NULL,
    entry_price     NUMERIC(10, 4) NOT NULL,
    shares          NUMERIC(14, 4) NOT NULL,
    cost_usdc       NUMERIC(10, 4) NOT NULL,
    btc_5m_pct      NUMERIC(8, 4),
    signal_reason   TEXT,
    confidence      NUMERIC(5, 3),
    outcome         VARCHAR(4),
    pnl_usdc        NUMERIC(10, 4),
    status          VARCHAR(8) DEFAULT 'OPEN',
    paper_trade     BOOLEAN DEFAULT TRUE,
    timestamp_open  TIMESTAMPTZ DEFAULT NOW(),
    timestamp_close TIMESTAMPTZ
)"""

_CREATE_IDX_SLOT   = "CREATE INDEX IF NOT EXISTS idx_btc_dir_slot   ON btc_direction_trades(slot_ts)"
_CREATE_IDX_STATUS = "CREATE INDEX IF NOT EXISTS idx_btc_dir_status ON btc_direction_trades(status)"


def _db_url() -> str:
    return (
        f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
        f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT', '5432')}"
        f"/{os.getenv('POSTGRES_DB')}"
    )


class BtcDirectionExecutor:
    """Paper executor para mercados BTC Up/Down 15m de Polymarket."""

    def __init__(self, config: dict):
        self.cfg          = config
        self.paper_mode   = config.get('paper_trading', True)
        self.initial_bal  = config.get('initial_paper_balance', 500.0)
        risk              = config.get('risk', {})
        self.max_trade    = risk.get('max_trade_usdc', 20.0)
        self.max_open     = risk.get('max_open_positions', 2)

        self.engine = create_engine(_db_url())
        self._ensure_table()
        self._paper_balance = self._compute_balance()

    # ── Setup ────────────────────────────────────────────────────────────────

    def _ensure_table(self):
        with self.engine.begin() as conn:
            conn.execute(text(_CREATE_TABLE_SQL))
            conn.execute(text(_CREATE_IDX_SLOT))
            conn.execute(text(_CREATE_IDX_STATUS))

    def _compute_balance(self) -> float:
        """
        Recalcula el balance paper desde la DB:
          inicial + P&L realizado - costos de posiciones abiertas
        """
        try:
            with self.engine.connect() as conn:
                locked = conn.execute(text(
                    "SELECT COALESCE(SUM(cost_usdc), 0) FROM btc_direction_trades "
                    "WHERE status = 'OPEN' AND paper_trade = TRUE"
                )).scalar() or 0.0

                realized_pnl = conn.execute(text(
                    "SELECT COALESCE(SUM(pnl_usdc), 0) FROM btc_direction_trades "
                    "WHERE status = 'CLOSED' AND paper_trade = TRUE"
                )).scalar() or 0.0

            return float(self.initial_bal) + float(realized_pnl) - float(locked)
        except Exception as e:
            logger.warning(f'EXECUTOR: Error calculando balance, usando inicial: {e}')
            return float(self.initial_bal)

    # ── Propiedades ──────────────────────────────────────────────────────────

    @property
    def paper_balance(self) -> float:
        return self._paper_balance

    # ── Checks de idempotencia y límites ─────────────────────────────────────

    def already_traded_slot(self, slot_ts: int) -> bool:
        """True si ya hay una posición (OPEN o CLOSED) en este slot."""
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT 1 FROM btc_direction_trades WHERE slot_ts = :s LIMIT 1"),
                {'s': slot_ts},
            ).fetchone()
        return row is not None

    def count_open_positions(self) -> int:
        with self.engine.connect() as conn:
            return int(conn.execute(
                text("SELECT COUNT(*) FROM btc_direction_trades WHERE status = 'OPEN'")
            ).scalar() or 0)

    # ── Ejecución ────────────────────────────────────────────────────────────

    def execute(self, signal: dict, market: dict) -> dict:
        """
        Registra un paper trade en la DB.

        Args:
            signal: output de BtcDirectionStrategy.evaluate()
            market: output de BtcDirectionFeed.get_current_market()

        Returns:
            dict con executed (bool) y detalles del trade o reason si falla.
        """
        if not self.paper_mode:
            raise NotImplementedError('Live mode no implementado')

        direction = signal.get('direction')
        if not direction:
            return {'executed': False, 'reason': 'NO_SIGNAL'}

        slot_ts = market['slot_ts']

        if self.already_traded_slot(slot_ts):
            return {'executed': False, 'reason': 'ALREADY_TRADED_SLOT'}

        if self.count_open_positions() >= self.max_open:
            return {'executed': False, 'reason': 'MAX_OPEN_POSITIONS'}

        entry_price = signal['entry_price']
        if entry_price <= 0:
            return {'executed': False, 'reason': 'INVALID_PRICE'}

        # Tamaño: el menor entre max_trade_usdc y 4% del balance
        trade_usdc = min(self.max_trade, self._paper_balance * 0.04)
        trade_usdc = max(trade_usdc, 5.0)  # mínimo del mercado: 5 USDC

        if trade_usdc > self._paper_balance:
            return {'executed': False, 'reason': 'INSUFFICIENT_BALANCE'}

        shares = round(trade_usdc / entry_price, 4)
        cost   = round(shares * entry_price, 4)

        trade_id = str(uuid.uuid4())

        with self.engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO btc_direction_trades
                    (id, slot_ts, market_slug, condition_id, direction,
                     token_id, entry_price, shares, cost_usdc,
                     btc_5m_pct, signal_reason, confidence, paper_trade, timestamp_open)
                VALUES
                    (:id, :slot_ts, :slug, :cid, :dir,
                     :token_id, :entry_price, :shares, :cost,
                     :btc_5m_pct, :reason, :conf, TRUE, NOW())
            """), {
                'id':          trade_id,
                'slot_ts':     slot_ts,
                'slug':        market['slug'],
                'cid':         market['condition_id'],
                'dir':         direction,
                'token_id':    signal['token_id'],
                'entry_price': entry_price,
                'shares':      shares,
                'cost':        cost,
                'btc_5m_pct':  signal.get('btc_5m_pct', 0.0),
                'reason':      signal.get('reasoning', ''),
                'conf':        signal.get('confidence', 0.0),
            })

        self._paper_balance -= cost

        logger.info(
            f'EXECUTOR: PAPER {direction} {market["slug"]} | '
            f'shares={shares:.2f} @ {entry_price:.3f} = ${cost:.2f} USDC | '
            f'balance=${self._paper_balance:.2f}'
        )

        return {
            'executed':    True,
            'trade_id':    trade_id,
            'direction':   direction,
            'shares':      shares,
            'cost_usdc':   cost,
            'entry_price': entry_price,
        }

    # ── Cierre de posiciones expiradas ────────────────────────────────────────

    def close_expired(self, feed) -> list[dict]:
        """
        Cierra posiciones de slots ya terminados consultando el outcome en Polymarket.

        Args:
            feed: instancia de BtcDirectionFeed

        Returns:
            Lista de dicts con info de los trades cerrados (puede estar vacía).
        """
        closed = []

        with self.engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT id, slot_ts, condition_id, direction, shares, cost_usdc "
                "FROM btc_direction_trades WHERE status = 'OPEN'"
            )).fetchall()

        now = time.time()
        for row in rows:
            trade    = dict(row._mapping)
            slot_end = trade['slot_ts'] + 900
            # Esperar al menos 30s después del cierre del slot antes de consultar
            if now < slot_end + 30:
                continue

            outcome = feed.get_market_outcome(trade['condition_id'])
            if outcome is None:
                continue  # Aún no resuelto o error temporal

            direction = trade['direction']
            shares    = float(trade['shares'])
            cost      = float(trade['cost_usdc'])
            won       = (direction == outcome)

            # P&L paper: ganó → recibe $1 por share  |  perdió → pierde el costo
            pnl = round(shares * 1.0 - cost, 4) if won else round(-cost, 4)

            with self.engine.begin() as conn:
                conn.execute(text("""
                    UPDATE btc_direction_trades
                    SET status = 'CLOSED', outcome = :outcome, pnl_usdc = :pnl,
                        timestamp_close = NOW()
                    WHERE id = :id
                """), {'outcome': outcome, 'pnl': pnl, 'id': str(trade['id'])})

            # Liberar capital bloqueado y sumar P&L
            self._paper_balance += cost + pnl

            icon = '✓ WON' if won else '✗ LOST'
            logger.info(
                f'EXECUTOR: CLOSED [{icon}] {direction}→{outcome} '
                f'slug=btc-updown-15m-{trade["slot_ts"]} '
                f'P&L=${pnl:+.2f} balance=${self._paper_balance:.2f}'
            )

            closed.append({
                'trade_id':  str(trade['id']),
                'direction': direction,
                'outcome':   outcome,
                'pnl':       pnl,
                'won':       won,
            })

        return closed

    # ── Estadísticas ─────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Retorna estadísticas acumuladas del agente."""
        with self.engine.connect() as conn:
            row = conn.execute(text("""
                SELECT
                    COUNT(*)                                            AS total,
                    SUM(CASE WHEN status  = 'OPEN'    THEN 1 ELSE 0 END) AS open_count,
                    SUM(CASE WHEN status  = 'CLOSED'  THEN 1 ELSE 0 END) AS closed_count,
                    SUM(CASE WHEN direction = outcome  THEN 1 ELSE 0 END) AS wins,
                    COALESCE(SUM(pnl_usdc), 0)                          AS total_pnl
                FROM btc_direction_trades
                WHERE paper_trade = TRUE
            """)).fetchone()

        total, open_cnt, closed_cnt, wins, pnl = row
        total      = int(total or 0)
        open_cnt   = int(open_cnt or 0)
        closed_cnt = int(closed_cnt or 0)
        wins       = int(wins or 0)
        pnl        = float(pnl or 0.0)
        win_rate   = (wins / closed_cnt * 100.0) if closed_cnt > 0 else 0.0

        return {
            'total_trades':  total,
            'open':          open_cnt,
            'closed':        closed_cnt,
            'wins':          wins,
            'win_rate_pct':  round(win_rate, 1),
            'total_pnl':     round(pnl, 2),
            'paper_balance': round(self._paper_balance, 2),
        }
