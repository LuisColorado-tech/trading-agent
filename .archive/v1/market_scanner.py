"""
MarketScanner — Agente de escaneo de mercado.
Itera sobre activos y timeframes, calcula indicadores técnicos,
detecta señales y las publica en Redis + persiste en PostgreSQL.
"""
import json
import os
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

import redis
from loguru import logger
from sqlalchemy import text

import sys
sys.path.insert(0, '/opt/trading')

from data.market_feed import MarketFeed, ASSET_MAP
from agents.indicators import IndicatorEngine, IndicatorSet

SCAN_ASSETS = list(ASSET_MAP.keys())  # Derivado de la config YAML


class MarketScanner:
    """Escanea mercado, genera indicadores, detecta señales y publica."""

    def __init__(self):
        self.feed = MarketFeed()
        self.redis = redis.Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            password=os.getenv('REDIS_PASSWORD') or None,
            decode_responses=True,
        )

    def scan(self) -> list:
        """Escaneo completo de todos los activos y timeframes."""
        all_signals = []
        for asset in SCAN_ASSETS:
            asset_info = ASSET_MAP[asset]
            timeframes = asset_info['timeframes']
            for tf in timeframes:
                try:
                    # Refresh: fetch + save + read from DB
                    df = self.feed.refresh(asset, tf, limit=250)
                    if df.empty:
                        logger.warning(f'No data for {asset}/{tf}')
                        continue

                    ind = IndicatorEngine.calculate(df, asset, tf)
                    if ind is None:
                        logger.debug(f'Not enough data for indicators: {asset}/{tf}')
                        continue

                    signals = self._detect_signals(ind)
                    if signals:
                        self._save_signals(signals)
                        self._publish_signals(signals)
                        all_signals.extend(signals)

                    # Guardar snapshot de indicadores en Redis para consulta rápida
                    self.redis.hset(
                        'indicators:latest',
                        f'{asset}:{tf}',
                        json.dumps(asdict(ind), default=str),
                    )
                except Exception as e:
                    logger.error(f'Scan error {asset}/{tf}: {e}')

        logger.info(f'Scan complete: {len(all_signals)} signals across {len(SCAN_ASSETS)} assets')
        return all_signals

    def _detect_signals(self, ind: IndicatorSet) -> list:
        """Detecta señales técnicas a partir de un IndicatorSet."""
        signals = []
        ts = datetime.now(timezone.utc).isoformat()
        base = {
            'asset': ind.asset,
            'timeframe': ind.timeframe,
            'price_at_signal': ind.close,
            'timestamp': ts,
        }

        # ── EMA Cross ──
        if ind.ema20 > ind.ema50 * 1.001:
            signals.append({
                **base,
                'id': str(uuid.uuid4()),
                'signal_type': 'EMA_CROSS_BULL',
                'indicator': 'EMA_20_50',
                'direction': 'BUY',
                'value': ind.ema20,
                'strength': min(ind.trend_strength, 1.0),
            })
        elif ind.ema20 < ind.ema50 * 0.999:
            signals.append({
                **base,
                'id': str(uuid.uuid4()),
                'signal_type': 'EMA_CROSS_BEAR',
                'indicator': 'EMA_20_50',
                'direction': 'SELL',
                'value': ind.ema20,
                'strength': min(ind.trend_strength, 1.0),
            })

        # ── RSI ──
        if ind.rsi < 30:
            signals.append({
                **base,
                'id': str(uuid.uuid4()),
                'signal_type': 'RSI_OVERSOLD',
                'indicator': 'RSI_14',
                'direction': 'BUY',
                'value': ind.rsi,
                'strength': (30 - ind.rsi) / 30,
            })
        elif ind.rsi > 70:
            signals.append({
                **base,
                'id': str(uuid.uuid4()),
                'signal_type': 'RSI_OVERBOUGHT',
                'indicator': 'RSI_14',
                'direction': 'SELL',
                'value': ind.rsi,
                'strength': (ind.rsi - 70) / 30,
            })

        # ── Bollinger Bands ──
        if ind.bb_pct < 0.05:
            signals.append({
                **base,
                'id': str(uuid.uuid4()),
                'signal_type': 'BB_LOWER_TOUCH',
                'indicator': 'BB_20_2',
                'direction': 'BUY',
                'value': ind.bb_lower,
                'strength': min(1 - ind.bb_pct, 1.0),
            })
        elif ind.bb_pct > 0.95:
            signals.append({
                **base,
                'id': str(uuid.uuid4()),
                'signal_type': 'BB_UPPER_TOUCH',
                'indicator': 'BB_20_2',
                'direction': 'SELL',
                'value': ind.bb_upper,
                'strength': min(ind.bb_pct, 1.0),
            })

        # ── Volume Spike ──
        if ind.vol_ratio > 2.0:
            signals.append({
                **base,
                'id': str(uuid.uuid4()),
                'signal_type': 'VOLUME_SPIKE',
                'indicator': 'VOLUME_SMA20',
                'direction': 'NEUTRAL',
                'value': ind.vol_ratio,
                'strength': min(ind.vol_ratio / 5, 1.0),
            })

        return signals

    def _save_signals(self, signals: list):
        """Persiste señales en PostgreSQL."""
        with self.feed.engine.begin() as conn:
            for sig in signals:
                conn.execute(
                    text("""
                        INSERT INTO signals
                            (id, asset, timeframe, signal_type, indicator,
                             direction, value, strength, price_at_signal, timestamp)
                        VALUES
                            (:id, :asset, :timeframe, :signal_type, :indicator,
                             :direction, :value, :strength, :price_at_signal, :timestamp)
                        ON CONFLICT (id) DO NOTHING
                    """),
                    {
                        'id': sig['id'],
                        'asset': sig['asset'],
                        'timeframe': sig['timeframe'],
                        'signal_type': sig['signal_type'],
                        'indicator': sig['indicator'],
                        'direction': sig['direction'],
                        'value': float(sig['value']),
                        'strength': float(sig['strength']),
                        'price_at_signal': float(sig['price_at_signal']),
                        'timestamp': sig['timestamp'],
                    }
                )

    def _publish_signals(self, signals: list):
        """Publica señales en Redis pub/sub."""
        for sig in signals:
            self.redis.publish('signals:new', json.dumps(sig, default=str))
            logger.info(
                f'Signal: {sig["asset"]} {sig["signal_type"]} '
                f'dir={sig["direction"]} str={sig["strength"]:.2f}'
            )


# ── CLI para ejecución directa ──
if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv('/opt/trading/config/.env')

    scanner = MarketScanner()
    signals = scanner.scan()
    print(f'\n=== Scan Result: {len(signals)} signals ===')
    for s in signals:
        print(f'  {s["asset"]}/{s["timeframe"]}: {s["signal_type"]} '
              f'{s["direction"]} strength={s["strength"]:.2f} '
              f'@ {s["price_at_signal"]}')
