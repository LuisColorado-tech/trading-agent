"""
StrategyEngine — Orquestador de estrategias.
Evalúa TrendMomentum y Breakout sobre indicadores reales,
selecciona la mejor señal y pide verificación a Claude.
NOTE: MeanReversion deshabilitada — 0/8 win rate en paper, -$569 P&L.
"""
import json
import os
import sys

import redis
from loguru import logger
from sqlalchemy import create_engine

sys.path.insert(0, '/opt/trading')

from agents.indicators import IndicatorEngine
from core.market_regime import classify_market_regime, regime_block_reason, strategy_allowed_in_regime
from core.performance_guard import StrategyPerformanceGuard
from core.claude_bridge import ClaudeBridge
from data.market_feed import MarketFeed, ASSET_MAP
from strategies.breakout import BreakoutStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.trend_momentum import TrendMomentumStrategy


# ── Confluencia mínima para pasar señal ─────────────────────────────
MIN_CONFLUENCE_INDICATORS = 3  # nº mínimo de factores alineados para operar


def count_confluence(ind, direction: str) -> tuple[int, list[str]]:
    """Cuenta cuántos indicadores confirman la dirección propuesta."""
    factors = []
    if direction == 'BUY':
        if ind.ema20 > ind.ema50:
            factors.append('EMA_ALIGNED')
        if ind.close > ind.ema20:
            factors.append('PRICE_ABOVE_EMA')
        if 40 <= ind.rsi <= 65:
            factors.append('RSI_OK')
        if ind.macd > ind.macd_signal:
            factors.append('MACD_BULLISH')
        if ind.vol_ratio > 1.2:
            factors.append('VOLUME_UP')
        if ind.close > ind.vwap:
            factors.append('ABOVE_VWAP')
    elif direction == 'SELL':
        if ind.ema20 < ind.ema50:
            factors.append('EMA_ALIGNED')
        if ind.close < ind.ema20:
            factors.append('PRICE_BELOW_EMA')
        if 35 <= ind.rsi <= 55:
            factors.append('RSI_OK')
        if ind.macd < ind.macd_signal:
            factors.append('MACD_BEARISH')
        if ind.vol_ratio > 1.2:
            factors.append('VOLUME_UP')
        if ind.close < ind.vwap:
            factors.append('BELOW_VWAP')
    return len(factors), factors


def count_confluence_pullback(ind, direction: str) -> tuple[int, list[str]]:
    """Confluencia específica para señales de pullback (Mean Reversion en TREND_UP).
    Los factores son distintos: el precio ESTÁ por debajo de EMA20 (eso es el pullback),
    el RSI ESTÁ sobrevendido, y el MACD ESTÁ negativo — todo contrario a TREND_MOMENTUM."""
    factors = []
    if direction == 'BUY':
        if ind.ema20 > ind.ema50:              # macro tendencia alcista intacta
            factors.append('MACRO_UPTREND')
        if ind.rsi < 42:                       # sobreventa = pullback válido
            factors.append('RSI_OVERSOLD')
        if ind.bb_pct < 0.30:                  # precio cerca de soporte estadístico
            factors.append('NEAR_BB_LOWER')
        if ind.close > ind.ema200 * 0.97:      # tendencia de largo plazo no rota
            factors.append('ABOVE_EMA200')
        if ind.macd_hist < 0:                  # MACD en dip = momentum de bajada agotándose
            factors.append('MACD_DIP')
    return len(factors), factors


