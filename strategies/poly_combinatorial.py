"""
poly_combinatorial.py — Combinatorial Arbitrage Strategy para Polymarket.

Basada en el repo Anmoldureha/polymarket-trading-bot-strategies (24★).

Estrategia: detectar contradicciones lógicas entre mercados relacionados.

Principio: si el Mercado A pregunta "BTC > $80k" y el Mercado B pregunta
"BTC > $85k", necesariamente P(B) ≤ P(A) (subconjunto estricto).
Si el mercado viola esto (P(B) > P(A)), existe una oportunidad de arb:
comprar NO del mercado "caro" (el que viola la lógica).

Ejemplo real:
  "Will BTC hit $80,000 in April?" → 60%
  "Will BTC hit $85,000 in April?" → 65%  ← CONTRADICCIÓN → comprar NO aquí

Esta estrategia solo genera señales, no coloca hedges. El hub se encarga
de ejecutar el lado rentable.
"""
import re
import sys
from datetime import datetime, timezone, timedelta
from itertools import combinations

import yaml
from loguru import logger

sys.path.insert(0, '/opt/trading')

with open('/opt/trading/config/exchange_config.yaml') as f:
    _POLY_CFG = yaml.safe_load(f).get('polymarket', {})

NAME = 'combinatorial'

_STRAT_CFG = _POLY_CFG.get('strategies', {}).get('combinatorial', {})

# Diferencia mínima de probabilidad para que valga la pena el trade
MIN_PROB_DIFF = _STRAT_CFG.get('min_prob_diff', 0.05)  # 5%
# Período de agrupación: mercados con end_date dentro de N días entre sí
GROUP_END_WINDOW_DAYS = _STRAT_CFG.get('group_end_window_days', 5)
# Activos a monitorear
ASSETS = ['BTC', 'Bitcoin', 'ETH', 'Ethereum', 'SOL', 'Solana']

# Patrones para extraer umbrales numéricos de preguntas
_PRICE_PATTERNS = [
    r'\$\s*([\d,]+(?:\.\d+)?)\s*k\b',  # "$80k", "$80.5k"
    r'\$\s*([\d,]+(?:\.\d+)?)\b',       # "$80,000", "$80000", "$80.5"
]


def _extract_price_target(question: str) -> float | None:
    """Extrae el precio objetivo numérico de una pregunta.

    Returns: float (en USD, no en k) o None si no se pudo extraer.
    """
    q = question.replace(',', '')  # eliminar comas en números

    for pattern in _PRICE_PATTERNS:
        match = re.search(pattern, q, re.IGNORECASE)
        if match:
            val = float(match.group(1).replace(',', ''))
            # Si termina en 'k', multiplicar por 1000
            if 'k' in match.group(0).lower():
                val *= 1000
            return val
    return None


def _detect_asset(question: str) -> str | None:
    """Detecta el activo principal de la pregunta."""
    q = question.upper()
    if 'BTC' in q or 'BITCOIN' in q:
        return 'BTC'
    if 'ETH' in q or 'ETHEREUM' in q:
        return 'ETH'
    if 'SOL' in q or 'SOLANA' in q:
        return 'SOL'
    return None


