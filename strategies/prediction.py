"""
prediction.py — Estrategia de predicción para mercados Polymarket.

Usa el LLM (GPT-4o-mini) para estimar la probabilidad real de un evento
y compara con el precio de mercado para detectar edge.

Flujo:
  1. Recibe mercado con question + precio actual
  2. Pide al LLM que estime probabilidad del evento
  3. Calcula edge = prob_estimada - precio_mercado
  4. Si edge > MIN_EDGE → genera señal con side (YES/NO) y confianza
"""
import json
import os
import sys
from datetime import datetime, timezone

import yaml

sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv

load_dotenv('/opt/trading/config/.env')

from loguru import logger

with open('/opt/trading/config/exchange_config.yaml') as f:
    _CFG = yaml.safe_load(f).get('polymarket', {})

_RISK = _CFG.get('risk', {})
MIN_EDGE_PCT = _RISK.get('min_edge_pct', 8.0) / 100.0  # 0.08

# Prompt para estimación de probabilidad
_PROBABILITY_PROMPT = """You are an expert prediction market analyst. Your job is to estimate the TRUE probability of an event occurring.

MARKET QUESTION: {question}

CURRENT MARKET PRICE (YES): ${price_yes:.3f} (implies {implied_pct:.1f}% probability)
MARKET VOLUME: ${volume:,.0f}
RESOLUTION DATE: {end_date}
CATEGORY: {category}

Based on your knowledge, estimate the TRUE probability that the answer is YES.

IMPORTANT RULES:
- Be calibrated. If you're uncertain, estimate close to 50%.
- Consider base rates, historical precedent, and current context.
- Markets with high volume are usually well-priced. You need strong reasoning to disagree.
- Account for the date: {current_date}. Consider time remaining until resolution.
- Do NOT blindly agree with the market price. Think independently.

Respond ONLY in valid JSON (no markdown, no code fences):
{{"estimated_probability": <float 0.0 to 1.0>, "confidence": <int 0 to 100>, "reasoning": "<2-3 sentence explanation>", "key_factors": ["<factor1>", "<factor2>", "<factor3>"]}}"""


class PredictionStrategy:
    """Detecta edge en mercados de predicción via análisis LLM."""

    NAME = 'PREDICTION_LLM'

    def __init__(self):
        self._llm = None
        api_key = os.getenv('OPENAI_API_KEY', '')
        if api_key and api_key != 'CHANGE_ME':
            from openai import OpenAI
            self._llm = OpenAI(api_key=api_key)
        self._model = os.getenv('LLM_MODEL', 'gpt-4o-mini')

    def _call_llm(self, prompt: str) -> dict:
        """Llama al LLM y retorna JSON parseado."""
        if not self._llm:
            return {}
        resp = self._llm.chat.completions.create(
            model=self._model,
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0.2,
            max_tokens=500,
        )
        raw = resp.choices[0].message.content.strip()
        # Limpiar posibles code fences
        if raw.startswith('```'):
            raw = raw.split('\n', 1)[1].rsplit('```', 1)[0].strip()
        return json.loads(raw)

    def evaluate(self, market: dict) -> dict:
        """Evalúa un mercado y retorna señal si hay edge suficiente.

        Returns:
            dict con keys: opportunity, side, edge, estimated_prob,
                  confidence, reasoning, market
            Si no hay edge: {'opportunity': False, 'reason': ...}
        """
        question = market.get('question', '')
        price_yes = float(market.get('price_yes', 0.5))
        price_no = float(market.get('price_no', 0.5))
        volume = float(market.get('volume', 0))
        category = market.get('category', 'unknown')
        end_date = market.get('end_date', '')

        # Pedir estimación al LLM
        prompt = _PROBABILITY_PROMPT.format(
            question=question,
            price_yes=price_yes,
            implied_pct=price_yes * 100,
            volume=volume,
            end_date=str(end_date)[:19],
            category=category or 'general',
            current_date=datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        )

        try:
            result = self._call_llm(prompt)
        except Exception as e:
            logger.warning(f'PREDICTION: LLM error for "{question[:50]}": {e}')
            return {'opportunity': False, 'reason': f'LLM_ERROR: {e}'}

        # Parsear resultado
        estimated_prob = float(result.get('estimated_probability', price_yes))
        confidence = int(result.get('confidence', 50))
        reasoning = result.get('reasoning', '')

        # Calcular edge para YES y NO
        edge_yes = estimated_prob - price_yes      # Comprar YES si prob > price
        edge_no = (1 - estimated_prob) - price_no  # Comprar NO si (1-prob) > price_no

        # Determinar el lado con mayor edge
        if edge_yes > edge_no and edge_yes >= MIN_EDGE_PCT:
            side = 'YES'
            edge = edge_yes
            entry_price = price_yes
        elif edge_no > edge_yes and edge_no >= MIN_EDGE_PCT:
            side = 'NO'
            edge = edge_no
            entry_price = price_no
        else:
            return {
                'opportunity': False,
                'reason': f'LOW_EDGE: yes={edge_yes:+.1%} no={edge_no:+.1%} (min={MIN_EDGE_PCT:.0%})',
                'estimated_prob': estimated_prob,
                'confidence': confidence,
            }

        # Filtro: baja confianza del LLM
        if confidence < 40:
            return {
                'opportunity': False,
                'reason': f'LOW_CONFIDENCE: {confidence}% (min=40%)',
                'estimated_prob': estimated_prob,
                'edge': edge,
            }

        logger.info(
            f'PREDICTION: Edge detected! "{question[:50]}" '
            f'side={side} edge={edge:+.1%} prob={estimated_prob:.0%} '
            f'conf={confidence}%'
        )

        return {
            'opportunity': True,
            'side': side,
            'edge': edge,
            'entry_price': entry_price,
            'estimated_prob': estimated_prob,
            'confidence': confidence,
            'reasoning': reasoning,
            'key_factors': result.get('key_factors', []),
            'market': market,
            'strategy': self.NAME,
        }
