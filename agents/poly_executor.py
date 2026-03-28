"""
poly_executor.py — Ejecutor de posiciones Polymarket (paper + live).

En paper mode: simula la ejecución y persiste en DB.
En live mode: ejecuta via py-clob-client contra el CLOB.
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone

import redis as _redis
import yaml
from loguru import logger
from sqlalchemy import create_engine, text

sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv

load_dotenv('/opt/trading/config/.env')

with open('/opt/trading/config/exchange_config.yaml') as f:
    _CFG = yaml.safe_load(f).get('polymarket', {})


def _db_url() -> str:
    return (
        f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
        f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT', '5432')}"
        f"/{os.getenv('POSTGRES_DB')}"
    )


class PolyExecutor:
    """Ejecuta posiciones en Polymarket (paper o live)."""

    def __init__(self):
        self.paper_mode = _CFG.get('paper_trading', True)
        self.engine = create_engine(_db_url())
        self.redis = _redis.Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            decode_responses=True,
        )

        if not self.paper_mode:
            from py_clob_client.client import ClobClient
            self.client = ClobClient(
                _CFG.get('host', 'https://clob.polymarket.com'),
                key=os.getenv('POLY_PRIVATE_KEY', ''),
                chain_id=_CFG.get('chain_id', 137),
                signature_type=0,
                funder=os.getenv('POLY_FUNDER_ADDRESS', ''),
            )
            self.client.set_api_creds(self.client.create_or_derive_api_creds())

    def execute(self, signal: dict, risk_decision, session_name: str) -> dict:
        """Ejecuta una posición aprobada por PolyRiskManager.

        Args:
            signal: dict con side, entry_price, market, strategy, etc.
            risk_decision: PolyRiskDecision con shares y cost
            session_name: nombre de sesión paper

        Returns:
            dict con executed, position_id, etc.
        """
        if not risk_decision.approved:
            return {'executed': False, 'reason': risk_decision.reason}

        market = signal.get('market', {})
        side = signal['side']
        entry_price = signal['entry_price']
        shares = risk_decision.shares
        cost = risk_decision.cost

        position_id = str(uuid.uuid4())

        if self.paper_mode:
            order_info = {'type': 'PAPER', 'fill_price': entry_price}
        else:
            order_info = self._execute_live(signal, risk_decision)
            if not order_info:
                return {'executed': False, 'reason': 'LIVE_EXECUTION_FAILED'}

        # Persistir en DB
        self._save_position(
            position_id=position_id,
            market=market,
            side=side,
            strategy=signal.get('strategy', 'PREDICTION_LLM'),
            entry_price=entry_price,
            shares=shares,
            cost=cost,
            session_name=session_name,
            metadata={
                'edge': signal.get('edge', 0),
                'estimated_prob': signal.get('estimated_prob', 0),
                'confidence': signal.get('confidence', 0),
                'reasoning': signal.get('reasoning', ''),
                'key_factors': signal.get('key_factors', []),
                'paper': self.paper_mode,
            },
        )

        # Publicar evento
        self.redis.publish('poly:executed', json.dumps({
            'position_id': position_id,
            'side': side,
            'question': market.get('question', '')[:80],
            'entry_price': entry_price,
            'shares': shares,
            'cost': cost,
            'edge': signal.get('edge', 0),
        }))

        logger.info(
            f'POLY EXECUTED: {side} "{market.get("question", "")[:50]}" '
            f'shares={shares:.1f} @ ${entry_price:.3f} cost=${cost:.2f}'
        )

        return {
            'executed': True,
            'position_id': position_id,
            'side': side,
            'shares': shares,
            'cost': cost,
            'entry_price': entry_price,
        }

    def _execute_live(self, signal: dict, risk_decision) -> dict | None:
        """Ejecuta orden real en Polymarket CLOB."""
        try:
            from py_clob_client.clob_types import MarketOrderArgs, OrderType
            from py_clob_client.order_builder.constants import BUY

            market = signal['market']
            side = signal['side']
            token_id = market['token_yes'] if side == 'YES' else market['token_no']

            mo = MarketOrderArgs(
                token_id=token_id,
                amount=risk_decision.cost,
                side=BUY,
                order_type=OrderType.FOK,
            )
            signed = self.client.create_market_order(mo)
            resp = self.client.post_order(signed, OrderType.FOK)
            logger.info(f'POLY LIVE ORDER: {resp}')
            return resp
        except Exception as e:
            logger.error(f'POLY LIVE EXECUTION FAILED: {e}')
            return None

    def _save_position(self, position_id: str, market: dict, side: str,
                       strategy: str, entry_price: float, shares: float,
                       cost: float, session_name: str, metadata: dict):
        """Guarda posición en DB."""
        with self.engine.connect() as conn:
            conn.execute(
                text('''
                    INSERT INTO poly_positions
                        (id, condition_id, question, side, strategy,
                         entry_price, shares, cost_basis, status,
                         paper_trade, session_name, metadata)
                    VALUES
                        (:id, :cid, :q, :side, :strat,
                         :price, :shares, :cost, 'OPEN',
                         :paper, :sess, :meta)
                '''),
                {
                    'id': position_id,
                    'cid': market.get('condition_id', ''),
                    'q': market.get('question', ''),
                    'side': side,
                    'strat': strategy,
                    'price': entry_price,
                    'shares': shares,
                    'cost': cost,
                    'paper': self.paper_mode,
                    'sess': session_name,
                    'meta': json.dumps(metadata),
                },
            )
            conn.commit()
