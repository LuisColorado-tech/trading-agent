"""Tests unitarios básicos de ExecutionAgent."""
import json
import sys
import uuid
from unittest.mock import MagicMock, patch

sys.path.insert(0, '/opt/trading')


def _approved_decision():
    decision = MagicMock()
    decision.approved = True
    decision.position_size = 0.1
    decision.stop_loss = 74000.0
    decision.take_profit = 76665.0
    decision.risk_amount = 100.0
    decision.reason = 'APPROVED'
    return decision


class TestExecutionAgent:
    def test_session_uuid_is_serialized_in_trade_metadata(self):
        with patch('agents.execution_agent.ccxt.kraken'), \
             patch('agents.execution_agent.redis.Redis'), \
             patch('agents.execution_agent.create_engine'), \
             patch('agents.execution_agent.ClaudeBridge') as MockClaude, \
             patch('agents.execution_agent.RiskManager') as MockRisk, \
             patch('agents.execution_agent.PaperSessionManager') as MockSessionManager:
            MockClaude.return_value.call.return_value = {
                'confidence': 0,
                'reasoning': '',
                'flags': [],
                '_latency_ms': 0,
            }
            MockRisk.return_value.evaluate.return_value = _approved_decision()
            MockSessionManager.return_value.get_active_session.return_value = {
                'id': uuid.uuid4(),
                'session_name': 'PAPER_SESSION_999',
            }

            from agents.execution_agent import ExecutionAgent

            agent = ExecutionAgent()
            agent._save_trade = MagicMock()
            agent._save_explanation = MagicMock()
            agent.redis.publish = MagicMock()

            signal = {
                'asset': 'BTC',
                'direction': 'BUY',
                'strategy': 'TREND_MOMENTUM',
                'indicators': {'price': 75000.0},
            }
            portfolio = {'total_balance': 10000.0}

            result = agent.execute(signal, portfolio, [])

            assert result['executed'] is True
            saved_trade = agent._save_trade.call_args[0][0]
            metadata = json.loads(saved_trade['metadata'])
            assert metadata['paper_session_name'] == 'PAPER_SESSION_999'
            assert isinstance(metadata['paper_session_id'], str)