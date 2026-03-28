"""
test_trade_monitor.py — Tests unitarios del Trade Monitor.

Verifica la lógica de cierre de trades:
  - SL/TP para BUY y SELL
  - Trailing dinámico: escalones progresivos de R
  - Cálculo de PnL correcto
  - Close reasons correctas (STOP_LOSS, TRAILING_STOP, TAKE_PROFIT)
"""
import sys
import pytest
from unittest.mock import MagicMock, patch, call
from decimal import Decimal

sys.path.insert(0, '/opt/trading')


# ── Helper: crear TradeMonitor mockeado ────────────────────────────

def _make_monitor():
    """TradeMonitor sin DB ni Redis real."""
    with patch('agents.trade_monitor.create_engine'), \
         patch('agents.trade_monitor.redis.Redis'), \
         patch('agents.trade_monitor.MarketFeed'):
        from agents.trade_monitor import TradeMonitor
        monitor = TradeMonitor()
    return monitor


def _make_trade(asset='BTC', side='BUY', entry=75000.0, sl=74000.0,
                tp=76500.0, size=0.1, metadata=None):
    """Crea dict de trade mock."""
    return {
        'id': 'test-trade-001',
        'asset': asset,
        'side': side,
        'entry_price': Decimal(str(entry)),
        'stop_loss': Decimal(str(sl)),
        'take_profit': Decimal(str(tp)),
        'position_size': Decimal(str(size)),
        'status': 'OPEN',
        'metadata': metadata,
    }


# ═══════════════════════════════════════════════════════════════════
# BUY: Cierre por Stop Loss
# ═══════════════════════════════════════════════════════════════════

class TestBuyStopLoss:
    """BUY trade cierra cuando precio ≤ SL."""

    def test_price_at_sl_closes(self):
        monitor = _make_monitor()
        trade = _make_trade(entry=75000, sl=74000, tp=76500, size=0.1)
        monitor._get_current_price = MagicMock(return_value=74000.0)
        monitor._update_trailing = MagicMock()

        result = monitor._evaluate_trade(trade)

        assert result is not None
        assert result['close_reason'] == 'STOP_LOSS'
        assert result['exit_price'] == 74000.0
        # PnL = (SL - entry) × size = (74000 - 75000) × 0.1 = -100
        assert abs(result['pnl'] - (-100.0)) < 0.01

    def test_price_below_sl_closes(self):
        monitor = _make_monitor()
        trade = _make_trade(entry=75000, sl=74000, tp=76500, size=0.1)
        monitor._get_current_price = MagicMock(return_value=73500.0)
        monitor._update_trailing = MagicMock()

        result = monitor._evaluate_trade(trade)
        assert result['close_reason'] == 'STOP_LOSS'

    def test_price_above_sl_stays_open(self):
        monitor = _make_monitor()
        trade = _make_trade(entry=75000, sl=74000, tp=76500, size=0.1)
        monitor._get_current_price = MagicMock(return_value=75200.0)
        monitor._update_trailing = MagicMock()

        result = monitor._evaluate_trade(trade)
        assert result is None  # Trade stays open


# ═══════════════════════════════════════════════════════════════════
# BUY: Cierre por Take Profit
# ═══════════════════════════════════════════════════════════════════

class TestBuyTakeProfit:
    """BUY trade cierra cuando precio ≥ TP."""

    def test_price_at_tp_closes(self):
        monitor = _make_monitor()
        trade = _make_trade(entry=75000, sl=74000, tp=76500, size=0.1)
        monitor._get_current_price = MagicMock(return_value=76500.0)
        monitor._update_trailing = MagicMock()

        result = monitor._evaluate_trade(trade)

        assert result is not None
        assert result['close_reason'] == 'TAKE_PROFIT'
        assert result['exit_price'] == 76500.0
        # PnL = (TP - entry) × size = (76500 - 75000) × 0.1 = 150
        assert abs(result['pnl'] - 150.0) < 0.01

    def test_pnl_percentage_correct(self):
        monitor = _make_monitor()
        trade = _make_trade(entry=75000, sl=74000, tp=76500, size=0.1)
        monitor._get_current_price = MagicMock(return_value=76500.0)
        monitor._update_trailing = MagicMock()

        result = monitor._evaluate_trade(trade)
        # pnl_pct = (TP - entry) / entry × 100 = 1500/75000 × 100 = 2.0%
        assert abs(result['pnl_pct'] - 2.0) < 0.01


# ═══════════════════════════════════════════════════════════════════
# SELL: Cierre por SL y TP
# ═══════════════════════════════════════════════════════════════════

