"""
RiskManager — Motor de gestión de riesgo.
Punto de autoridad final para aprobar/rechazar trades.
PARÁMETROS INMUTABLES en tiempo de ejecución.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

import os

import redis
from loguru import logger

import sys
sys.path.insert(0, '/opt/trading')
from core.claude_bridge import ClaudeBridge

# ─── PARÁMETROS INMUTABLES ─────────────────────────────────────────
MAX_RISK_PER_TRADE_PCT   = 0.01   # 1% del portafolio por trade
MAX_PORTFOLIO_EXPOSURE   = 0.05   # 5% máximo total en posiciones abiertas
STOP_LOSS_ATR_MULTIPLIER = 1.5    # Stop = Entry - (1.5 × ATR)
TAKE_PROFIT_ATR_MULT     = 2.5    # TP = Entry + (2.5 × ATR)
MAX_DRAWDOWN_STOP        = 0.10   # 10% drawdown → parar todo el trading
MAX_CONCURRENT_TRADES    = 3      # Máximo trades abiertos simultáneamente
MIN_RR_RATIO             = 1.5    # Ratio riesgo:recompensa mínimo
SL_COOLDOWN_MINUTES      = 60     # Minutos de espera tras un SL antes de re-entrar al mismo asset
TP_COOLDOWN_MINUTES      = 5      # Minutos de espera tras un TP/TRAILING antes de re-entrar
DEAD_HOURS_UTC           = {1, 2, 3, 4}  # Horas con 0% WR históricamente — no operar
SIGNAL_DEDUP_HOURS       = 4     # No reentrar mismo asset+dirección en N horas tras SL
MAX_NOTIONAL_PCT         = 0.50   # Notional máximo por trade = 50% del balance (evitar apalancamiento)
PAPER_HALT_COOLDOWN_HOURS = 3     # Reanudación autónoma sólo en paper tras cuarentena
PAPER_AUTO_RESUME_MAX_DD = 0.09   # Sólo reanudar si el DD actual ya bajó por debajo de 9%
# ───────────────────────────────────────────────────────────────────


@dataclass
class RiskDecision:
    approved: bool
    position_size: float
    stop_loss: float
    take_profit: float
    risk_amount: float
    reason: str
    claude_flags: List[str] = field(default_factory=list)


class RiskManager:
    """Punto de autoridad final de riesgo. No se puede override por API ni Claude."""

    def __init__(self):
        self.claude = ClaudeBridge()
        self._trading_halted = False
        self._halt_reason = ''
        self.paper_mode = os.getenv('PAPER_TRADING', 'true').lower() == 'true'
        self._redis = redis.Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            password=os.getenv('REDIS_PASSWORD') or None,
            decode_responses=True,
        )

    def _paper_auto_resume_allowed(self, portfolio: dict) -> bool:
        if not self.paper_mode:
            return False
        breach_at = portfolio.get('last_halt_breach_at')
        current_drawdown = float(portfolio.get('drawdown_pct', 0.0) or 0.0)
        if breach_at is None:
            return False
        if current_drawdown > PAPER_AUTO_RESUME_MAX_DD:
            return False
        now = datetime.now(timezone.utc)
        if isinstance(breach_at, str):
            breach_at = datetime.fromisoformat(breach_at)
        if breach_at.tzinfo is None:
            breach_at = breach_at.replace(tzinfo=timezone.utc)
        return now - breach_at >= timedelta(hours=PAPER_HALT_COOLDOWN_HOURS)

    def register_close(self, asset: str, direction: str = '', reason: str = ''):
        """Registra un cierre de trade. Aplica cooldown según el motivo de cierre. Persiste en Redis."""
        is_loss = reason in ('STOP_LOSS',)
        cooldown_min = SL_COOLDOWN_MINUTES if is_loss else TP_COOLDOWN_MINUTES
        self._redis.setex(f'cooldown:{asset}', cooldown_min * 60, reason)
        logger.info(f'COOLDOWN: {asset} blocked for {cooldown_min} min (reason={reason}) [Redis]')
        # Dedup largo solo tras pérdidas: bloquear misma dirección por SIGNAL_DEDUP_HOURS
        if is_loss and direction:
            dedup_key = f'dedup:{asset}:{direction}'
            self._redis.setex(dedup_key, int(SIGNAL_DEDUP_HOURS * 3600), reason)
            logger.info(f'SIGNAL_DEDUP: {asset}:{direction} blocked for {SIGNAL_DEDUP_HOURS}h [Redis]')

    def register_sl_close(self, asset: str, direction: str = ''):
        """Backward-compat wrapper."""
        self.register_close(asset, direction, reason='STOP_LOSS')

    def check_persistent_halt(self, portfolio: dict):
        """Verifica drawdown desde DB al inicio de cada ciclo. Halt persiste entre restarts."""
        current_drawdown = portfolio.get('drawdown_pct', 0)
        historical_drawdown = portfolio.get('historical_max_drawdown', current_drawdown)
        halt_triggered = portfolio.get('halt_triggered', False)
        if halt_triggered:
            if self._paper_auto_resume_allowed(portfolio):
                self._trading_halted = False
                self._halt_reason = ''
                logger.warning(
                    'PAPER AUTO-RESUME: halt quarantine completed, '
                    f'current drawdown {current_drawdown * 100:.1f}%'
                )
                return
            halt_dd = max(float(historical_drawdown), float(current_drawdown))
            self._trading_halted = True
            self._halt_reason = f'DRAWDOWN_{halt_dd * 100:.1f}pct'
            logger.critical(f'TRADING HALTED (historical breach): Drawdown {halt_dd * 100:.1f}%')
            return
        if current_drawdown >= MAX_DRAWDOWN_STOP:
            self._trading_halted = True
            self._halt_reason = f'DRAWDOWN_{current_drawdown * 100:.1f}pct'
            logger.critical(f'TRADING HALTED (persistent check): Drawdown {current_drawdown * 100:.1f}%')

    def evaluate(self, signal: dict, portfolio: dict,
                 open_trades: list) -> RiskDecision:
        """Evalúa si un trade debe ejecutarse. Devuelve RiskDecision."""

        # 0. Halt de emergencia
        if self._trading_halted:
            return RiskDecision(
                approved=False, position_size=0, stop_loss=0,
                take_profit=0, risk_amount=0,
                reason=f'TRADING_HALTED: {self._halt_reason}',
                claude_flags=[],
            )

        # 0b. Filtro horario: bloquear horas con 0% WR histórico
        current_hour = datetime.now(timezone.utc).hour
        if current_hour in DEAD_HOURS_UTC:
            return RiskDecision(
                approved=False, position_size=0, stop_loss=0,
                take_profit=0, risk_amount=0,
                reason=f'DEAD_HOUR:{current_hour}UTC',
                claude_flags=[],
            )

        total_balance = portfolio.get('total_balance', 0)
        current_exposure = portfolio.get('exposure_pct', 0)
        current_drawdown = portfolio.get('drawdown_pct', 0)
        n_open = len(open_trades)

        # 1. Drawdown máximo
        if current_drawdown >= MAX_DRAWDOWN_STOP:
            self._trading_halted = True
            self._halt_reason = f'DRAWDOWN_{current_drawdown * 100:.1f}pct'
            logger.critical(f'TRADING HALTED: Drawdown {current_drawdown * 100:.1f}%')
            return RiskDecision(
                approved=False, position_size=0, stop_loss=0,
                take_profit=0, risk_amount=0,
                reason='DRAWDOWN_LIMIT_REACHED',
                claude_flags=['CRITICAL_HALT'],
            )

        # 2. Exposición máxima (risk-based: sum de riesgo por trade / balance)
        if current_exposure >= MAX_PORTFOLIO_EXPOSURE:
            return RiskDecision(
                approved=False, position_size=0, stop_loss=0,
                take_profit=0, risk_amount=0,
                reason='MAX_EXPOSURE_REACHED', claude_flags=[],
            )

        # 3. Trades concurrentes
        if n_open >= MAX_CONCURRENT_TRADES:
            return RiskDecision(
                approved=False, position_size=0, stop_loss=0,
                take_profit=0, risk_amount=0,
                reason='MAX_CONCURRENT_TRADES', claude_flags=[],
            )

        # 3b. Máximo 1 trade abierto por activo (evitar concentración)
        asset_name = signal.get('asset', '')
        asset_open_count = sum(
            1 for t in open_trades
            if (t.get('asset') or t.get('asset', '')) == asset_name
        )
        if asset_open_count >= 1:
            return RiskDecision(
                approved=False, position_size=0, stop_loss=0,
                take_profit=0, risk_amount=0,
                reason=f'DUPLICATE_ASSET:{asset_name}', claude_flags=[],
            )

        # 3c. Cooldown post stop-loss: no re-entrar al mismo asset tras SL reciente
        cooldown_ttl = self._redis.ttl(f'cooldown:{asset_name}')
        if cooldown_ttl and cooldown_ttl > 0:
            remaining = cooldown_ttl / 60
            return RiskDecision(
                approved=False, position_size=0, stop_loss=0,
                take_profit=0, risk_amount=0,
                reason=f'SL_COOLDOWN:{asset_name}:{remaining:.0f}min_left',
                claude_flags=[],
            )

        # 3d. Dedup: no reentrar mismo asset+dirección tras SL reciente
        direction = signal.get('direction', '')
        dedup_key = f'dedup:{asset_name}:{direction}'
        dedup_ttl = self._redis.ttl(dedup_key)
        if dedup_ttl and dedup_ttl > 0:
            remaining_h = dedup_ttl / 3600
            return RiskDecision(
                approved=False, position_size=0, stop_loss=0,
                take_profit=0, risk_amount=0,
                reason=f'SIGNAL_DEDUP:{asset_name}:{direction}:{remaining_h:.1f}h_left',
                claude_flags=[],
            )

        # 4. Calcular tamaño de posición
        entry_price = signal['indicators']['price']
        stop_loss = signal['stop_loss']
        take_profit = signal['take_profit']
        risk_per_unit = abs(entry_price - stop_loss)

        if risk_per_unit == 0:
            return RiskDecision(
                approved=False, position_size=0, stop_loss=stop_loss,
                take_profit=take_profit, risk_amount=0,
                reason='ZERO_RISK_PER_UNIT', claude_flags=[],
            )

        risk_amount = total_balance * MAX_RISK_PER_TRADE_PCT

        # 4p. Probation: reducir riesgo al 50% si la estrategia está en periodo de prueba
        if signal.get('on_probation'):
            risk_amount *= 0.5
            logger.info(f'PROBATION: {signal.get("asset")} risk reduced to ${risk_amount:.2f} (50% of normal)')

        position_size = risk_amount / risk_per_unit
        position_value = position_size * entry_price
        risk_pct = risk_amount / total_balance if total_balance > 0 else 0

        # 4a. Cap notional: no permitir que un trade supere MAX_NOTIONAL_PCT del balance
        max_notional = total_balance * MAX_NOTIONAL_PCT
        if position_value > max_notional:
            position_size = max_notional / entry_price
            position_value = position_size * entry_price
            logger.info(f'NOTIONAL_CAP: {signal.get("asset")} capped to {position_size:.6f} units (${position_value:,.0f} / ${total_balance:,.0f} bal)')

        # 4b. Cash check: rechazar si no hay cash suficiente para el nocional
        available_cash = portfolio.get('available_cash', total_balance)
        if available_cash < position_value:
            return RiskDecision(
                approved=False, position_size=0, stop_loss=stop_loss,
                take_profit=take_profit, risk_amount=risk_amount,
                reason=f'INSUFFICIENT_CASH:{available_cash:,.0f}<{position_value:,.0f}',
                claude_flags=[],
            )

        # 4c. Verificar que exposición total (actual + nuevo riesgo) no exceda límite
        if current_exposure + risk_pct > MAX_PORTFOLIO_EXPOSURE:
            return RiskDecision(
                approved=False, position_size=0, stop_loss=stop_loss,
                take_profit=take_profit, risk_amount=risk_amount,
                reason='MAX_EXPOSURE_WITH_NEW_TRADE', claude_flags=[],
            )

        # 5. R:R ratio mínimo
        rr = abs(take_profit - entry_price) / risk_per_unit
        if rr < MIN_RR_RATIO:
            return RiskDecision(
                approved=False, position_size=0, stop_loss=stop_loss,
                take_profit=take_profit, risk_amount=risk_amount,
                reason=f'INSUFFICIENT_RR:{rr:.2f}', claude_flags=[],
            )

        # 6. Claude anomaly check
        claude_anomaly = self.claude.call(
            task_type='anomaly_check',
            asset=signal.get('asset', ''),
            data={
                'signal': signal,
                'position_size': position_size,
                'risk_pct': risk_pct,
                'open_trades': n_open,
                'recent_trades': open_trades[-5:] if open_trades else [],
            },
            portfolio_context=portfolio,
        )

        claude_flags = claude_anomaly.get('flags', [])
        if (claude_anomaly.get('severity') == 'CRITICAL'
                and claude_anomaly.get('confidence', 0) >= 85):
            logger.warning(f'Claude CRITICAL ANOMALY: {claude_anomaly.get("reasoning")}')
            return RiskDecision(
                approved=False, position_size=0, stop_loss=stop_loss,
                take_profit=take_profit, risk_amount=risk_amount,
                reason='CLAUDE_CRITICAL_ANOMALY', claude_flags=claude_flags,
            )

        # 7. APROBADO
        logger.info(
            f'RISK APPROVED: {signal.get("asset")} {position_size:.6f} units '
            f'risk=${risk_amount:.2f} RR={rr:.2f}'
        )
        return RiskDecision(
            approved=True,
            position_size=round(position_size, 6),
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_amount=risk_amount,
            reason='APPROVED',
            claude_flags=claude_flags,
        )

    def resume_trading(self, manual_override: bool = False):
        """Solo manual. El sistema no puede auto-reanudar tras un halt."""
        if not manual_override:
            raise PermissionError('Trading halt requires manual override')
        self._trading_halted = False
        self._halt_reason = ''
        logger.warning('Trading RESUMED by manual override')