class CombinatorialArbPolyStrategy:
    """
    Combinatorial Arbitrage: detectar violaciones de monotonía entre mercados.

    Recibe TODOS los mercados activos y busca pares donde las probabilidades
    son inconsistentes con la lógica de subconjuntos.
    """

    NAME = NAME

    def find_opportunities(self, markets: list[dict]) -> list[dict]:
        """Busca oportunidades de arbitraje combinatorial entre todos los mercados.

        Args:
            markets: lista de dicts de mercados activos

        Returns:
            lista de signals con opportunity: True y todos los campos estándar.
        """
        signals = []

        # Agrupar por activo
        by_asset: dict[str, list[dict]] = {}
        for m in markets:
            asset = _detect_asset(m.get('question', ''))
            if asset is None:
                continue
            target = _extract_price_target(m.get('question', ''))
            if target is None:
                continue
            m['_asset'] = asset
            m['_target'] = target
            by_asset.setdefault(asset, []).append(m)

        # Buscar pares inconsistentes dentro de cada grupo de activo
        for asset, asset_markets in by_asset.items():
            if len(asset_markets) < 2:
                continue

            # Filtrar por end_date cercana (agrupar por período)
            groups = self._group_by_period(asset_markets)

            for group in groups:
                if len(group) < 2:
                    continue
                group_signals = self._find_monotonicity_violations(group)
                signals.extend(group_signals)

        return signals

    def _group_by_period(self, markets: list[dict]) -> list[list[dict]]:
        """Agrupa mercados con end_date cercana (±GROUP_END_WINDOW_DAYS)."""
        if not markets:
            return []

        now = datetime.now(timezone.utc)
        sorted_markets = sorted(
            markets,
            key=lambda m: (m.get('end_date') or now).replace(tzinfo=timezone.utc)
            if isinstance(m.get('end_date'), datetime) and not (m.get('end_date') or now).tzinfo
            else (m.get('end_date') or now)
        )

        groups = []
        current_group = [sorted_markets[0]]

        for m in sorted_markets[1:]:
            ref_end = current_group[0].get('end_date')
            cur_end = m.get('end_date')

            if ref_end and cur_end:
                # Asegurar timezone
                if isinstance(ref_end, datetime) and not ref_end.tzinfo:
                    ref_end = ref_end.replace(tzinfo=timezone.utc)
                if isinstance(cur_end, datetime) and not cur_end.tzinfo:
                    cur_end = cur_end.replace(tzinfo=timezone.utc)

                if isinstance(ref_end, datetime) and isinstance(cur_end, datetime):
                    diff_days = abs((cur_end - ref_end).days)
                    if diff_days <= GROUP_END_WINDOW_DAYS:
                        current_group.append(m)
                        continue

            groups.append(current_group)
            current_group = [m]

        if current_group:
            groups.append(current_group)

        return groups

    def _find_monotonicity_violations(self, group: list[dict]) -> list[dict]:
        """Detecta violaciones de monotonicidad en un grupo de mercados.

        Regla: para preguntas "¿X > threshold?", a mayor threshold → menor probabilidad.
        Si P(threshold_alto) > P(threshold_bajo) → contradicción → short el caro.
        """
        signals = []
        threshold_key = '_target'
        prob_key = 'price_yes'  # p(YES) = probabilidad del evento

        # Ordenar por threshold ascendente
        sorted_group = sorted(group, key=lambda m: m.get(threshold_key, 0))

        # Comparar todos los pares
        for i in range(len(sorted_group)):
            for j in range(i + 1, len(sorted_group)):
                low_m = sorted_group[i]
                high_m = sorted_group[j]

                low_threshold = low_m.get(threshold_key, 0)
                high_threshold = high_m.get(threshold_key, 0)
                low_prob = float(low_m.get(prob_key, 0))
                high_prob = float(high_m.get(prob_key, 0))

                # Violación: P(higher_threshold) > P(lower_threshold) + buffer
                # buffer = MIN_PROB_DIFF para evitar ruido
                if high_prob > low_prob + MIN_PROB_DIFF:
                    prob_diff = high_prob - low_prob
                    asset = high_m.get('_asset', 'UNKNOWN')

                    # Acción: comprar NO del mercado con precio más alto (el "caro")
                    # porque lógicamente su probabilidad debería ser menor
                    entry_price = 1.0 - high_prob  # precio del NO = 1 - price_yes
                    edge = prob_diff  # el edge es la magnitud de la violación

                    reasoning = (
                        f'COMBINATORIAL_ARB | {asset} | '
                        f'Threshold ${low_threshold:,.0f} @ {low_prob:.1%} < '
                        f'Threshold ${high_threshold:,.0f} @ {high_prob:.1%} '
                        f'[VIOLACIÓN {prob_diff:.1%}] → Buy NO of high market'
                    )
                    logger.info(
                        f'SIGNAL_POLY COMBINATORIAL: {reasoning} | '
                        f'"{high_m["question"][:60]}"'
                    )

                    signals.append({
                        'opportunity': True,
                        'side': 'NO',
                        'edge': round(edge, 4),
                        'entry_price': round(entry_price, 4),
                        'estimated_prob': min(0.90, 1.0 - high_prob + edge * 0.5),
                        'confidence': min(95, int(prob_diff * 200)),  # 0-95%
                        'reasoning': reasoning,
                        'prob_diff': round(prob_diff, 4),
                        'reference_market': low_m.get('condition_id'),
                        'reference_prob': low_prob,
                        'market': high_m,
                        'strategy': NAME,
                    })

        return signals

    def evaluate(self, market: dict, all_markets: list[dict] | None = None, **kwargs) -> dict:
        """Interfaz compatible con el hub: evalúa un solo mercado.

        Para combinatorial, la lógica real está en find_opportunities().
        Este método es un wrapper para compatibilidad con el loop estándar.
        """
        if all_markets:
            signals = self.find_opportunities(all_markets)
            # Retornar la primera señal que involucre este mercado
            for sig in signals:
                if sig['market'].get('condition_id') == market.get('condition_id'):
                    return sig
        return {'opportunity': False, 'reason': 'NO_VIOLATION_FOUND'}