class TestSellTrades:
    """SELL trade: SL arriba (precio ≥ SL), TP abajo (precio ≤ TP)."""

    def test_sell_sl_triggers_on_high_price(self):
        monitor = _make_monitor()
        trade = _make_trade(asset='SOL', side='SELL', entry=97.0,
                            sl=100.0, tp=92.0, size=50.0)
        monitor._get_current_price = MagicMock(return_value=100.0)
        monitor._update_trailing = MagicMock()

        result = monitor._evaluate_trade(trade)

        assert result['close_reason'] == 'STOP_LOSS'
        # PnL = (entry - SL) × size = (97 - 100) × 50 = -150
        assert abs(result['pnl'] - (-150.0)) < 0.01

    def test_sell_tp_triggers_on_low_price(self):
        monitor = _make_monitor()
        trade = _make_trade(asset='SOL', side='SELL', entry=97.0,
                            sl=100.0, tp=92.0, size=50.0)
        monitor._get_current_price = MagicMock(return_value=92.0)
        monitor._update_trailing = MagicMock()

        result = monitor._evaluate_trade(trade)

        assert result['close_reason'] == 'TAKE_PROFIT'
        # PnL = (entry - TP) × size = (97 - 92) × 50 = 250
        assert abs(result['pnl'] - 250.0) < 0.01

    def test_sell_pnl_pct_correct(self):
        monitor = _make_monitor()
        trade = _make_trade(asset='SOL', side='SELL', entry=97.0,
                            sl=100.0, tp=92.0, size=50.0)
        monitor._get_current_price = MagicMock(return_value=92.0)
        monitor._update_trailing = MagicMock()

        result = monitor._evaluate_trade(trade)
        # pnl_pct = (entry - TP) / entry × 100 = 5/97 × 100 = 5.155%
        assert abs(result['pnl_pct'] - 5.155) < 0.01


# ═══════════════════════════════════════════════════════════════════
# Trailing Dinámico Progresivo
# ═══════════════════════════════════════════════════════════════════

