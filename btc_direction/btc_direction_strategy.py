"""
btc_direction_strategy.py — Señal de dirección para mercados Up/Down de Polymarket.

Soporta BTC, ETH, SOL, XRP usando señales de la tabla `signals` de la DB.
Fallback a CCXT OHLCV para BTC si la DB no tiene señales recientes.

Señal combinada:
  1. Momentum del asset (señales DB últimos 10m, o 5 velas OHLCV para BTC):
       mayoría BUY  →  bias Up
       mayoría SELL →  bias Down
       sin claridad →  no operar
  2. Edge de precio en Polymarket:
       si precio_del_outcome < 0.50  →  el mercado subvalora nuestra dirección
       edge = 0.50 - precio_polymarket
       Requerido mínimo: 0.03

Solo se genera señal si ambas condiciones se cumplen.
"""
import os
import sys

import ccxt
from loguru import logger
from sqlalchemy import create_engine, text

sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv

load_dotenv('/opt/trading/config/.env')

# Pares CCXT por asset (fallback OHLCV, solo aplica para BTC actualmente)
_CCXT_PAIRS: dict[str, str] = {
    'BTC': 'BTC/USDT',
    'ETH': 'ETH/USDT',
    'SOL': 'SOL/USDT',
    'XRP': 'XRP/USDT',
}


def _db_url() -> str:
    return (
        f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
        f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT', '5432')}"
        f"/{os.getenv('POSTGRES_DB')}"
    )


