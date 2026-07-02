"""
ExecutionAgent — Ejecuta trades aprobados por RiskManager.
Paper mode por defecto. Persiste en PostgreSQL y publica en Redis.

Modos de entrada (Fase 4):
  - 'taker': market order, fill instantáneo al precio de señal. Default.
  - 'limit_maker': orden límite, fill solo si vela posterior toca el precio.
    El trade queda en status PENDING_LIMIT hasta que TradeMonitor lo confirme.
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone

import ccxt
import redis
from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text

sys.path.insert(0, '/opt/trading')
load_dotenv('/opt/trading/config/.env')

from core.claude_bridge import ClaudeBridge
from core.paper_session_manager import PaperSessionManager
from risk.risk_manager import RiskManager, RiskDecision

# ── Configuración de entrada ───────────────────────────────────────
# Fase 4: 'taker' = fill instantáneo, 'limit_maker' = esperar touch de vela.
# Ver docs/PLAN_EJECUCION_15PCT.md §FASE 4.
ENTRY_ORDER_TYPE = 'limit_maker'
MAKER_TIMEOUT_CANDLES = 3


class ExecutionAgent:
    """Ejecuta trades: Risk check -> Order -> Save -> Explain."""

    def __init__(self):
        self.risk = RiskManager()
        self.claude = ClaudeBridge()
        self.paper_mode = os.getenv('PAPER_TRADING', 'true').lower() == 'true'

        self.exchange = ccxt.kraken({
            'apiKey': os.getenv('KRAKEN_API_KEY', ''),
            'secret': os.getenv('KRAKEN_SECRET', ''),
        })

        db_url = (
            f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
            f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT', '5432')}"
            f"/{os.getenv('POSTGRES_DB')}"
        )
        self.engine = create_engine(db_url)
        self.session_manager = PaperSessionManager(db_url)
        self.redis = redis.Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            password=os.getenv('REDIS_PASSWORD') or None,
            decode_responses=True,
        )

    def execute(self, signal: dict, portfolio: dict,
                open_trades: list) -> dict:
        """Flujo completo: Risk check -> Order -> Save -> Explain."""

        # 1. Risk Manager decision (autoridad final)
        decision = self.risk.evaluate(signal, portfolio, open_trades)

        if not decision.approved:
            logger.info(f'Trade REJECTED: {decision.reason}')
            return {'executed': False, 'reason': decision.reason}

        asset = signal['asset']

        # 2. Colocar orden
        try:
            if self.paper_mode:
                order = self._simulate_order(signal, decision)
            else:
                symbol = f'{asset}/USDT'
                side_lower = signal['direction'].lower()
                order = self.exchange.create_order(
                    symbol=symbol,
                    type='market',
                    side=side_lower,
                    amount=decision.position_size,
                )
                # Stop loss: usar stop-loss order type de Kraken
                sl_side = 'sell' if side_lower == 'buy' else 'buy'
                self.exchange.create_order(
                    symbol=symbol,
                    type='stop-loss',
                    side=sl_side,
                    amount=decision.position_size,
                    price=decision.stop_loss,
                )
                # Take profit: limit order
                self.exchange.create_order(
                    symbol=symbol,
                    type='take-profit',
                    side=sl_side,
                    amount=decision.position_size,
                    price=decision.take_profit,
                )
        except Exception as e:
            logger.error(f'Order execution error: {e}')
            return {'executed': False, 'reason': f'exchange_error: {e}'}

        # 3. Guardar trade en DB
        trade_id = str(uuid.uuid4())
        active_session = self.session_manager.get_active_session() if self.paper_mode else None
        entry_price = signal['indicators']['price']
        initial_risk = abs(entry_price - decision.stop_loss)
        order_type = ENTRY_ORDER_TYPE if self.paper_mode else 'taker'
        trade_status = 'PENDING_LIMIT' if (self.paper_mode and ENTRY_ORDER_TYPE == 'limit_maker') else 'OPEN'

        trade_data = {
            'id': trade_id,
            'asset': asset,
            'side': signal['direction'],
            'strategy': signal['strategy'],
            'entry_price': entry_price,
            'stop_loss': decision.stop_loss,
            'take_profit': decision.take_profit,
            'position_size': decision.position_size,
            'position_pct': (
                decision.risk_amount / portfolio['total_balance']
                if portfolio.get('total_balance', 0) > 0 else 0
            ),
            'paper_trade': self.paper_mode,
            'timestamp_open': datetime.now(timezone.utc).isoformat(),
            'metadata': json.dumps({
                'paper_session_id': str(active_session['id']) if active_session else None,
                'paper_session_name': active_session['session_name'] if active_session else None,
                'initial_risk': initial_risk,
                'regime': signal.get('market_regime', 'unknown'),
                'timeframe': signal.get('timeframe', '15m'),
                'entry_order_type': order_type,
                'limit_price': entry_price,
                'maker_timeout_candles': MAKER_TIMEOUT_CANDLES,
                'maker_pending_since': datetime.now(timezone.utc).isoformat(),
            }),
        }
        self._save_trade(trade_data, trade_status)

        # 4. Claude explanation (no bloquea ejecución)
        try:
            explanation = self.claude.call(
                task_type='explain_trade',
                asset=asset,
                data={
                    'trade': trade_data,
                    'signal': signal,
                    'decision': {
                        'approved': decision.approved,
                        'position_size': decision.position_size,
                        'risk_amount': decision.risk_amount,
                        'reason': decision.reason,
                    },
                },
                portfolio_context=portfolio,
            )
            self._save_explanation(trade_id, asset, 'explain_trade', explanation)
        except Exception as e:
            logger.warning(f'Claude explanation failed (non-critical): {e}')

        # 5. Publicar evento en Redis
        self.redis.publish('trades:executed', json.dumps({
            'trade_id': trade_id,
            'asset': asset,
            'side': signal['direction'],
            'price': signal['indicators']['price'],
        }))

        logger.info(
            f'TRADE EXECUTED: {trade_id} {asset} {signal["direction"]} '
            f'{decision.position_size:.6f} @ {signal["indicators"]["price"]}'
        )
        return {'executed': True, 'trade_id': trade_id, 'order': order}

    def _simulate_order(self, signal: dict, decision: RiskDecision) -> dict:
        if ENTRY_ORDER_TYPE == 'limit_maker' and self.paper_mode:
            return {
                'id': f'PAPER_{uuid.uuid4().hex[:8]}',
                'symbol': f'{signal["asset"]}/USDT',
                'side': signal['direction'],
                'amount': decision.position_size,
                'price': signal['indicators']['price'],
                'type': 'limit',
                'status': 'open',
            }
        return {
            'id': f'PAPER_{uuid.uuid4().hex[:8]}',
            'symbol': f'{signal["asset"]}/USDT',
            'side': signal['direction'],
            'amount': decision.position_size,
            'price': signal['indicators']['price'],
            'type': 'market',
            'status': 'closed',
        }

    def _save_trade(self, data: dict, status: str = 'OPEN'):
        with self.engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO trades
                        (id, asset, side, strategy, entry_price, stop_loss,
                         take_profit, position_size, position_pct,
                         paper_trade, timestamp_open, metadata, status)
                    VALUES
                        (:id, :asset, :side, :strategy, :entry_price, :stop_loss,
                         :take_profit, :position_size, :position_pct,
                         :paper_trade, :timestamp_open, CAST(:metadata AS jsonb), :status)
                """),
                {**data, 'status': status},
            )

    def _save_explanation(self, trade_id: str, asset: str,
                          task_type: str, result: dict):
        with self.engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO claude_explanations
                        (task_type, asset, trade_id, input_payload, result,
                         confidence, reasoning, flags, latency_ms)
                    VALUES
                        (:task_type, :asset, :trade_id, :input_payload, :result,
                         :confidence, :reasoning, :flags, :latency_ms)
                """),
                {
                    'task_type': task_type,
                    'asset': asset,
                    'trade_id': trade_id,
                    'input_payload': json.dumps({}),
                    'result': json.dumps(result, default=str),
                    'confidence': result.get('confidence', 0),
                    'reasoning': result.get('reasoning', ''),
                    'flags': result.get('flags', []),
                    'latency_ms': result.get('_latency_ms', 0),
                },
            )


# ── CLI test ──
if __name__ == '__main__':
    from agents.strategy_engine import StrategyEngine
    load_dotenv('/opt/trading/config/.env')

    # Simular portfolio
    portfolio = {
        'total_balance': 10000.0,
        'exposure_pct': 0.0,
        'drawdown_pct': 0.0,
    }

    engine = StrategyEngine()
    agent = ExecutionAgent()

    # Buscar oportunidades y ejecutar la primera
    opps = engine.scan_all(portfolio)
    print(f'\n=== {len(opps)} opportunities found ===')

    executed = 0
    for opp in opps[:3]:  # Intentar hasta 3
        print(f'\nEvaluating: {opp["asset"]}/{opp["timeframe"]} '
              f'{opp["strategy"]} {opp["direction"]}')
        result = agent.execute(opp, portfolio, [])
        print(f'  Result: {result}')
        if result.get('executed'):
            executed += 1

    print(f'\n=== {executed} trades executed (paper mode) ===')