class TestTrailingDinamico:
    """Trailing dinámico: SL avanza por escalones de R.

    Setup: entry=75000, SL=74000 → R=1000
    Escalones: 1.0R→BE, 1.5R→+0.5R, 2.0R→+1.0R, 2.5R→+1.5R, 3.0R→+2.0R
    """

    # ── Paso 0: Break-even (1.0R) ──

    def test_buy_trailing_step_0_breakeven(self):
        """BUY: profit = 1.0R → min step=1 → SL sube a entry + 0.3R."""
        monitor = _make_monitor()
        # R = 75000 - 74000 = 1000. 1.0R profit → price = 76000
        trade = _make_trade(entry=75000, sl=74000, tp=78000, size=0.1)
        monitor._get_current_price = MagicMock(return_value=76000.0)
        monitor._update_trailing = MagicMock()

        monitor._evaluate_trade(trade)

        monitor._update_trailing.assert_called_once()
        args = monitor._update_trailing.call_args
        assert abs(args[0][1] - 75300.0) < 1.0  # entry + 0.3R (min step=1)
        assert args[0][2] == 1000.0    # initial_risk
        assert args[0][3] == 1         # level 1 (min)
        assert abs(args[0][4] - 0.3) < 0.01  # locked_r = 0.3

    # ── Paso 1: Lock 0.3R (1.05R) ──

    def test_buy_trailing_step_1_lock_half_r(self):
        """BUY: profit = 1.1R → SL sube a entry + 0.3R."""
        monitor = _make_monitor()
        # 1.1R profit → price = 76100
        trade = _make_trade(entry=75000, sl=74000, tp=78000, size=0.1)
        monitor._get_current_price = MagicMock(return_value=76100.0)
        monitor._update_trailing = MagicMock()

        monitor._evaluate_trade(trade)

        args = monitor._update_trailing.call_args
        assert abs(args[0][1] - 75300.0) < 1.0   # entry + 0.3 × 1000
        assert args[0][3] == 1         # level 1
        assert abs(args[0][4] - 0.3) < 0.01  # locked_r

    # ── Paso 2: Lock 0.6R (1.35R) ──

    def test_buy_trailing_step_2_lock_full_r(self):
        """BUY: profit = 1.4R → SL sube a entry + 0.6R."""
        monitor = _make_monitor()
        trade = _make_trade(entry=75000, sl=74000, tp=78000, size=0.1)
        monitor._get_current_price = MagicMock(return_value=76400.0)
        monitor._update_trailing = MagicMock()

        monitor._evaluate_trade(trade)

        args = monitor._update_trailing.call_args
        assert abs(args[0][1] - 75600.0) < 1.0   # entry + 0.6 × 1000
        assert args[0][3] == 2         # level 2
        assert abs(args[0][4] - 0.6) < 0.01  # locked_r

    # ── Gap: precio salta varios niveles ──

    def test_buy_trailing_gap_multiple_levels(self):
        """BUY: profit = 2.3R → floor((2.3-0.75)/0.3)=5 → locked=1.5R → SL = entry + 1.5R."""
        monitor = _make_monitor()
        trade = _make_trade(entry=75000, sl=74000, tp=80000, size=0.1)
        monitor._get_current_price = MagicMock(return_value=77300.0)
        monitor._update_trailing = MagicMock()

        monitor._evaluate_trade(trade)

        args = monitor._update_trailing.call_args
        assert abs(args[0][1] - 76500.0) < 1.0   # entry + 1.5 × 1000
        assert args[0][3] == 5

    # ── Sin activación (P < 1.0R) ──

    def test_no_trailing_below_activation(self):
        """BUY: profit = 0.5R → sin trailing (activación a 0.75R)."""
        monitor = _make_monitor()
        # 0.5R → price = 75500 (below 0.75R=75750)
        trade = _make_trade(entry=75000, sl=74000, tp=78000, size=0.1)
        monitor._get_current_price = MagicMock(return_value=75500.0)
        monitor._update_trailing = MagicMock()

        monitor._evaluate_trade(trade)

        monitor._update_trailing.assert_not_called()

    # ── SELL: escalones ──

    def test_sell_trailing_step_0_breakeven(self):
        """SELL: entry=97, SL=100 → R=3. P=1.0R (price=94) → min step=1 → SL=96.1."""
        monitor = _make_monitor()
        trade = _make_trade(asset='SOL', side='SELL', entry=97.0,
                            sl=100.0, tp=88.0, size=50.0)
        monitor._get_current_price = MagicMock(return_value=94.0)
        monitor._update_trailing = MagicMock()

        monitor._evaluate_trade(trade)

        args = monitor._update_trailing.call_args
        assert abs(args[0][1] - 96.1) < 0.01  # entry - 0.3R (min step=1)
        assert args[0][3] == 1       # level 1 (min)

    def test_sell_trailing_step_1(self):
        """SELL: P=1.1R (price=93.7) → floor((1.1-0.75)/0.3)=1 → locked=0.3R → SL=entry-0.3R=96.1."""
        monitor = _make_monitor()
        trade = _make_trade(asset='SOL', side='SELL', entry=97.0,
                            sl=100.0, tp=88.0, size=50.0)
        # R=3. 1.1R profit → price = 97 - 1.1*3 = 93.7
        monitor._get_current_price = MagicMock(return_value=93.7)
        monitor._update_trailing = MagicMock()

        monitor._evaluate_trade(trade)

        args = monitor._update_trailing.call_args
        assert abs(args[0][1] - 96.1) < 0.01   # entry - 0.3 × 3
        assert args[0][3] == 1                   # level 1

    # ── SL nunca retrocede ──

    def test_trailing_sl_never_retreats(self):
        """Si SL ya fue avanzado, no retrocede a un nivel menor."""
        monitor = _make_monitor()
        # SL ya en entry+0.5R=75500 (level 1 previo), metadata con initial_risk
        trade = _make_trade(entry=75000, sl=75500.0, tp=78000, size=0.1,
                            metadata={'initial_risk': 1000.0,
                                      'trailing_activated': True,
                                      'trailing_level': 1})
        # Precio en 1.2R → step 0 (BE=75000), pero SL=75500 > 75000 → no retrocede
        monitor._get_current_price = MagicMock(return_value=76200.0)
        monitor._update_trailing = MagicMock()

        monitor._evaluate_trade(trade)

        monitor._update_trailing.assert_not_called()

    # ── initial_risk se preserva en metadata ──

    def test_initial_risk_persisted_in_metadata(self):
        """El initial_risk se pasa a _update_trailing para ser persistido."""
        monitor = _make_monitor()
        trade = _make_trade(entry=75000, sl=74000, tp=78000, size=0.1)
        monitor._get_current_price = MagicMock(return_value=76000.0)
        monitor._update_trailing = MagicMock()

        monitor._evaluate_trade(trade)

        args = monitor._update_trailing.call_args
        assert args[0][2] == 1000.0  # initial_risk = |75000 - 74000|

    def test_initial_risk_from_metadata_preserved(self):
        """Si metadata ya tiene initial_risk, lo usa (no recalcula del SL actual)."""
        monitor = _make_monitor()
        # SL ya movido a 75300 pero initial_risk=1000 (del SL original=74000)
        trade = _make_trade(entry=75000, sl=75300.0, tp=80000, size=0.1,
                            metadata={'initial_risk': 1000.0,
                                      'trailing_activated': True,
                                      'trailing_level': 1})
        # Precio a 2.0R (77000). R=1000. floor((2.0-0.75)/0.3)=4 → locked=1.2R → SL=76200
        monitor._get_current_price = MagicMock(return_value=77000.0)
        monitor._update_trailing = MagicMock()

        monitor._evaluate_trade(trade)

        args = monitor._update_trailing.call_args
        assert abs(args[0][1] - 76200.0) < 1.0   # entry + 1.2 × R(1000)
        assert args[0][2] == 1000.0    # initial_risk from metadata

    # ── Legacy trade (trailing viejo sin initial_risk) ──

    def test_legacy_trade_no_crash(self):
        """Trade legacy: trailing_activated=true, SL=entry, sin initial_risk.
        No debe crashear. initial_risk se recupera via 1.5% proxy."""
        monitor = _make_monitor()
        trade = _make_trade(entry=75000, sl=75000.0, tp=78000, size=0.1,
                            metadata={'trailing_activated': True})
        monitor._get_current_price = MagicMock(return_value=77000.0)
        monitor._update_trailing = MagicMock()

        result = monitor._evaluate_trade(trade)

        # No crash, trailing uses 1.5% proxy fallback (initial_risk=1125)
        monitor._update_trailing.assert_called_once()
        args = monitor._update_trailing.call_args
        assert abs(args[0][2] - 1125.0) < 1.0  # 75000 * 0.015

    # ── TP sigue funcionando con trailing activo ──

    def test_tp_still_closes_with_trailing_active(self):
        """TP cierra el trade independientemente del trailing."""
        monitor = _make_monitor()
        trade = _make_trade(entry=75000, sl=74000, tp=76500, size=0.1)
        # Precio = TP = 76500 (también activa trailing pero TP tiene prioridad de cierre)
        monitor._get_current_price = MagicMock(return_value=76500.0)
        monitor._update_trailing = MagicMock()

        result = monitor._evaluate_trade(trade)

        assert result is not None
        assert result['close_reason'] == 'TAKE_PROFIT'
        assert result['exit_price'] == 76500.0

    # ── Close reason: TRAILING_STOP vs STOP_LOSS ──

    def test_close_reason_trailing_stop(self):
        """Cierre en SL avanzado por trailing → close_reason = TRAILING_STOP."""
        monitor = _make_monitor()
        # SL ya avanzado a 75500 por trailing
        trade = _make_trade(entry=75000, sl=75500.0, tp=78000, size=0.1,
                            metadata={'trailing_activated': True,
                                      'initial_risk': 1000.0,
                                      'trailing_level': 1})
        monitor._get_current_price = MagicMock(return_value=75500.0)  # = SL
        monitor._update_trailing = MagicMock()

        result = monitor._evaluate_trade(trade)

        assert result is not None
        assert result['close_reason'] == 'TRAILING_STOP'
        # PnL = (75500 - 75000) × 0.1 = +50
        assert abs(result['pnl'] - 50.0) < 0.01

    def test_close_reason_original_sl(self):
        """Cierre en SL original (sin trailing) → close_reason = STOP_LOSS."""
        monitor = _make_monitor()
        trade = _make_trade(entry=75000, sl=74000, tp=76500, size=0.1)
        monitor._get_current_price = MagicMock(return_value=74000.0)
        monitor._update_trailing = MagicMock()

        result = monitor._evaluate_trade(trade)

        assert result['close_reason'] == 'STOP_LOSS'

    def test_trailing_breakeven_then_reversal_closes_at_zero(self):
        """Trailing mueve a BE, precio revierte a entry → PnL ≈ $0."""
        monitor = _make_monitor()
        # SL movido a entry (BE) por trailing
        trade = _make_trade(entry=75000, sl=75000.0, tp=78000, size=0.1,
                            metadata={'trailing_activated': True,
                                      'initial_risk': 1000.0,
                                      'trailing_level': 0})
        monitor._get_current_price = MagicMock(return_value=75000.0)
        monitor._update_trailing = MagicMock()

        result = monitor._evaluate_trade(trade)

        assert result is not None
        assert result['close_reason'] == 'TRAILING_STOP'
        assert abs(result['pnl']) < 0.01


# ═══════════════════════════════════════════════════════════════════
# No price data
# ═══════════════════════════════════════════════════════════════════

class TestNoPriceData:
    """Si no hay precio, el trade no se evalúa."""

    def test_no_price_returns_none(self):
        monitor = _make_monitor()
        trade = _make_trade()
        monitor._get_current_price = MagicMock(return_value=None)

        result = monitor._evaluate_trade(trade)
        assert result is None
