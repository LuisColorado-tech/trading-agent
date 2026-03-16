"""
StrategyEngine — Orquestador de estrategias.
Evalúa TrendMomentum, MeanReversion y Breakout sobre indicadores reales,
selecciona la mejor señal y pide verificación a Claude.
"""
import json
import os
import sys

import redis
from loguru import logger

sys.path.insert(0, '/opt/trading')

from agents.indicators import IndicatorEngine
from core.claude_bridge import ClaudeBridge
from data.market_feed import MarketFeed, ASSET_MAP
from strategies.breakout import BreakoutStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.trend_momentum import TrendMomentumStrategy


class StrategyEngine:
    """Evalúa todas las estrategias y devuelve la mejor oportunidad."""

    def __init__(self):
        self.strategies = [
            TrendMomentumStrategy(),
            MeanReversionStrategy(),
            BreakoutStrategy(),
        ]
        self.claude = ClaudeBridge()
        self.feed = MarketFeed()
        self.redis = redis.Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            password=os.getenv('REDIS_PASSWORD') or None,
            decode_responses=True,
        )

    def evaluate(self, asset: str, timeframe: str,
                 portfolio_context: dict = None) -> dict:
        """Evalúa todas las estrategias y devuelve la mejor oportunidad si existe."""
        df = self.feed.get_latest(asset, timeframe, n=250)
        if df.empty:
            return {'opportunity': False, 'reason': 'no_data'}

        ind = IndicatorEngine.calculate(df, asset, timeframe)
        if ind is None:
            return {'opportunity': False, 'reason': 'insufficient_data'}

        # Evaluar todas las estrategias
        results = []
        for strategy in self.strategies:
            try:
                if strategy.NAME == 'BREAKOUT':
                    res = strategy.score(ind, df)
                else:
                    res = strategy.score(ind)
                if res['direction'] != 'NEUTRAL':
                    res['strategy'] = strategy.NAME
                    results.append(res)
            except Exception as e:
                logger.error(f'Strategy {strategy.NAME} error: {e}')

        if not results:
            return {'opportunity': False, 'reason': 'no_signal'}

        # Seleccionar señal de mayor score
        best = max(results, key=lambda r: r['score'])

        # Invocar Claude para verificación de consistencia
        claude_check = self.claude.call(
            task_type='signal_interpretation',
            asset=asset,
            data={
                'signals': results,
                'best_signal': best,
                'indicators': {
                    'rsi': ind.rsi,
                    'ema20': ind.ema20,
                    'ema50': ind.ema50,
                    'trend': ind.trend_direction,
                    'vol_ratio': ind.vol_ratio,
                    'atr_pct': ind.atr_pct,
                },
                'timeframe': timeframe,
            },
            portfolio_context=portfolio_context or {},
        )

        # Si Claude recomienda abortar con alta confianza, respetar
        if (claude_check.get('recommendation') == 'ABORT'
                and claude_check.get('confidence', 0) >= 80):
            logger.warning(f'Claude ABORT for {asset}: {claude_check.get("reasoning")}')
            return {
                'opportunity': False,
                'reason': 'claude_abort',
                'claude_analysis': claude_check,
            }

        best['claude_analysis'] = claude_check
        best['asset'] = asset
        best['timeframe'] = timeframe
        best['indicators'] = {
            'rsi': ind.rsi,
            'atr': ind.atr,
            'price': ind.close,
            'trend': ind.trend_direction,
        }

        return {'opportunity': True, 'signal': best}

    def scan_all(self, portfolio_context: dict = None) -> list:
        """Evalúa todas las combinaciones asset/timeframe y devuelve oportunidades."""
        opportunities = []
        for asset, info in ASSET_MAP.items():
            for tf in info['timeframes']:
                try:
                    result = self.evaluate(asset, tf, portfolio_context)
                    if result.get('opportunity'):
                        opportunities.append(result['signal'])
                        # Publicar en Redis
                        self.redis.publish(
                            'strategies:opportunity',
                            json.dumps(result['signal'], default=str),
                        )
                except Exception as e:
                    logger.error(f'StrategyEngine scan error {asset}/{tf}: {e}')
        logger.info(f'StrategyEngine scan: {len(opportunities)} opportunities found')
        return opportunities


# ── CLI ──
if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv('/opt/trading/config/.env')

    engine = StrategyEngine()
    opps = engine.scan_all()

    print(f'\n=== Strategy Engine: {len(opps)} opportunities ===')
    for o in opps:
        print(f'  {o["asset"]}/{o["timeframe"]}: {o["strategy"]} '
              f'{o["direction"]} score={o["score"]} '
              f'SL={o.get("stop_loss","N/A"):.2f} '
              f'TP={o.get("take_profit","N/A"):.2f}')
