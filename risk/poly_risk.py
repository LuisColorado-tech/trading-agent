"""
poly_risk.py — Gestión de riesgo para posiciones Polymarket.

Kelly criterion sizing, limits de exposición, y diversificación.
Independiente del RiskManager de cripto.
"""
import os
import sys
import yaml

sys.path.insert(0, '/opt/trading')

from loguru import logger

with open('/opt/trading/config/exchange_config.yaml') as f:
    _CFG = yaml.safe_load(f).get('polymarket', {}).get('risk', {})

MAX_POSITION_PCT = _CFG.get('max_position_pct', 5.0) / 100.0
MAX_TOTAL_EXPOSURE_PCT = _CFG.get('max_total_exposure_pct', 40.0) / 100.0
MAX_CONCURRENT = _CFG.get('max_concurrent_positions', 10)
KELLY_FRACTION = _CFG.get('kelly_fraction', 0.25)


class PolyRiskDecision:
    """Resultado de evaluación de riesgo Polymarket."""
    __slots__ = ('approved', 'shares', 'cost', 'reason')

    def __init__(self, approved: bool, shares: float = 0, cost: float = 0, reason: str = ''):
        self.approved = approved
        self.shares = shares
        self.cost = cost
        self.reason = reason

    def __repr__(self):
        return f'PolyRiskDecision(approved={self.approved}, shares={self.shares:.1f}, cost=${self.cost:.2f}, reason={self.reason!r})'


class PolyRiskManager:
    """Gestión de riesgo para la línea Polymarket."""

    def evaluate(self, signal: dict, balance: float, open_positions: list) -> PolyRiskDecision:
        """Evalúa si una señal Polymarket debe ejecutarse y con qué tamaño.

        Args:
            signal: dict con side, edge, entry_price, estimated_prob, confidence, market
            balance: balance disponible USDC (paper)
            open_positions: lista de posiciones abiertas

        Returns:
            PolyRiskDecision
        """
        # R1: Balance mínimo
        if balance < 10.0:
            return PolyRiskDecision(False, reason='INSUFFICIENT_BALANCE')

        # R2: Max posiciones concurrentes
        if len(open_positions) >= MAX_CONCURRENT:
            return PolyRiskDecision(False, reason=f'MAX_CONCURRENT:{len(open_positions)}/{MAX_CONCURRENT}')

        # R3: No duplicar mercado
        condition_id = signal.get('market', {}).get('condition_id', '')
        for pos in open_positions:
            if pos.get('condition_id') == condition_id:
                return PolyRiskDecision(False, reason=f'DUPLICATE_MARKET:{condition_id[:12]}')

        # R4: Exposición total
        total_exposure = sum(float(p.get('cost_basis', 0)) for p in open_positions)
        max_exposure = balance * MAX_TOTAL_EXPOSURE_PCT
        if total_exposure >= max_exposure:
            return PolyRiskDecision(False, reason=f'MAX_EXPOSURE:{total_exposure:.0f}/{max_exposure:.0f}')

        # R5: Sizing via Kelly Criterion
        edge = signal.get('edge', 0)
        entry_price = signal.get('entry_price', 0.5)
        confidence = signal.get('confidence', 50) / 100.0

        shares, cost = self._kelly_size(edge, entry_price, balance, confidence)

        if cost < 1.0:
            return PolyRiskDecision(False, reason=f'KELLY_TOO_SMALL: cost=${cost:.2f}')

        # R6: Cap por posición
        max_per_position = balance * MAX_POSITION_PCT
        if cost > max_per_position:
            cost = max_per_position
            shares = cost / entry_price

        # R7: No exceder cash disponible
        available = balance - total_exposure
        if cost > available:
            cost = available * 0.95  # dejar 5% buffer
            shares = cost / entry_price

        if cost < 1.0:
            return PolyRiskDecision(False, reason='INSUFFICIENT_AVAILABLE_CASH')

        market_q = signal.get('market', {}).get('question', '')[:40]
        logger.info(
            f'POLY RISK APPROVED: {signal["side"]} "{market_q}" '
            f'shares={shares:.1f} cost=${cost:.2f} edge={edge:+.1%}'
        )
        return PolyRiskDecision(True, shares=shares, cost=cost, reason='APPROVED')

    def _kelly_size(self, edge: float, entry_price: float, balance: float, confidence: float) -> tuple[float, float]:
        """Calcula tamaño de posición usando Kelly Criterion fraccionado.

        Kelly = (p*b - q) / b
        donde:
            p = probabilidad estimada de ganar
            q = 1 - p
            b = odds (payout / costo) = (1 - entry_price) / entry_price

        Returns:
            (shares, cost_in_usdc)
        """
        if entry_price <= 0.01 or entry_price >= 0.99:
            return 0, 0

        # Probabilidad estimada ajustada por confianza
        # Si confidence baja, acercar estimación al precio de mercado
        p = entry_price + edge  # prob estimada
        p = entry_price + (p - entry_price) * confidence  # ajustar por confianza
        p = max(0.01, min(0.99, p))
        q = 1 - p

        # Odds: cuánto ganas por $ arriesgado
        b = (1.0 - entry_price) / entry_price

        # Kelly full
        kelly = (p * b - q) / b if b > 0 else 0
        kelly = max(0, kelly)

        # Fracción Kelly (conservador)
        fraction = kelly * KELLY_FRACTION
        cost = balance * fraction
        shares = cost / entry_price if entry_price > 0 else 0

        return shares, cost
