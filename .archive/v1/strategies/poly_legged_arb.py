"""
poly_legged_arb.py — Legged Arbitrage Strategy para Polymarket.

Basada en el repo Anmoldureha/polymarket-trading-bot-strategies (24★).

Estrategia de 2 fases:
  Phase 1 (Entry): Comprar YES cuando el precio es bajo (≤0.30) en un mercado volátil.
  Phase 2 (Hedge): Cuando el mercado se revierte y el precio de NO cae, comprar NO.
  Resultado: Si YES_cost + NO_cost < 0.95 → profit garantizado de $0.05+ por share.

En mercados crypto volátiles (BTC/ETH), es común que el precio oscile entre
0.20-0.80 a lo largo del día → oportunidades de construir el arb en 2 pasos.
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta

import yaml
from loguru import logger
from sqlalchemy import create_engine, text

sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv

load_dotenv('/opt/trading/config/.env')

with open('/opt/trading/config/exchange_config.yaml') as f:
    _POLY_CFG = yaml.safe_load(f).get('polymarket', {})

NAME = 'legged_arb'

_STRAT_CFG = _POLY_CFG.get('strategies', {}).get('legged_arb', {})

# Precio máximo para abrir Phase 1 (YES debe ser "barato")
MAX_PHASE1_PRICE = _STRAT_CFG.get('max_phase1_price', 0.30)
# Ganancia mínima garantizada para ejecutar Phase 2 (% de profit)
MIN_LEG2_PROFIT_PCT = _STRAT_CFG.get('min_leg2_profit_pct', 5.0)
# Días máximos para esperar Phase 2 antes de abandonar
MAX_HOLD_DAYS = _STRAT_CFG.get('max_hold_days', 14)
# Inversión máxima total por par (ambas legs)
MAX_INVESTMENT_PER_PAIR = _STRAT_CFG.get('max_investment_per_pair', 30.0)


def _db_url() -> str:
    return (
        f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
        f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT', '5432')}"
        f"/{os.getenv('POSTGRES_DB')}"
    )


class LeggedArbPolyStrategy:
    """
    Legged Arbitrage: construir un arb en 2 fases aprovechando volatilidad.

    Mantiene estado en memoria (legs abiertas esperando Phase 2) y en DB
    (columna strategy_data para persistencia entre reinicios).
    """

    NAME = NAME

    def __init__(self):
        # condition_id → {'phase': 1, 'yes_cost': float, 'opened_at': datetime}
        self._open_legs: dict[str, dict] = {}
        self._engine = create_engine(_db_url())
        self._load_open_legs()

    def _load_open_legs(self):
        """Carga legs abiertas desde DB al iniciar (persistencia)."""
        try:
            with self._engine.connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT condition_id, strategy_data
                        FROM poly_positions
                        WHERE status = 'OPEN'
                          AND strategy = :strat
                          AND strategy_data IS NOT NULL
                    """),
                    {'strat': NAME},
                ).fetchall()
                for row in rows:
                    cid = row[0]
                    data_raw = row[1]
                    if isinstance(data_raw, str):
                        try:
                            data = json.loads(data_raw)
                        except (ValueError, TypeError):
                            continue
                    elif isinstance(data_raw, dict):
                        data = data_raw
                    else:
                        continue
                    if data.get('leg_phase') == 1:
                        self._open_legs[cid] = {
                            'phase': 1,
                            'yes_cost': float(data.get('yes_cost', 0)),
                            'opened_at': data.get('opened_at'),
                        }
        except Exception as e:
            logger.debug(f'LEGGED_ARB: Error cargando legs desde DB: {e}')

    def evaluate(self, market: dict, **kwargs) -> dict:
        """Evalúa si el mercado es candidato para Legged Arbitrage.

        Si la posición ya tiene Phase 1 abierta, evalúa si es momento de Phase 2.
        Si no hay Phase 1, evalúa si el precio YES es suficientemente bajo.

        Args:
            market: dict con condition_id, price_yes, price_no, end_date, etc.

        Returns:
            dict con opportunity: True/False y campos del signal.
        """
        condition_id = market.get('condition_id', '')
        question = market.get('question', '')
        price_yes = float(market.get('price_yes', 0))
        price_no = float(market.get('price_no', 0))
        end_date = market.get('end_date')

        # Filtro de seguridad: solo mercados crypto
        _CRYPTO_KW = ('btc', 'bitcoin', 'eth', 'ethereum', 'sol', 'solana',
                      'crypto', 'avax', 'bnb', 'xrp')
        if not any(kw in question.lower() for kw in _CRYPTO_KW):
            return {'opportunity': False, 'reason': 'NON_CRYPTO_MARKET'}

        # Calcular días hasta expiración
        if end_date is None:
            return {'opportunity': False, 'reason': 'NO_END_DATE'}

        now = datetime.now(timezone.utc)
        if isinstance(end_date, str):
            try:
                end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            except ValueError:
                return {'opportunity': False, 'reason': 'INVALID_END_DATE'}
        if not end_date.tzinfo:
            end_date = end_date.replace(tzinfo=timezone.utc)

        days_left = (end_date - now).total_seconds() / 86400
        if days_left <= 0:
            return {'opportunity': False, 'reason': 'MARKET_CLOSED'}

        # ── Phase 2: ya tenemos Phase 1 abierta ──
        if condition_id in self._open_legs:
            leg = self._open_legs[condition_id]
            yes_cost = leg['yes_cost']
            total_cost = yes_cost + price_no

            # Calcular profit garantizado si ejecutamos leg 2
            guaranteed_profit_pct = (1.0 - total_cost) / total_cost * 100

            if guaranteed_profit_pct >= MIN_LEG2_PROFIT_PCT:
                edge = 1.0 - total_cost  # profit garantizado por share
                reasoning = (
                    f'LEGGED_ARB_PHASE2 | NO @ {price_no:.3f} | '
                    f'YES_leg1={yes_cost:.3f} | Total={total_cost:.3f} | '
                    f'Profit garantizado: {guaranteed_profit_pct:.1f}%'
                )
                logger.info(f'SIGNAL_POLY LEGGED_ARB PHASE2: {reasoning} | "{question[:60]}"')

                return {
                    'opportunity': True,
                    'side': 'NO',
                    'edge': round(edge, 4),
                    'entry_price': price_no,
                    'estimated_prob': 0.99,  # profit garantizado
                    'confidence': 95,
                    'reasoning': reasoning,
                    'leg_phase': 2,
                    'leg1_cost': yes_cost,
                    'guaranteed_profit_pct': round(guaranteed_profit_pct, 2),
                    'market': market,
                    'strategy': NAME,
                }

            # Verificar timeout
            opened_at_str = leg.get('opened_at')
            if opened_at_str:
                try:
                    opened_at = datetime.fromisoformat(opened_at_str)
                    if not opened_at.tzinfo:
                        opened_at = opened_at.replace(tzinfo=timezone.utc)
                    if (now - opened_at).days >= MAX_HOLD_DAYS:
                        # Leg 1 expiró por tiempo → limpiar
                        del self._open_legs[condition_id]
                        logger.warning(f'LEGGED_ARB: Leg 1 expirada por timeout: {question[:60]}')
                except (ValueError, TypeError):
                    pass

            return {'opportunity': False, 'reason': f'WAITING_PHASE2:{guaranteed_profit_pct:.1f}%'}

        # ── Phase 1: buscar precio YES bajo ──
        # Solo abrir Phase 1 si hay suficiente tiempo (necesitamos esperar la oscilación)
        if days_left < 1:
            return {'opportunity': False, 'reason': f'INSUFF_TIME:{days_left:.1f}d'}

        if price_yes > MAX_PHASE1_PRICE:
            return {'opportunity': False, 'reason': f'YES_TOO_HIGH:{price_yes:.3f}'}

        # Verificar que el mercado tiene volatilidad (precio NO > 0.60 = hay desequilibrio)
        if price_no < 0.60:
            return {'opportunity': False, 'reason': f'NO_TOO_LOW:{price_no:.3f}'}

        # Edge inicial = la mitad del profit potencial si el mercado se revierte a 50/50
        edge = 0.50 - price_yes

        reasoning = (
            f'LEGGED_ARB_PHASE1 | YES @ {price_yes:.3f} | '
            f'NO @ {price_no:.3f} | {days_left:.1f}d left | '
            f'Potential edge if reverses: {edge:.3f}'
        )
        logger.info(f'SIGNAL_POLY LEGGED_ARB PHASE1: {reasoning} | "{question[:60]}"')

        # Registrar leg 1 (se confirma al ejecutar en el hub)
        self._open_legs[condition_id] = {
            'phase': 1,
            'yes_cost': price_yes,
            'opened_at': now.isoformat(),
        }

        return {
            'opportunity': True,
            'side': 'YES',
            'edge': round(edge, 4),
            'entry_price': price_yes,
            'estimated_prob': min(0.90, price_yes + edge),
            'confidence': 60,
            'reasoning': reasoning,
            'leg_phase': 1,
            'market': market,
            'strategy': NAME,
        }

    def confirm_leg1(self, condition_id: str, actual_cost: float):
        """Actualiza el costo real de leg 1 después de la ejecución."""
        if condition_id in self._open_legs:
            self._open_legs[condition_id]['yes_cost'] = actual_cost

    def cancel_leg1(self, condition_id: str):
        """Cancela una leg 1 (ej. posición cerrada externamente)."""
        self._open_legs.pop(condition_id, None)