class StrategyEngine:
    """Evalúa todas las estrategias y devuelve la mejor oportunidad."""

    def __init__(self):
        db_url = (
            f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
            f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT', '5432')}"
            f"/{os.getenv('POSTGRES_DB')}"
        )
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
        self.guard = StrategyPerformanceGuard(db_url)

    def evaluate(self, asset: str, timeframe: str,
                 portfolio_context: dict = None) -> dict:
        """Evalúa todas las estrategias y devuelve la mejor oportunidad si existe."""
        df = self.feed.get_latest(asset, timeframe, n=250)
        if df.empty:
            return {'opportunity': False, 'reason': 'no_data'}

        ind = IndicatorEngine.calculate(df, asset, timeframe)
        if ind is None:
            return {'opportunity': False, 'reason': 'insufficient_data'}

        regime = classify_market_regime(ind)


        # Evaluar todas las estrategias
        results = []
        blocked = []
        for strategy in self.strategies:
            try:
                if not strategy_allowed_in_regime(strategy.NAME, regime):
                    blocked.append({'strategy': strategy.NAME, 'reason': regime_block_reason(strategy.NAME, regime)})
                    continue
                if strategy.NAME == 'BREAKOUT':
                    res = strategy.score(ind, df)
                else:
                    res = strategy.score(ind)
                if res['direction'] != 'NEUTRAL':
                    # Bonus de régimen (backtest 6m): SELL en TREND_DOWN tiene win rate 38%.
                    # Se añade score adicional para que supere el MIN_SCORE con más margen.
                    if regime.name == 'TREND_DOWN' and res['direction'] == 'SELL':
                        res['score'] = res.get('score', 0) + 8
                        res.setdefault('reasons', []).append('REGIME_TREND_DOWN_BONUS')
                    guard_reason = self.guard.assess_signal(asset, strategy.NAME)
                    if guard_reason:
                        blocked.append({'strategy': strategy.NAME, 'reason': guard_reason})
                        logger.warning(f'Strategy guard blocked {asset}/{timeframe} {strategy.NAME}: {guard_reason}')
                        continue
                    res['strategy'] = strategy.NAME
                    res['on_probation'] = self.guard.is_on_probation(strategy.NAME)
                    results.append(res)
            except Exception as e:
                logger.error(f'Strategy {strategy.NAME} error: {e}')

        if not results:
            if blocked:
                block_summary = ', '.join(f"{b['strategy']}:{b['reason']}" for b in blocked)
                logger.info(
                    f'No opportunity {asset}/{timeframe}: BLOCKED [{block_summary}]'
                )
                return {'opportunity': False, 'reason': 'strategy_guard', 'blocked': blocked}
            logger.info(
                f'No opportunity {asset}/{timeframe}: no_signal '
                f'(regime={regime.name} trend={ind.trend_strength:.3f})'
            )
            return {'opportunity': False, 'reason': 'no_signal'}

        # Seleccionar señal de mayor score
        best = max(results, key=lambda r: r['score'])

        # ── Filtro de confluencia: diferenciado por tipo de estrategia ──
        # MEAN_REVERSION usa factores de pullback (precio bajo EMA, RSI<42, etc.)
        # porque en TREND_UP la dirección esperada es exactamente la opuesta a los
        # indicadores que mide count_confluence estándar.
        if best.get('strategy') == 'MEAN_REVERSION':
            n_conf, conf_factors = count_confluence_pullback(ind, best['direction'])
            min_conf_needed = 3  # de 5 factores específicos de pullback
        else:
            n_conf, conf_factors = count_confluence(ind, best['direction'])
            min_conf_needed = MIN_CONFLUENCE_INDICATORS
        if n_conf < min_conf_needed:
            logger.info(
                f'No opportunity {asset}/{timeframe}: low_confluence '
                f'{n_conf}/{min_conf_needed} factors={conf_factors} '
                f'dir={best["direction"]} score={best["score"]} regime={regime.name}'
            )
            return {'opportunity': False, 'reason': f'low_confluence:{n_conf}'}
        best['confluence'] = {'count': n_conf, 'factors': conf_factors}

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
        best['market_regime'] = regime.name
        best['indicators'] = {
            'rsi': ind.rsi,
            'atr': ind.atr,
            'price': ind.close,
            'trend': ind.trend_direction,
            'trend_strength': ind.trend_strength,
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
