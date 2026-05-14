"""
StrategyEngine — Orquestador de estrategias.
Evalúa TrendMomentum y Breakout sobre indicadores reales,
selecciona la mejor señal y pide verificación a Claude.
NOTE: MeanReversion deshabilitada — 0/8 win rate en paper, -$569 P&L.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

import random
import redis
from loguru import logger
from sqlalchemy import create_engine

sys.path.insert(0, '/opt/trading')

from agents.indicators import IndicatorEngine
from core.market_regime import classify_market_regime, regime_block_reason, strategy_allowed_in_regime, get_macro_bias, macro_position_multiplier, MacroBias
from core.performance_guard import StrategyPerformanceGuard
from core.claude_bridge import ClaudeBridge
from data.market_feed import MarketFeed, ASSET_MAP
from strategies.breakout import BreakoutStrategy
from strategies.btc_dip_buyer import BtcDipBuyerStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.trend_momentum import TrendMomentumStrategy
from strategies.smc_order_blocks import SmcOrderBlocksStrategy
from strategies.btc_microstructure import BtcMicrostructureStrategy
from core.asset_profiles import get_profile, hour_allowed, direction_allowed


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
            # ── ESTRATEGIAS PAUSADAS (May 14: stability run) ──
            # SMC_ORDER_BLOCKS: reactivada May 13, backtest 62 trades +$558.
            #   Paper: 5 trades -$51 (May 14). En drawdown. Pausada para estabilidad.
            # BTC_MICROSTRUCTURE: reactivada May 13, backtest 38 trades +$1,292.
            #   Paper: 1 trade -$18 (May 14). Pausada para estabilidad.
            # Ambas son rentables en backtest pero necesitan más validación paper.
            # Se reactivarán cuando TREND_MOMENTUM esté estable 2+ semanas.
            # SmcOrderBlocksStrategy(),
            # BtcMicrostructureStrategy(),
            # BreakoutStrategy, BtcDipBuyerStrategy, MeanReversionStrategy: pausadas.
        ]
        self.claude = ClaudeBridge()
        # LLM_CALL_SAMPLE_RATE: fracción de señales que consultan al LLM (1.0 = todas).
        # Con 0.10, el LLM se invoca en ~1 de cada 10 señales que pasan confluence.
        # El 99% de los ABORT de Claude son neutrales — reducir llamadas ahorra ~90% del costo.
        self._llm_sample_rate = float(os.getenv('LLM_CALL_SAMPLE_RATE', '0.10'))
        self.feed = MarketFeed()
        self.redis = redis.Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            password=os.getenv('REDIS_PASSWORD') or None,
            decode_responses=True,
        )
        self.guard = StrategyPerformanceGuard(db_url)
        self._macro_bias: str | None = None
        self._macro_last_update: float = 0

    def _get_macro_bias(self) -> str:
        """Obtiene el régimen macro usando BTC 1h como referencia. Cache 15 min."""
        now = time.time()
        if self._macro_bias is not None and (now - self._macro_last_update) < 900:
            return self._macro_bias
        try:
            btc_df = self.feed.get_latest('BTC', '1h', n=250)
            if not btc_df.empty and len(btc_df) >= 200:
                self._macro_bias = get_macro_bias(btc_df)
                self._macro_last_update = now
                logger.info(f'Macro regime: {self._macro_bias}')
                return self._macro_bias
        except Exception:
            pass
        return self._macro_bias or MacroBias.RANGE

    def evaluate(self, asset: str, timeframe: str,
                 portfolio_context: dict = None) -> dict:
        """Evalúa todas las estrategias y devuelve la mejor oportunidad si existe."""
        # ── Filtro horario por perfil de asset (antes de cargar datos) ──
        current_hour = datetime.now(timezone.utc).hour
        if not hour_allowed(asset, current_hour):
            return {'opportunity': False, 'reason': f'hour_blocked:{current_hour}h_utc'}

        # ── Macro regime: computar una vez por ciclo (cache 15 min) ──
        macro_bias = self._get_macro_bias()

        df = self.feed.get_latest(asset, timeframe, n=250)
        if df.empty:
            return {'opportunity': False, 'reason': 'no_data'}

        ind = IndicatorEngine.calculate(df, asset, timeframe)
        if ind is None:
            return {'opportunity': False, 'reason': 'insufficient_data'}

        # ── Filtro de volatilidad mínima (ATR) por perfil ──
        profile = get_profile(asset)
        if ind.atr_pct < profile.min_atr_pct:
            logger.info(f'No opportunity {asset}/{timeframe}: low_atr {ind.atr_pct:.4f} < {profile.min_atr_pct:.4f}')
            return {'opportunity': False, 'reason': f'low_atr:{ind.atr_pct:.4f}'}

        regime = classify_market_regime(ind)

        # Si ningún flag está activo (CHOPPY), salir rápido sin evaluar estrategias
        any_allowed = (regime.allow_trend or regime.allow_mean_reversion
                       or regime.allow_breakout or regime.allow_dip_buy)
        if not any_allowed:
            logger.info(f'No opportunity {asset}/{timeframe}: CHOPPY (régimen inactivo)')
            return {'opportunity': False, 'reason': 'choppy'}

        # Evaluar todas las estrategias
        results = []
        blocked = []
        for strategy in self.strategies:
            try:
                if not strategy_allowed_in_regime(strategy.NAME, regime):
                    blocked.append({'strategy': strategy.NAME, 'reason': regime_block_reason(strategy.NAME, regime)})
                    continue
                # Pasar df a todas las estrategias: SMC_ORDER_BLOCKS y BTC_MICROSTRUCTURE
                # usan df para FVG y momentum multiperiodo. Sin df esos factores nunca calculan.
                try:
                    res = strategy.score(ind, df)
                except TypeError:
                    # Estrategias que no aceptan df (interfaz antigua)
                    res = strategy.score(ind)
                if res['direction'] != 'NEUTRAL':
                    # Bonus de régimen (backtest 6m): SELL en TREND_DOWN tiene win rate 38%.
                    # Se añade score adicional para que supere el MIN_SCORE con más margen.
                    if regime.name == 'TREND_DOWN' and res['direction'] == 'SELL':
                        res['score'] = res.get('score', 0) + 8
                        res.setdefault('reasons', []).append('REGIME_TREND_DOWN_BONUS')
                    # Macro regime alignment bonus: viento a favor = +10 score
                    if macro_bias == MacroBias.BULL_RUN and res['direction'] == 'BUY':
                        res['score'] = res.get('score', 0) + 10
                        res.setdefault('reasons', []).append('MACRO_BULL_ALIGNED')
                    elif macro_bias == MacroBias.BEAR_TREND and res['direction'] == 'SELL':
                        res['score'] = res.get('score', 0) + 10
                        res.setdefault('reasons', []).append('MACRO_BEAR_ALIGNED')
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

        # ── Filtro de dirección permitida por perfil de asset ──
        # Macro-regime override: en BULL_RUN se permite BUY aunque el perfil diga SELL-only.
        # En BEAR_TREND y RANGE se respeta la restricción original del perfil.
        if macro_bias == MacroBias.BULL_RUN and best['direction'] == 'BUY':
            pass  # permitir BUY en bull run
        elif not direction_allowed(asset, best['direction']):
            logger.info(
                f'No opportunity {asset}/{timeframe}: direction_not_allowed '
                f'dir={best["direction"]} asset={asset} macro={macro_bias}'
            )
            return {'opportunity': False, 'reason': f'direction_not_allowed:{best["direction"]}'}

        # ── Filtro de confluencia: diferenciado por tipo de estrategia ──
        if best.get('strategy') == 'MEAN_REVERSION':
            n_conf, conf_factors = count_confluence_pullback(ind, best['direction'])
            min_conf_needed = 3  # de 5 factores específicos de pullback
        elif best.get('strategy') == 'BTC_DIP_BUYER':
            # El scoring interno de BtcDipBuyerStrategy ya es suficientemente exigente
            # (RSI<38 + bb_pct<0.35 + EMA200). Confluencia mínima de 2: macro-bull + oversold.
            n_conf, conf_factors = count_confluence_pullback(ind, best['direction'])
            min_conf_needed = 2
        else:
            n_conf, conf_factors = count_confluence(ind, best['direction'])
            min_conf_needed = get_profile(asset).confluence_min
        if n_conf < min_conf_needed:
            logger.info(
                f'No opportunity {asset}/{timeframe}: low_confluence '
                f'{n_conf}/{min_conf_needed} factors={conf_factors} '
                f'dir={best["direction"]} score={best["score"]} regime={regime.name}'
            )
            return {'opportunity': False, 'reason': f'low_confluence:{n_conf}'}
        best['confluence'] = {'count': n_conf, 'factors': conf_factors}

        # Invocar LLM para verificación de consistencia (muestreo para controlar costos).
        # LLM_CALL_SAMPLE_RATE=0.10 → ~1 de cada 10 señales. El resto pasa con resultado neutral.
        if random.random() < self._llm_sample_rate:
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
        else:
            claude_check = {'recommendation': 'PROCEED', 'confidence': 0, 'reasoning': 'llm_sampled_out', 'flags': []}

        # Si el LLM recomienda abortar con alta confianza, respetar
        if (claude_check.get('recommendation') == 'ABORT'
                and claude_check.get('confidence', 0) >= 80):
            logger.warning(f'LLM ABORT for {asset}: {claude_check.get("reasoning")}')
            return {
                'opportunity': False,
                'reason': 'llm_abort',
                'claude_analysis': claude_check,
            }

        best['claude_analysis'] = claude_check
        best['asset'] = asset
        best['timeframe'] = timeframe
        best['market_regime'] = regime.name
        best['require_candle_close'] = get_profile(asset).require_candle_close
        best['indicators'] = {
            'rsi': ind.rsi,
            'atr': ind.atr,
            'price': ind.close,
            'trend': ind.trend_direction,
            'trend_strength': ind.trend_strength,
        }
        best['macro_bias'] = macro_bias
        best['position_multiplier'] = macro_position_multiplier(macro_bias, best['direction'])

        return {'opportunity': True, 'signal': best}

    def scan_all(self, portfolio_context: dict = None) -> list:
        """Evalúa todas las combinaciones asset/timeframe y devuelve oportunidades."""
        # Pre-computar macro bias una vez por ciclo
        self._get_macro_bias()
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