class BtcDirectionStrategy:
    """Genera señal de dirección para mercados Up/Down de Polymarket (multi-asset)."""

    def __init__(self, config: dict):
        btc_cfg = config.get('btc_data', {})
        self.exchange_id = btc_cfg.get('exchange', 'kraken')
        self.timeframe   = btc_cfg.get('timeframe', '1m')
        self.lookback    = btc_cfg.get('lookback_candles', 10)
        self.fallback_id = btc_cfg.get('fallback_exchange', 'okx')

        risk_cfg = config.get('risk', {})
        self.momentum_threshold = risk_cfg.get('momentum_threshold_pct', 0.15) / 100.0
        self.min_edge           = risk_cfg.get('min_price_edge', 0.03)

        self._exchange = None
        self._fallback = None
        self._engine   = create_engine(_db_url())

    # ── Señales desde DB (multi-asset) ──────────────────────────────────────

    def _get_momentum_from_db(self, asset: str) -> tuple:
        """
        Obtiene dirección del momentum desde la tabla `signals` de la DB.
        Consulta los últimos 10 minutos de señales para el asset dado.
        Returns: (direction, strength, reasoning)
            direction: 'Up' | 'Down' | None
        """
        try:
            with self._engine.connect() as conn:
                rows = conn.execute(text("""
                    SELECT direction, COUNT(*) as cnt
                    FROM signals
                    WHERE asset = :asset
                      AND timestamp > now() - interval '10 minutes'
                    GROUP BY direction
                    ORDER BY cnt DESC
                """), {'asset': asset}).fetchall()
        except Exception as e:
            logger.warning(f'STRATEGY: DB signals error para {asset}: {e}')
            return None, 0.0, f'DB error: {e}'

        if not rows:
            return None, 0.0, f'Sin señales DB últimos 10m para {asset}'

        counts = {r[0]: int(r[1]) for r in rows}
        buys    = counts.get('BUY', 0)
        sells   = counts.get('SELL', 0)
        reasoning = f'{asset} DB 10m: BUY={buys} SELL={sells} NEUTRAL={counts.get("NEUTRAL", 0)}'

        directional = buys + sells
        if directional == 0:
            return None, 0.0, f'Solo NEUTRAL | {reasoning}'

        buy_ratio  = buys  / directional
        sell_ratio = sells / directional
        threshold  = 0.60

        if buy_ratio >= threshold:
            strength = min((buy_ratio - 0.50) / 0.25, 1.0)
            return 'Up', round(strength, 3), reasoning
        if sell_ratio >= threshold:
            strength = min((sell_ratio - 0.50) / 0.25, 1.0)
            return 'Down', round(strength, 3), reasoning

        return None, 0.0, f'Sin mayoría clara ({buy_ratio:.0%} BUY) | {reasoning}'

    # ── Acceso a exchange (fallback BTC OHLCV) ───────────────────────────────

    def _get_exchange(self) -> ccxt.Exchange:
        if self._exchange is None:
            cls = getattr(ccxt, self.exchange_id)
            self._exchange = cls({'enableRateLimit': True})
        return self._exchange

    def _get_fallback(self) -> ccxt.Exchange:
        if self._fallback is None:
            cls = getattr(ccxt, self.fallback_id)
            self._fallback = cls({'enableRateLimit': True})
        return self._fallback

    def _get_ohlcv_momentum(self, asset: str) -> tuple:
        """
        Momentum via CCXT OHLCV. Fallback cuando la DB no tiene señales.
        Returns: (direction, strength, reasoning, pct_change)
        """
        pair = _CCXT_PAIRS.get(asset, 'BTC/USDT')
        closes = None
        for ex in (self._get_exchange(), self._get_fallback()):
            try:
                candles = ex.fetch_ohlcv(pair, self.timeframe, limit=self.lookback)
                if candles and len(candles) >= 5:
                    closes = [float(c[4]) for c in candles]
                    break
            except Exception as e:
                logger.warning(f'STRATEGY: Error OHLCV {asset} en {ex.id}: {e}')

        if not closes:
            return None, 0.0, f'Sin OHLCV para {asset}', 0.0

        pct = (closes[-1] - closes[-5]) / closes[-5] * 100.0
        threshold_pct = self.momentum_threshold * 100.0

        if pct > threshold_pct:
            st = min(pct / (threshold_pct * 2.0), 1.0)
            return 'Up', st, f'{asset}_OHLCV_5m={pct:+.3f}%', pct
        if pct < -threshold_pct:
            st = min(abs(pct) / (threshold_pct * 2.0), 1.0)
            return 'Down', st, f'{asset}_OHLCV_5m={pct:+.3f}%', pct
        return None, 0.0, f'{asset}_OHLCV_5m={pct:+.3f}% (umbral +-{threshold_pct:.2f}%)', pct

    # ── Evaluación principal ─────────────────────────────────────────────────

    def evaluate(self, market: dict) -> dict:
        """
        Evalúa el mercado y devuelve señal de trading.

        Args:
            market: dict de BtcMultiFeed con price_up/down, token_up/down, asset, etc.

        Returns:
            dict con direction, confidence, btc_5m_pct, entry_price, token_id, edge, reasoning, asset
        """
        asset      = market.get('asset', 'BTC')
        price_up   = market['price_up']
        price_down = market['price_down']

        # ── 1. Momentum (DB primero, CCXT fallback solo para BTC) ────────────
        momentum_dir, momentum_strength, reasoning_src = self._get_momentum_from_db(asset)
        ohlcv_pct = 0.0

        if momentum_dir is None and asset == 'BTC':
            momentum_dir, momentum_strength, reasoning_src, ohlcv_pct = \
                self._get_ohlcv_momentum(asset)

        if momentum_dir is None:
            return self._no_signal(f'Sin momentum claro: {reasoning_src}')

        # ── 2. Edge de precio en Polymarket ──────────────────────────────────
        entry_price = price_up   if momentum_dir == 'Up'   else price_down
        token_id    = market['token_up'] if momentum_dir == 'Up' else market['token_down']
        edge        = 0.50 - entry_price

        if edge < self.min_edge:
            return self._no_signal(
                f'Edge insuficiente: precio={entry_price:.3f} edge={edge:.3f} '
                f'(minimo {self.min_edge:.3f}) dir={momentum_dir}'
            )

        # ── 3. Confianza combinada (50% momentum + 50% edge) ─────────────────
        edge_strength = min(edge / 0.15, 1.0)
        confidence    = round(0.5 * momentum_strength + 0.5 * edge_strength, 3)

        reasoning = (
            f'{asset} {momentum_dir} conf={confidence:.2f} | '
            f'{reasoning_src} | '
            f'precio_poly={entry_price:.3f} edge={edge:+.3f}'
        )

        logger.info(f'STRATEGY: SENAL {asset} {momentum_dir} conf={confidence:.2f} | {reasoning}')

        return {
            'direction':   momentum_dir,
            'confidence':  confidence,
            'btc_5m_pct':  round(ohlcv_pct, 4),
            'entry_price': entry_price,
            'token_id':    token_id,
            'edge':        round(edge, 4),
            'reasoning':   reasoning,
            'asset':       asset,
        }

    @staticmethod
    def _no_signal(reason: str) -> dict:
        logger.debug(f'STRATEGY: No signal -- {reason}')
        return {
            'direction':   None,
            'confidence':  0.0,
            'btc_5m_pct':  0.0,
            'entry_price': 0.0,
            'token_id':    '',
            'edge':        0.0,
            'reasoning':   reason,
            'asset':       '',
        }
