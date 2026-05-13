"""
MarketGuard — Sistema de auto-verificación y auto-preservación.

Monitorea condiciones extremas del mercado y ajusta el comportamiento
del agente en tiempo real para proteger capital o aprovechar oportunidades.

Alertas/acciones:
  - FLASH_CRASH:   BTC cae >3% en 15m → pausa SELL 30min (evitar cuchillo)
  - FLASH_RALLY:   BTC sube >3% en 15m → activa BUY temporal
  - VOLATILITY_SPIKE: ATR > 2× normal → reduce posición 0.25×
  - DEAD_MARKET:   ATR < 0.5% por 6h → modo baja actividad
  - CONSECUTIVE_SL: N SLs seguidas → reduce exposición
  - EMERGENCY:     DD > 8% → halt temprano (antes del 10% del RiskManager)

Estado persiste en Redis para sobrevivir reinicios.
"""
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import redis as redis_lib
from loguru import logger

sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')


# ── Thresholds ──────────────────────────────────────────────────────────

class GuardLevel:
    NORMAL = 'NORMAL'
    CAUTION = 'CAUTION'
    DEFENSIVE = 'DEFENSIVE'
    PAUSED = 'PAUSED'


@dataclass
class MarketGuardState:
    level: str = GuardLevel.NORMAL
    reason: str = ''
    since: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    position_multiplier: float = 1.0
    buy_allowed: bool = False


