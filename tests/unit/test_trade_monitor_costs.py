"""
test_trade_monitor_costs.py — PnL neto en el cierre de trades.

Verifica que _close_trade:
  - Persiste pnl NETO, pnl_gross y fee_paid en la tabla trades
  - Actualiza el balance del portfolio con el PnL neto (no el bruto)
  - Devuelve el dict que check_open_trades reporta hacia afuera
"""
import sys
import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch

sys.path.insert(0, '/opt/trading')

from core.cost_model import net_pnl


def _make_monitor():
    with patch('agents.trade_monitor.create_engine'), \
         patch('agents.trade_monitor.redis.Redis'), \
         patch('agents.trade_monitor.MarketFeed'):
        from agents.trade_monitor import TradeMonitor
        monitor = TradeMonitor()
    monitor._get_open_trades = MagicMock(return_value=[])
    monitor._get_historical_peak_balance = MagicMock(return_value=10000.0)
    return monitor


def _make_trade(asset='BTC', side='BUY', entry=75000.0, sl=74000.0,
                tp=76500.0, size=0.1):
    return {
        'id': 'test-trade-001',
        'asset': asset,
        'side': side,
        'strategy': 'TREND_MOMENTUM',
        'entry_price': Decimal(str(entry)),
        'stop_loss': Decimal(str(sl)),
        'take_profit': Decimal(str(tp)),
        'position_size': Decimal(str(size)),
        'status': 'OPEN',
        'metadata': None,
    }


def _captured_update_params(monitor) -> dict:
    """Extrae los parámetros del UPDATE trades ejecutado contra la DB mock."""
    conn = monitor.engine.begin.return_value.__enter__.return_value
    for call in conn.execute.call_args_list:
        params = call.args[1] if len(call.args) > 1 else call.kwargs
        if isinstance(params, dict) and 'pnl_gross' in params:
            return params
    raise AssertionError('No se ejecutó UPDATE trades con pnl_gross/fee_paid')


class TestCloseTradeNetPnl:

    def test_persists_net_gross_and_fee(self):
        monitor = _make_monitor()
        trade = _make_trade()
        portfolio = {'total_balance': 10000.0, 'available_cash': 10000.0,
                     'peak_balance': 10000.0}

        result = monitor._close_trade(trade, 76500.0, 'TAKE_PROFIT', portfolio)

        params = _captured_update_params(monitor)
        gross_expected = (76500.0 - 75000.0) * 0.1  # +150
        # BTC → OKX (Fase 4). Fase 4: TP usa maker en exit, entry es taker por defecto
        net_expected, fee_expected = net_pnl(
            gross_expected, 75000.0, 76500.0, 0.1, 'okx',
            entry_order_type='taker', exit_order_type='maker',
        )

        assert params['pnl_gross'] == pytest.approx(gross_expected)
        assert params['fee_paid'] == pytest.approx(fee_expected)
        assert params['pnl'] == pytest.approx(net_expected)
        assert params['pnl'] < params['pnl_gross']

        # El dict devuelto (lo que reporta check_open_trades) es coherente
        assert result['pnl'] == pytest.approx(net_expected)
        assert result['pnl_gross'] == pytest.approx(gross_expected)
        assert result['fee_paid'] == pytest.approx(fee_expected)

    def test_portfolio_balance_uses_net(self):
        monitor = _make_monitor()
        trade = _make_trade()
        portfolio = {'total_balance': 10000.0, 'available_cash': 10000.0,
                     'peak_balance': 10000.0}

        result = monitor._close_trade(trade, 76500.0, 'TAKE_PROFIT', portfolio)

        assert portfolio['total_balance'] == pytest.approx(10000.0 + result['pnl'])
        # Con bruto habría sido 10150 — el neto debe ser estrictamente menor
        assert portfolio['total_balance'] < 10150.0

    def test_sell_stop_loss_costs_extra(self):
        """Un SL en SELL pierde el bruto MÁS el fee — la pérdida neta es mayor."""
        monitor = _make_monitor()
        trade = _make_trade(side='SELL', entry=97.0, sl=100.0, tp=92.0, size=50.0)
        portfolio = {'total_balance': 10000.0, 'available_cash': 10000.0,
                     'peak_balance': 10000.0}

        result = monitor._close_trade(trade, 100.0, 'STOP_LOSS', portfolio)

        gross = (97.0 - 100.0) * 50.0  # -150
        assert result['pnl_gross'] == pytest.approx(gross)
        assert result['pnl'] < gross
        assert result['fee_paid'] > 0

    def test_unknown_asset_falls_back_to_gross(self):
        """Activo fuera de ASSET_MAP: no rompe el cierre, PnL queda bruto
        y fee 0 (con warning en logs)."""
        monitor = _make_monitor()
        trade = _make_trade(asset='ACTIVO_INEXISTENTE')
        portfolio = {'total_balance': 10000.0, 'available_cash': 10000.0,
                     'peak_balance': 10000.0}

        result = monitor._close_trade(trade, 76500.0, 'TAKE_PROFIT', portfolio)

        assert result['pnl'] == pytest.approx(result['pnl_gross'])
        assert result['fee_paid'] == 0.0
