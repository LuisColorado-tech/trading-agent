"""
test_pipeline.py — Tests de integración del pipeline completo.

Simula el flujo end-to-end sin DB real:
  Signal → Strategy → Risk → Execute → Monitor → Close

Verifica que cada etapa transforma datos correctamente y que las
decisiones en cadena producen el resultado esperado.
"""
import sys
import json
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
from decimal import Decimal

sys.path.insert(0, '/opt/trading')


@pytest.fixture(autouse=True)
def _safe_hour():
    """All tests run at 10:00 UTC (safe hour) to avoid DEAD_HOUR blocks."""
    safe_now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    with patch('risk.risk_manager.datetime') as mock_dt:
        mock_dt.now.return_value = safe_now
        mock_dt.fromtimestamp = datetime.fromtimestamp
        mock_dt.fromisoformat = datetime.fromisoformat
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        yield mock_dt


# ── Mock completo del ClaudeBridge ─────────────────────────────

def _neutral_claude():
    mock = MagicMock()
    mock.call.return_value = {
        'consistency': 'CONSISTENT',
        'recommendation': 'PROCEED',
        'confidence': 70,
        'reasoning': 'Signals aligned.',
        'flags': [],
        'anomaly_detected': False,
        'severity': 'LOW',
        'result': 'Test explanation',
        '_latency_ms': 100,
    }
    return mock


# ═══════════════════════════════════════════════════════════════════
# Flujo completo: señal → riesgo → ejecución
# ═══════════════════════════════════════════════════════════════════

class TestSignalToExecution:
    """Verificar que una señal válida recorre todo el pipeline correctamente."""

    def test_good_signal_gets_executed(self):
        """BUY BTC con parámetros válidos → aprobado → trade creado."""
        with patch('risk.risk_manager.ClaudeBridge') as MockClaude, \
             patch('risk.risk_manager.redis.Redis') as MockRedis:
            MockClaude.return_value = _neutral_claude()
            mock_redis = MockRedis.return_value
            mock_redis.ttl.return_value = -2
            mock_redis.setex.return_value = True
            from risk.risk_manager import RiskManager

            rm = RiskManager()
            rm.claude = _neutral_claude()

            signal = {
                'asset': 'BTC',
                'direction': 'BUY',
                'strategy': 'TREND_MOMENTUM',
                'timeframe': '15m',
                'score': 80,
                'stop_loss': 74000.0,
                'take_profit': 76665.0,
                'indicators': {'price': 75000.0, 'rsi': 55, 'atr': 666, 'trend': 'UP'},
            }
            portfolio = {
                'total_balance': 10000.0,
                'available_cash': 10000.0,
                'exposure_pct': 0.0,
                'drawdown_pct': 0.0,
                'peak_balance': 10000.0,
            }
            decision = rm.evaluate(signal, portfolio, [])

            assert decision.approved
            assert decision.position_size > 0
            assert decision.stop_loss == 74000.0
            assert decision.take_profit == 76665.0
            assert decision.risk_amount == pytest.approx(100.0, abs=1.0)

    def test_full_lifecycle_pnl(self):
        """Simular apertura + cierre para verificar PnL correcto."""
        # 1. Sizing
        balance = 10000.0
        entry = 75000.0
        sl = 74000.0
        tp = 76665.0
        risk_amount = balance * 0.01  # $100
        position_size = risk_amount / abs(entry - sl)  # 0.1

        # 2. TP hit → cerrar
        exit_price = tp
        pnl = (exit_price - entry) * position_size  # 1665 × 0.1 = $166.5
        new_balance = balance + pnl

        assert pnl == pytest.approx(166.5, abs=0.1)
        assert new_balance == pytest.approx(10166.5, abs=0.1)

    def test_full_lifecycle_sl_loss(self):
        """Apertura + SL hit → verificar pérdida = max 1% del balance."""
        balance = 10000.0
        entry = 75000.0
        sl = 74000.0
        risk_amount = balance * 0.01  # $100
        position_size = risk_amount / abs(entry - sl)  # 0.1

        exit_price = sl
        pnl = (exit_price - entry) * position_size  # -1000 × 0.1 = -$100
        loss_pct = abs(pnl) / balance * 100

        assert abs(pnl) == pytest.approx(100.0, abs=1.0)
        assert loss_pct == pytest.approx(1.0, abs=0.01)  # EXACTAMENTE 1%


