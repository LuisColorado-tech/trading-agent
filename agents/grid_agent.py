"""
GridAgent — Gestor de estado y ejecución del Grid Bot.

Responsabilidades:
  1. Detectar régimen RANGE/CHOPPY por asset
  2. Calcular grid y detectar precio cerca de un nivel
  3. Verificar que no hay orden ya abierta en ese nivel
  4. Abrir trade (paper) y persistir en DB (strategy='GRID_BOT')
  5. Publicar evento Redis para dashboard

No gestiona el cierre — TradeMonitor ya lo hace (SL/TP estándar).
El trailing está desactivado para GRID_BOT en trade_monitor.py.

Integración en run_trading.py:
    grid_agent = GridAgent(db_url)
    ...
    grid_agent.run_cycle(ASSETS, portfolio, session)
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

import redis as redis_lib
from loguru import logger
from sqlalchemy import create_engine, text

sys.path.insert(0, '/opt/trading')

from agents.indicators import IndicatorEngine
from core.asset_profiles import get_profile, hour_allowed
from core.market_regime import classify_market_regime
from data.market_feed import MarketFeed, ASSET_MAP
from strategies.grid_bot import GridBotStrategy, GridConfig, GridLevel
from risk.risk_manager import MAX_RISK_PER_TRADE_PCT

# ── Parámetros del grid agent ──────────────────────────────────────
GRID_MAX_PER_ASSET   = 2     # máx trades GRID_BOT abiertos simultáneos por asset
GRID_MAX_TOTAL       = 3     # máx trades GRID_BOT abiertos en total (no bloquear Trend)
GRID_RISK_FRACTION   = 0.40  # fracción del MAX_RISK normal por orden grid (40%)
GRID_RISK_FRACTION_TREND_UP = 0.25  # menor exposición si 1h muestra tendencia alcista
GRID_RISK_FRACTION_CHOPPY  = 0.20  # mínimo en mercados laterales erráticos
GRID_TIMEFRAME       = '15m' # timeframe para calcular rango y régimen
GRID_SL_COOLDOWN_MIN = 30    # minutos de cooldown tras SL (belt-and-suspenders con Redis)
# ──────────────────────────────────────────────────────────────────


class GridAgent:
    """Gestor del grid bot. Llamar desde el loop principal con run_cycle()."""

    def __init__(self, db_url: str):
        self.engine   = create_engine(db_url)
        self.feed     = MarketFeed()
        self.strategy = GridBotStrategy()
        self.redis    = redis_lib.Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            password=os.getenv('REDIS_PASSWORD') or None,
            decode_responses=True,
        )
        # Cache de grid configs calculadas (se refresca cada ciclo solo si cambia)
        self._grid_cache: Dict[str, GridConfig] = {}

    # ── Punto de entrada principal ─────────────────────────────────

    def run_cycle(self, assets: List[str], portfolio: dict, session: dict) -> List[dict]:
        """
        Evalúa todos los assets y abre órdenes grid si corresponde.

        Returns:
            Lista de dicts con trades abiertos en este ciclo.
        """
        opened = []
        total_open = self._count_open_grid_trades()

        if total_open >= GRID_MAX_TOTAL:
            logger.debug(f'GridAgent: límite total alcanzado ({total_open}/{GRID_MAX_TOTAL})')
            return []

        for asset in assets:
            if len(opened) + total_open >= GRID_MAX_TOTAL:
                break

            result = self._evaluate_asset(asset, portfolio, session)
            if result:
                opened.append(result)
                total_open += 1

        if opened:
            logger.info(f'GridAgent ciclo: {len(opened)} trade(s) abiertos — '
                        f'{[o["asset"] for o in opened]}')
        return opened

    # ── Evaluación por asset ───────────────────────────────────────

    def _evaluate_asset(self, asset: str, portfolio: dict, session: dict) -> Optional[dict]:
        try:
            # 1. Filtro horario
            hour_utc = datetime.now(timezone.utc).hour
            if not hour_allowed(asset, hour_utc):
                return None

            # 2. Cooldown Redis (ahora también seteado por TradeMonitor para GRID_BOT)
            if self.redis.ttl(f'cooldown:{asset}') > 0:
                return None

            # 2b. Belt-and-suspenders: verificar DB por SLs recientes de GRID_BOT (mismo asset)
            if self._recent_grid_sl(asset):
                return None

            # 3. Obtener datos e indicadores (15m + 1h para confirmación MTF)
            df = self.feed.get_latest(asset, GRID_TIMEFRAME, n=100)
            if df.empty or len(df) < 35:
                return None

            ind = IndicatorEngine.calculate(df, asset, GRID_TIMEFRAME)
            if ind is None:
                return None

            df_1h = self.feed.get_latest(asset, '1h', n=100)
            ind_1h = None
            if not df_1h.empty and len(df_1h) >= 50:
                ind_1h = IndicatorEngine.calculate(df_1h, asset, '1h')

            # 4. Verificar régimen RANGE o CHOPPY (con confirmación MTF 1h)
            # Si el 1h muestra tendencia clara, el RANGE en 15m es consolidación
            # dentro de tendencia → Grid Bot quedaría atrapado contra el movimiento mayor.
            profile = get_profile(asset)
            regime_1h = classify_market_regime(ind_1h) if ind_1h is not None else None
            regime = classify_market_regime(ind, ind_htf=ind_1h)
            if not regime.allow_grid:
                return None

            # 4b. Umbrales de volatilidad por asset (más estrictos que el umbral global)
            # Cada asset tiene su propia "anchura" de rango real. Si bb_width o atr_pct
            # superan el umbral del perfil, el mercado está demasiado en movimiento.
            if ind.bb_width > profile.grid_bb_width_max or ind.atr_pct > profile.grid_atr_pct_max:
                logger.debug(
                    f'GridAgent {asset}: umbral RANGE superado '
                    f'bb_width={ind.bb_width:.4f}>{profile.grid_bb_width_max} '
                    f'atr_pct={ind.atr_pct:.5f}>{profile.grid_atr_pct_max}'
                )
                return None

            # 5. Calcular grid con parámetros del perfil del asset
            grid = self.strategy.calculate_grid(
                ind, df,
                n_levels=profile.grid_levels,
                tp_ratio=profile.grid_tp_ratio,
                sl_ratio=profile.grid_sl_ratio,
                min_rr=profile.grid_min_rr,
                range_candles=profile.grid_range_candles,
                exchange=ASSET_MAP.get(asset, {}).get('exchange', 'kraken'),
            )
            if grid is None:
                return None

            self._grid_cache[asset] = grid

            # 5b. Detectar si el precio rompió el rango → invalidar grid cache
            if ind.close > grid.range_high * 1.005 or ind.close < grid.range_low * 0.995:
                self._grid_cache.pop(asset, None)
                logger.debug(f'GridAgent {asset}: price broke range, invalidating grid cache')
                return None

            # 6. ¿El precio está cerca de un nivel de entrada?
            level = self.strategy.nearest_level(grid, ind.close)
            if level is None:
                return None

            # 7. ¿Ya hay un trade abierto en este nivel?
            if self._level_occupied(asset, level.price):
                logger.debug(f'GridAgent {asset}: nivel {level.price:.4f} ya ocupado')
                return None

            # 8. ¿Límite por asset?
            if self._count_open_grid_trades(asset) >= GRID_MAX_PER_ASSET:
                return None

            # 9. Tamaño de posición con risk fraction dinámico según régimen 1h
            total_balance = portfolio.get('total_balance', 10000.0)
            rf = GRID_RISK_FRACTION
            if regime_1h is not None:
                rf_name = regime_1h.name if hasattr(regime_1h, 'name') else str(regime_1h)
                if 'TREND_UP' in rf_name or 'BREAKOUT_UP' in rf_name:
                    rf = GRID_RISK_FRACTION_TREND_UP   # 0.25 → menor exposición en mercado alcista
                elif 'CHOPPY' in rf_name:
                    rf = GRID_RISK_FRACTION_CHOPPY     # 0.20 → mínimo en mercados erráticos
            risk_amount   = total_balance * MAX_RISK_PER_TRADE_PCT * rf
            risk_per_unit = abs(level.price - level.sl)
            if risk_per_unit < 1e-10:
                return None
            position_size = risk_amount / risk_per_unit

            # 10. Abrir trade
            trade_id = self._open_trade(
                asset=asset,
                level=level,
                grid=grid,
                entry_price=ind.close,
                position_size=round(position_size, 6),
                session=session,
                regime_name=regime.name,
                regime_1h_name=regime_1h.name if regime_1h is not None else 'N/A',
            )

            logger.info(
                f'GRID OPEN: {asset} {level.direction} entry={ind.close:.4f} '
                f'nivel={level.price:.4f} TP={level.tp:.4f} SL={level.sl:.4f} '
                f'RR={level.rr:.2f} size={position_size:.4f} '
                f'regime={regime.name}{" (1h=" + regime_1h.name + ")" if regime_1h is not None else ""}'
            )
            return {
                'trade_id': trade_id,
                'asset': asset,
                'direction': level.direction,
                'entry_price': ind.close,
                'grid_level': level.price,
                'tp': level.tp,
                'sl': level.sl,
                'rr': level.rr,
                'regime': regime.name,
            }

        except Exception as e:
            logger.error(f'GridAgent._evaluate_asset {asset}: {e}')
            return None

    def _recent_grid_sl(self, asset: str) -> bool:
        """True si GRID_BOT tuvo un SL/TRAILING_STOP en este asset en los últimos GRID_SL_COOLDOWN_MIN minutos."""
        with self.engine.connect() as conn:
            row = conn.execute(
                text(f"""
                    SELECT COUNT(*) FROM trades
                    WHERE asset = :asset AND strategy = 'GRID_BOT' AND status = 'CLOSED'
                    AND close_reason IN ('STOP_LOSS', 'TRAILING_STOP')
                    AND timestamp_close > NOW() - INTERVAL '{GRID_SL_COOLDOWN_MIN} minutes'
                """),
                {'asset': asset},
            ).fetchone()
        return int(row[0]) > 0 if row else False

    # ── DB helpers ─────────────────────────────────────────────────

    def _count_open_grid_trades(self, asset: str = None) -> int:
        with self.engine.connect() as conn:
            if asset:
                row = conn.execute(
                    text("SELECT COUNT(*) FROM trades "
                         "WHERE status='OPEN' AND strategy='GRID_BOT' AND asset=:a"),
                    {'a': asset},
                ).fetchone()
            else:
                row = conn.execute(
                    text("SELECT COUNT(*) FROM trades "
                         "WHERE status='OPEN' AND strategy='GRID_BOT'")
                ).fetchone()
        return int(row[0]) if row else 0

    def _level_occupied(self, asset: str, level_price: float,
                        tolerance: float = 0.002) -> bool:
        """True si ya hay una orden abierta a ±0.2% de este nivel."""
        with self.engine.connect() as conn:
            rows = conn.execute(
                text("SELECT entry_price FROM trades "
                     "WHERE status='OPEN' AND strategy='GRID_BOT' AND asset=:a"),
                {'a': asset},
            ).fetchall()
        for row in rows:
            if abs(float(row.entry_price) - level_price) / level_price < tolerance:
                return True
        return False

    def _open_trade(self, asset: str, level: GridLevel, grid: GridConfig,
                    entry_price: float, position_size: float, session: dict,
                    regime_name: str = 'RANGE', regime_1h_name: str = 'N/A') -> str:
        trade_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        initial_risk = abs(entry_price - level.sl)

        metadata = {
            'grid_level_idx':   level.level_idx,
            'grid_level_price': round(level.price, 8),
            'grid_range_low':   round(grid.range_low, 8),
            'grid_range_high':  round(grid.range_high, 8),
            'grid_spacing':     round(grid.grid_spacing, 8),
            'grid_range_pct':   round(grid.range_pct * 100, 3),
            'initial_risk':     round(initial_risk, 8),
            'paper_session_id':   str(session['id']) if session else None,
            'paper_session_name': session.get('session_name') if session else None,
            'regime':    regime_name,
            'regime_1h': regime_1h_name,
        }

        with self.engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO trades
                        (id, asset, side, strategy, entry_price, stop_loss,
                         take_profit, position_size, position_pct,
                         paper_trade, timestamp_open, metadata)
                    VALUES
                        (:id, :asset, :side, 'GRID_BOT', :entry, :sl,
                         :tp, :size, 0,
                         true, :ts, CAST(:meta AS jsonb))
                """),
                {
                    'id':    trade_id,
                    'asset': asset,
                    'side':  level.direction,
                    'entry': entry_price,
                    'sl':    level.sl,
                    'tp':    level.tp,
                    'size':  position_size,
                    'ts':    now,
                    'meta':  json.dumps(metadata),
                },
            )

        self.redis.publish('trades:executed', json.dumps({
            'trade_id': trade_id,
            'asset':    asset,
            'side':     level.direction,
            'price':    entry_price,
            'strategy': 'GRID_BOT',
        }))

        return trade_id

    # ── Utilidades ─────────────────────────────────────────────────

    def summary(self) -> dict:
        """Estado actual del grid: trades abiertos por asset."""
        with self.engine.connect() as conn:
            rows = conn.execute(
                text("SELECT asset, side, entry_price, stop_loss, take_profit, metadata "
                     "FROM trades WHERE status='OPEN' AND strategy='GRID_BOT' "
                     "ORDER BY asset, entry_price DESC")
            ).fetchall()

        result: Dict[str, list] = {}
        for r in rows:
            if r.asset not in result:
                result[r.asset] = []
            meta = json.loads(r.metadata) if r.metadata else {}
            result[r.asset].append({
                'side':        r.side,
                'entry':       float(r.entry_price),
                'sl':          float(r.stop_loss),
                'tp':          float(r.take_profit),
                'grid_level':  meta.get('grid_level_price'),
                'range_pct':   meta.get('grid_range_pct'),
            })

        return {
            'total_open': sum(len(v) for v in result.values()),
            'by_asset':   result,
        }
