"""
RiskManager — Motor de gestión de riesgo.
Punto de autoridad final para aprobar/rechazar trades.
PARÁMETROS INMUTABLES en tiempo de ejecución.
"""
from dataclasses import dataclass, field
from typing import List

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

        # 2. Exposición máxima
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
        position_size = risk_amount / risk_per_unit
        position_value = position_size * entry_price
        position_pct = position_value / total_balance if total_balance > 0 else 0

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
                'position_pct': position_pct,
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