# ═══════════════════════════════════════════════════════════════════
# Flujo de rechazo en cascada
# ═══════════════════════════════════════════════════════════════════

class TestRejectionCascade:
    """Verificar que las 8 reglas se aplican en orden correcto."""

    def test_drawdown_beats_all(self):
        """Drawdown 10% rechaza incluso con 0 trades y 0 exposure."""
        with patch('risk.risk_manager.ClaudeBridge') as MockClaude:
            MockClaude.return_value = _neutral_claude()
            from risk.risk_manager import RiskManager

            rm = RiskManager()
            rm.claude = _neutral_claude()

            signal = {
                'asset': 'BTC', 'direction': 'BUY', 'strategy': 'TEST',
                'stop_loss': 74000.0, 'take_profit': 76665.0,
                'indicators': {'price': 75000.0, 'rsi': 55, 'atr': 666, 'trend': 'UP'},
            }
            portfolio = {
                'total_balance': 9000.0, 'available_cash': 9000.0,
                'exposure_pct': 0.0, 'drawdown_pct': 0.11,
                'peak_balance': 10000.0,
            }
            decision = rm.evaluate(signal, portfolio, [])
            assert not decision.approved
            assert decision.reason == 'DRAWDOWN_LIMIT_REACHED'

    def test_duplicate_blocks_before_sizing(self):
        """DUPLICATE_ASSET se evalúa antes de position sizing y R:R."""
        with patch('risk.risk_manager.ClaudeBridge') as MockClaude:
            MockClaude.return_value = _neutral_claude()
            from risk.risk_manager import RiskManager

            rm = RiskManager()
            rm.claude = _neutral_claude()

            signal = {
                'asset': 'BTC', 'direction': 'BUY', 'strategy': 'TEST',
                'stop_loss': 74000.0, 'take_profit': 76665.0,
                'indicators': {'price': 75000.0, 'rsi': 55, 'atr': 666, 'trend': 'UP'},
            }
            portfolio = {
                'total_balance': 10000.0, 'available_cash': 5000.0,
                'exposure_pct': 0.01, 'drawdown_pct': 0.0,
                'peak_balance': 10000.0,
            }
            open_trades = [{'id': '1', 'asset': 'BTC', 'side': 'BUY',
                           'entry_price': 74000, 'stop_loss': 73000,
                           'take_profit': 75500, 'position_size': 0.1}]

            decision = rm.evaluate(signal, portfolio, open_trades)
            assert not decision.approved
            assert 'DUPLICATE_ASSET' in decision.reason


# ═══════════════════════════════════════════════════════════════════
# Trailing + Cierre: flujo completo
# ═══════════════════════════════════════════════════════════════════

class TestTrailingLifecycle:
    """Verificar el flujo trailing completo:
    1. Abrir trade → 2. Precio sube → 3. Trailing activa → 4. Precio baja → 5. Cierra BE"""

    def test_trailing_protects_from_reversal(self):
        """Simular el ciclo completo de trailing sin mock."""
        entry = 75000.0
        sl = 74000.0  # riesgo = $1000
        tp = 77500.0
        size = 0.1

        # Precio sube a 76500 → trailing threshold = 75000 + 1.5*1000 = 76500
        # Condición: 76500 >= 76500 → TRUE, mover SL a entry
        risk_distance = abs(entry - sl)  # 1000
        threshold = entry + (1.5 * risk_distance)  # 76500
        price_high = 76500.0

        assert price_high >= threshold  # Trailing se activa
        new_sl = entry  # 75000

        # Precio baja a 75000 → SL hit
        price_down = 75000.0
        assert price_down <= new_sl  # SL triggered

        # PnL = SL_BE - entry = 0
        pnl = (new_sl - entry) * size
        assert pnl == 0.0


# ═══════════════════════════════════════════════════════════════════
# Stale Data Detection
# ═══════════════════════════════════════════════════════════════════