class MarketGuard:
    """Detecta condiciones de mercado y ajusta el comportamiento del agente."""

    # Constantes
    FLASH_MOVE_PCT = 3.0           # % de movimiento en 15 min para considerarlo flash
    VOL_SPIKE_MULT = 2.2           # ATR > 2.2× media 24h = volatilidad anómala (más conservador)
    DEAD_ATR_PCT = 0.3             # ATR < 0.3% = mercado sin vida (bajado 0.5→0.3)
    DEAD_ACTIVE_HOURS = frozenset({8,9,10,11,12,13,14,15,16,17,18,19,20,21})  # Solo en horario activo
    CONSECUTIVE_SL_LIMIT = 4       # N SLs seguidas → reducir
    EMERGENCY_DD = 0.08            # 8% DD → halt temprano
    PAUSE_MINUTES = 30             # Minutos de pausa tras flash crash/rally

    def __init__(self):
        redis_host = os.getenv('REDIS_HOST', 'localhost')
        redis_port = int(os.getenv('REDIS_PORT', 6379))
        self.redis = redis_lib.Redis(host=redis_host, port=redis_port, decode_responses=True)
        self._btc_history: list[float] = []
        self._last_atr_check = 0.0
        self._sl_counter: int = 0

    def check(self, feed=None, portfolio: dict = None) -> MarketGuardState:
        """Evalúa todas las condiciones y devuelve el estado recomendado.

        Args:
            feed: MarketFeed instance (opcional, para datos BTC)
            portfolio: dict con total_balance, drawdown_pct
        """
        state = MarketGuardState()
        now = datetime.now(timezone.utc)

        # ── 1. EMERGENCY: drawdown temprano ──
        if portfolio:
            dd = float(portfolio.get('drawdown_pct', 0) or 0)
            if dd >= self.EMERGENCY_DD:
                state.level = GuardLevel.PAUSED
                state.reason = f'EMERGENCY_DD:{dd*100:.1f}%'
                state.position_multiplier = 0.0
                self._set_guard('emergency', f'DD {dd*100:.1f}%', 3600)
                logger.critical(f'MARKETGUARD: EMERGENCY — DD {dd*100:.1f}%')
                return state

        # ── 2. BT Price data for market conditions ──
        btc_data = self._get_btc_data(feed)
        if btc_data is None or len(btc_data) < 30:
            return state

        current_price = btc_data[-1]
        recent_prices = btc_data[-15:]  # últimos 15 min (asumiendo datos 1m)

        # ── 3. FLASH CRASH ──
        if len(recent_prices) >= 3:
            pct_change = (recent_prices[-1] / recent_prices[0] - 1) * 100
            if pct_change <= -self.FLASH_MOVE_PCT:
                state.level = GuardLevel.PAUSED
                state.reason = f'FLASH_CRASH:{pct_change:.1f}%'
                state.position_multiplier = 0.0
                self._set_guard('flash_crash', f'BTC {pct_change:.1f}%', self.PAUSE_MINUTES * 60)
                self._send_alert(f'🚨 <b>FLASH CRASH</b> — BTC {pct_change:+.1f}% en 15m\n'
                                 f'SELL pausado {self.PAUSE_MINUTES}min. Esperando estabilización.')
                logger.critical(f'MARKETGUARD: FLASH CRASH BTC {pct_change:.1f}% — PAUSED')
                return state

        # ── 4. FLASH RALLY ──
        if len(recent_prices) >= 3:
            pct_change = (recent_prices[-1] / recent_prices[0] - 1) * 100
            if pct_change >= self.FLASH_MOVE_PCT:
                state.level = GuardLevel.CAUTION
                state.reason = f'FLASH_RALLY:{pct_change:.1f}%'
                state.position_multiplier = 0.25  # SELL reducido
                state.buy_allowed = True           # Permitir BUY
                self._send_alert(f'🚀 <b>FLASH RALLY</b> — BTC {pct_change:+.1f}% en 15m\n'
                                 f'SELL reducido a 0.25×. BUY habilitado temporal.')
                logger.warning(f'MARKETGUARD: FLASH RALLY BTC {pct_change:.1f}% — CAUTION')

        # ── 5. VOLATILITY SPIKE ──
        if len(btc_data) >= 60:
            # Calcular ATR rápido usando velas de 5m (simplificado: rango últimos 60 puntos)
            recent_atr = np.std(btc_data[-20:]) / np.mean(btc_data[-20:]) * 100
            baseline_atr = np.std(btc_data[-200:]) / np.mean(btc_data[-200:]) * 100 if len(btc_data) >= 200 else recent_atr * 0.5
            if recent_atr > baseline_atr * self.VOL_SPIKE_MULT and baseline_atr > 0:
                state.level = GuardLevel.CAUTION
                state.reason = f'VOL_SPIKE:ATR_{recent_atr:.1f}%_vs_{baseline_atr:.1f}%'
                state.position_multiplier = 0.25
                logger.warning(f'MARKETGUARD: VOL_SPIKE ATR {recent_atr:.1f}% > {baseline_atr:.1f}%×2 — CAUTION')

        # ── 6. DEAD MARKET — solo aplica en horario activo (08-21 UTC) ──
        current_hour = datetime.now(timezone.utc).hour
        if current_hour in self.DEAD_ACTIVE_HOURS and len(btc_data) >= 200:
            recent_vol = np.std(btc_data[-60:]) / np.mean(btc_data[-60:]) * 100
            if recent_vol < self.DEAD_ATR_PCT:
                # Solo reducir, no pausar. Multiplicador suave (0.75× vs 0.5× antes).
                state.position_multiplier = min(state.position_multiplier, 0.75)
                state.reason = f'DEAD_MARKET:ATR_{recent_vol:.2f}%'
                logger.info(f'MARKETGUARD: Low volatility (ATR {recent_vol:.2f}%) — soft reduction to 0.75×')

        # ── 7. Check if any guards are active ──
        guard_reasons = []
        for guard in ['emergency', 'flash_crash', 'flash_rally', 'vol_spike', 'consecutive_sl']:
            ttl = self.redis.ttl(f'guard:{guard}')
            if ttl and ttl > 0:
                guard_reasons.append(f'{guard}:{ttl}s')

        if guard_reasons:
            # Override with worst active guard
            if self.redis.ttl('guard:emergency') and self.redis.ttl('guard:emergency') > 0:
                state.level = GuardLevel.PAUSED
                state.position_multiplier = 0.0
            elif self.redis.ttl('guard:flash_crash') and self.redis.ttl('guard:flash_crash') > 0:
                state.level = GuardLevel.PAUSED
                state.position_multiplier = 0.0
            elif self.redis.ttl('guard:flash_rally') and self.redis.ttl('guard:flash_rally') > 0:
                state.level = GuardLevel.CAUTION
                state.position_multiplier = 0.25
                state.buy_allowed = True
            elif self.redis.ttl('guard:consecutive_sl') and self.redis.ttl('guard:consecutive_sl') > 0:
                state.level = GuardLevel.CAUTION
                state.position_multiplier = 0.25
                state.reason = 'CONSECUTIVE_SL'

        return state

    def register_sl(self):
        """Registra un STOP_LOSS. Si son muchos seguidos, reduce exposición."""
        self._sl_counter += 1
        if self._sl_counter >= self.CONSECUTIVE_SL_LIMIT:
            self._set_guard('consecutive_sl', f'{self._sl_counter} SLs', 1800)
            logger.warning(f'MARKETGUARD: {self._sl_counter} consecutive SLs — reducing exposure')
            self._send_alert(f'⚠️ <b>{self._sl_counter} STOP LOSS consecutivos</b>\n'
                             f'Exposición reducida 30min. Revisar mercado.')

    def register_tp(self):
        """Resetea el contador de SLs si hay un TP."""
        self._sl_counter = 0
        self.redis.delete('guard:consecutive_sl')

    def get_status(self) -> dict:
        """Retorna el estado actual de todas las guardas."""
        guards = {}
        for guard in ['emergency', 'flash_crash', 'flash_rally', 'vol_spike',
                       'consecutive_sl', 'dead_market']:
            ttl = self.redis.ttl(f'guard:{guard}')
            reason = self.redis.get(f'guard:{guard}')
            if ttl and ttl > 0:
                guards[guard] = {'ttl_s': ttl, 'reason': reason}
        return {
            'level': self._current_level(guards),
            'sl_counter': self._sl_counter,
            'active_guards': guards,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }

    def _current_level(self, guards: dict) -> str:
        if 'emergency' in guards or 'flash_crash' in guards:
            return GuardLevel.PAUSED
        if 'flash_rally' in guards or 'consecutive_sl' in guards:
            return GuardLevel.CAUTION
        return GuardLevel.NORMAL

    def _get_btc_data(self, feed) -> Optional[list[float]]:
        """Obtiene precios recientes de BTC (últimos ~200 puntos). Usa cache 60s."""
        now = time.time()
        if self._btc_history and (now - self._last_atr_check) < 60:
            return self._btc_history
        try:
            if feed is None:
                from data.market_feed import MarketFeed
                feed = MarketFeed()
            df = feed.get_latest('BTC', '1m', n=200)
            if not df.empty and 'close' in df.columns:
                self._btc_history = df['close'].tolist()
                self._last_atr_check = now
                return self._btc_history
        except Exception as e:
            logger.debug(f'MarketGuard: BTC data error: {e}')
        return self._btc_history if self._btc_history else None

    def _set_guard(self, name: str, reason: str, ttl: int):
        """Activa una guarda en Redis con TTL."""
        self.redis.setex(f'guard:{name}', ttl, reason)
        logger.info(f'MARKETGUARD: guard:{name} ACTIVE for {ttl}s ({reason})')

    def _send_alert(self, message: str):
        """Envía alerta por Telegram."""
        try:
            from core.notifications import send_telegram
            send_telegram(message, silent=False)
        except Exception:
            pass


# ── Singleton ──
_guard_instance: Optional[MarketGuard] = None


def get_market_guard() -> MarketGuard:
    global _guard_instance
    if _guard_instance is None:
        _guard_instance = MarketGuard()
    return _guard_instance