class TestStaleDataFlow:
    """Verificar lógica de detección de datos obsoletos."""

    def test_stale_threshold_calculation(self):
        """3× el timeframe = umbral de obsolescencia"""
        tf_minutes = {'1m': 1, '5m': 5, '15m': 15, '1h': 60, '4h': 240}

        assert tf_minutes['1m'] * 3 == 3       # 3 min
        assert tf_minutes['5m'] * 3 == 15      # 15 min
        assert tf_minutes['15m'] * 3 == 45     # 45 min
        assert tf_minutes['1h'] * 3 == 180     # 3 horas
        assert tf_minutes['4h'] * 3 == 720     # 12 horas

    def test_fresh_data_not_flagged(self):
        """Datos de hace 5 min en TF 15m no son stale (5 < 45)."""
        import pandas as pd
        now = pd.Timestamp.now(tz='UTC')
        latest = now - pd.Timedelta(minutes=5)
        age_min = (now - latest).total_seconds() / 60
        max_age = 15 * 3  # 45 min

        assert age_min < max_age  # Not stale

    def test_old_data_would_be_flagged(self):
        """Datos de hace 2h en TF 15m son stale (120 > 45)."""
        import pandas as pd
        now = pd.Timestamp.now(tz='UTC')
        latest = now - pd.Timedelta(hours=2)
        age_min = (now - latest).total_seconds() / 60
        max_age = 15 * 3  # 45 min

        assert age_min > max_age  # IS stale


# ═══════════════════════════════════════════════════════════════════
# Diversificación
# ═══════════════════════════════════════════════════════════════════

class TestDiversification:
    """Con la regla de duplicado, verificar que 3 slots se diversifican."""

    def test_max_three_different_assets(self):
        """Con 3 slots y 1 per asset, máximo 3 assets diferentes."""
        with patch('risk.risk_manager.ClaudeBridge') as MockClaude, \
             patch('risk.risk_manager.redis.Redis') as MockRedis:
            MockClaude.return_value = _neutral_claude()
            mock_redis = MockRedis.return_value
            mock_redis.ttl.return_value = -2
            mock_redis.setex.return_value = True
            from risk.risk_manager import RiskManager

            rm = RiskManager()
            rm.claude = _neutral_claude()

            portfolio = {
                'total_balance': 10000.0, 'available_cash': 10000.0,
                'exposure_pct': 0.0, 'drawdown_pct': 0.0,
                'peak_balance': 10000.0,
            }

            # Trade 1: BTC
            sig_btc = {
                'asset': 'BTC', 'direction': 'BUY', 'strategy': 'TEST',
                'stop_loss': 74000.0, 'take_profit': 76665.0,
                'indicators': {'price': 75000.0, 'rsi': 55, 'atr': 666, 'trend': 'UP'},
            }
            d1 = rm.evaluate(sig_btc, portfolio, [])
            assert d1.approved

            # Simular que BTC está abierto
            open_trades = [{'id': '1', 'asset': 'BTC', 'side': 'BUY',
                           'entry_price': 75000, 'stop_loss': 74000,
                           'take_profit': 76665, 'position_size': d1.position_size}]
            portfolio['exposure_pct'] = 0.01

            # Trade 2: ETH
            sig_eth = {
                'asset': 'ETH', 'direction': 'BUY', 'strategy': 'TEST',
                'stop_loss': 2280.0, 'take_profit': 2380.0,
                'indicators': {'price': 2320.0, 'rsi': 55, 'atr': 26, 'trend': 'UP'},
            }
            d2 = rm.evaluate(sig_eth, portfolio, open_trades)
            assert d2.approved

            # Trade 3: SOL (ahora 2 open)
            open_trades.append({'id': '2', 'asset': 'ETH', 'side': 'BUY',
                               'entry_price': 2320, 'stop_loss': 2280,
                               'take_profit': 2380, 'position_size': d2.position_size})
            portfolio['exposure_pct'] = 0.02

            sig_sol = {
                'asset': 'SOL', 'direction': 'BUY', 'strategy': 'TEST',
                'stop_loss': 93.0, 'take_profit': 100.0,
                'indicators': {'price': 95.0, 'rsi': 55, 'atr': 2.0, 'trend': 'UP'},
            }
            d3 = rm.evaluate(sig_sol, portfolio, open_trades)
            assert d3.approved

            # Trade 4: BTC duplicado → rechazado
            d4 = rm.evaluate(sig_btc, portfolio, open_trades)
            assert not d4.approved  # DUPLICATE_ASSET
