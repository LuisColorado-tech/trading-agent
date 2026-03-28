"""
test_risk_manager.py — Tests unitarios del Motor de Riesgo.

Verifica cada una de las 8 reglas del RiskManager:
  0. Trading halt
  1. Drawdown máximo
  2. Exposición máxima
  3. Trades concurrentes
  3b. Duplicación por activo
  4. Position sizing + post-sizing exposure
  5. Ratio R:R mínimo
  6. Claude anomaly (mockeado)

Cada test es independiente y no requiere DB ni conexión a exchanges.
"""
import sys
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '/opt/trading')


# ── Autouse: mock datetime to safe hour (avoids DEAD_HOUR blocks) ──

@pytest.fixture(autouse=True)
def _safe_hour():
    """All tests run at 10:00 UTC (safe hour) unless explicitly overridden."""
    safe_now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    with patch('risk.risk_manager.datetime') as mock_dt:
        mock_dt.now.return_value = safe_now
        mock_dt.fromtimestamp = datetime.fromtimestamp
        mock_dt.fromisoformat = datetime.fromisoformat
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        yield mock_dt


# ── Helpers ──────────────────────────────────────────────────────

def _make_risk_manager():
    """Crea RiskManager con Claude y Redis mockeados (no requiere API key ni Redis)."""
    with patch('risk.risk_manager.ClaudeBridge') as MockClaude, \
         patch('risk.risk_manager.redis.Redis') as MockRedis:
        mock_claude = MockClaude.return_value
        mock_claude.call.return_value = {
            'anomaly_detected': False,
            'severity': 'LOW',
            'confidence': 10,
            'reasoning': 'No anomaly detected.',
            'flags': [],
        }
        mock_redis = MockRedis.return_value
        # Stateful mock: setex stores keys, ttl looks them up
        _redis_store = {}
        def _mock_setex(key, ttl_val, value):
            _redis_store[key] = ttl_val
            return True
        def _mock_ttl(key):
            return _redis_store.get(key, -2)
        mock_redis.setex.side_effect = _mock_setex
        mock_redis.ttl.side_effect = _mock_ttl
        from risk.risk_manager import RiskManager
        rm = RiskManager()
        rm.claude = mock_claude
    return rm


# ═══════════════════════════════════════════════════════════════════
# REGLA 0: Trading Halt
# ═══════════════════════════════════════════════════════════════════

class TestTradingHalt:
    """Cuando el sistema está en halt, NO se admite ningún trade."""

    def test_halted_system_rejects_all(self, base_portfolio, btc_buy_signal, no_open_trades):
        rm = _make_risk_manager()
        rm._trading_halted = True
        rm._halt_reason = 'TEST_HALT'
        decision = rm.evaluate(btc_buy_signal, base_portfolio, no_open_trades)
        assert not decision.approved
        assert 'TRADING_HALTED' in decision.reason

    def test_resume_requires_manual_override(self):
        rm = _make_risk_manager()
        rm._trading_halted = True
        with pytest.raises(PermissionError):
            rm.resume_trading(manual_override=False)

    def test_resume_with_override_works(self):
        rm = _make_risk_manager()
        rm._trading_halted = True
        rm.resume_trading(manual_override=True)
        assert not rm._trading_halted


# ═══════════════════════════════════════════════════════════════════
# REGLA 1: Drawdown máximo (10%)
# ═══════════════════════════════════════════════════════════════════

class TestDrawdownLimit:
    """Drawdown ≥ 10% detiene todo el trading permanentemente."""

    def test_drawdown_at_limit_halts(self, portfolio_max_drawdown, btc_buy_signal, no_open_trades):
        rm = _make_risk_manager()
        decision = rm.evaluate(btc_buy_signal, portfolio_max_drawdown, no_open_trades)
        assert not decision.approved
        assert decision.reason == 'DRAWDOWN_LIMIT_REACHED'
        assert rm._trading_halted is True

    def test_drawdown_below_limit_passes(self, base_portfolio, btc_buy_signal, no_open_trades):
        rm = _make_risk_manager()
        base_portfolio['drawdown_pct'] = 0.05  # 5% < 10%
        decision = rm.evaluate(btc_buy_signal, base_portfolio, no_open_trades)
        assert decision.approved


# ═══════════════════════════════════════════════════════════════════
# REGLA 2: Exposición máxima (5%)
# ═══════════════════════════════════════════════════════════════════

class TestExposureLimit:
    """Exposición ≥ 5% rechaza nuevos trades."""

    def test_exposure_at_limit_rejects(self, base_portfolio, btc_buy_signal, no_open_trades):
        rm = _make_risk_manager()
        base_portfolio['exposure_pct'] = 0.05  # exacto 5%
        decision = rm.evaluate(btc_buy_signal, base_portfolio, no_open_trades)
        assert not decision.approved
        assert decision.reason == 'MAX_EXPOSURE_REACHED'

    def test_exposure_below_limit_passes(self, portfolio_with_exposure, btc_buy_signal, no_open_trades):
        rm = _make_risk_manager()
        decision = rm.evaluate(btc_buy_signal, portfolio_with_exposure, no_open_trades)
        assert decision.approved


# ═══════════════════════════════════════════════════════════════════
# REGLA 3: Trades concurrentes (max 3)
# ═══════════════════════════════════════════════════════════════════

class TestConcurrentTrades:
    """Máximo 3 trades abiertos simultáneamente."""

    def test_three_open_rejects(self, base_portfolio, btc_buy_signal, three_trades_open):
        rm = _make_risk_manager()
        decision = rm.evaluate(btc_buy_signal, base_portfolio, three_trades_open)
        assert not decision.approved
        assert decision.reason == 'MAX_CONCURRENT_TRADES'

    def test_two_open_allows(self, base_portfolio, eth_buy_signal, two_trades_open):
        rm = _make_risk_manager()
        # ETH ya está en two_trades_open, usar SOL signal
        sol_signal = eth_buy_signal.copy()
        sol_signal['asset'] = 'SOL'
        sol_signal['indicators'] = {'price': 95.0, 'rsi': 55, 'atr': 2.0, 'trend': 'UP'}
        sol_signal['stop_loss'] = 92.0
        sol_signal['take_profit'] = 100.0
        decision = rm.evaluate(sol_signal, base_portfolio, two_trades_open)
        assert decision.approved


# ═══════════════════════════════════════════════════════════════════
# REGLA 3b: Duplicación por activo (max 1 por asset)
# ═══════════════════════════════════════════════════════════════════

class TestDuplicateAsset:
    """No se permite más de 1 trade abierto por activo."""

    def test_duplicate_btc_rejected(self, base_portfolio, btc_buy_signal, one_btc_open):
        rm = _make_risk_manager()
        decision = rm.evaluate(btc_buy_signal, base_portfolio, one_btc_open)
        assert not decision.approved
        assert 'DUPLICATE_ASSET' in decision.reason
        assert 'BTC' in decision.reason

    def test_different_asset_allowed(self, base_portfolio, eth_buy_signal, one_btc_open):
        rm = _make_risk_manager()
        decision = rm.evaluate(eth_buy_signal, base_portfolio, one_btc_open)
        assert decision.approved

    def test_duplicate_check_after_max_concurrent(self, base_portfolio, btc_buy_signal):
        """La regla de duplicado se aplica DESPUÉS de la de concurrentes."""
        rm = _make_risk_manager()
        one_open = [{'id': '1', 'asset': 'BTC', 'side': 'BUY',
                      'entry_price': 74000, 'stop_loss': 73000,
                      'take_profit': 75500, 'position_size': 0.1}]
        decision = rm.evaluate(btc_buy_signal, base_portfolio, one_open)
        assert not decision.approved
        assert 'DUPLICATE_ASSET' in decision.reason


# ═══════════════════════════════════════════════════════════════════
# REGLA 4: Position Sizing
# ═══════════════════════════════════════════════════════════════════

class TestPositionSizing:
    """Verificar cálculo: size = (1% × balance) / |entry - SL|"""

    def test_position_size_formula(self, base_portfolio, btc_buy_signal, no_open_trades):
        rm = _make_risk_manager()
        decision = rm.evaluate(btc_buy_signal, base_portfolio, no_open_trades)
        assert decision.approved

        entry = btc_buy_signal['indicators']['price']  # 75000
        sl = btc_buy_signal['stop_loss']                # 74000
        risk_per_unit = abs(entry - sl)                  # 1000
        raw_size = (10000 * 0.01) / risk_per_unit        # 100 / 1000 = 0.1
        # Notional cap: 0.1 * 75000 = $7500 > 50% de $10k = $5000 → recortado
        max_notional = 10000 * 0.50
        expected_size = max_notional / entry              # 5000 / 75000 ≈ 0.0667

        assert abs(decision.position_size - expected_size) < 0.001

    def test_risk_amount_is_one_percent(self, base_portfolio, btc_buy_signal, no_open_trades):
        rm = _make_risk_manager()
        decision = rm.evaluate(btc_buy_signal, base_portfolio, no_open_trades)
        assert decision.approved
        assert abs(decision.risk_amount - 100.0) < 0.01  # 1% de $10K = $100

    def test_zero_risk_per_unit_rejected(self, base_portfolio, no_open_trades):
        rm = _make_risk_manager()
        signal = {
            'asset': 'BTC', 'direction': 'BUY', 'strategy': 'TEST',
            'stop_loss': 75000.0,       # SL = entry → risk = 0
            'take_profit': 76000.0,
            'indicators': {'price': 75000.0, 'rsi': 55, 'atr': 500, 'trend': 'UP'},
        }
        decision = rm.evaluate(signal, base_portfolio, no_open_trades)
        assert not decision.approved
        assert decision.reason == 'ZERO_RISK_PER_UNIT'

    def test_post_sizing_exposure_check(self, portfolio_high_exposure, btc_buy_signal, two_trades_open):
        """Con 4.5% exposure + 1% nuevo = 5.5% → rechazar.
        Con cash=$2k y notional SOL ~$3167 (capped a $5k), falla primero por INSUFFICIENT_CASH."""
        rm = _make_risk_manager()
        signal = btc_buy_signal.copy()
        signal['asset'] = 'SOL'
        signal['indicators'] = {'price': 95.0, 'rsi': 55, 'atr': 2.0, 'trend': 'UP'}
        signal['stop_loss'] = 92.0
        signal['take_profit'] = 100.0
        decision = rm.evaluate(signal, portfolio_high_exposure, two_trades_open)
        assert not decision.approved
        assert 'INSUFFICIENT_CASH' in decision.reason or 'MAX_EXPOSURE_WITH_NEW_TRADE' in decision.reason


# ═══════════════════════════════════════════════════════════════════
# REGLA 5: R:R ratio mínimo (1.5)
# ═══════════════════════════════════════════════════════════════════

class TestRiskRewardRatio:
    """Ratio R:R debe ser ≥ 1.5 para aprobar."""

    def test_low_rr_rejected(self, base_portfolio, bad_rr_signal, no_open_trades):
        rm = _make_risk_manager()
        decision = rm.evaluate(bad_rr_signal, base_portfolio, no_open_trades)
        assert not decision.approved
        assert 'INSUFFICIENT_RR' in decision.reason

    def test_good_rr_approved(self, base_portfolio, btc_buy_signal, no_open_trades):
        """BTC signal: RR = |76665-75000|/|75000-74000| = 1665/1000 = 1.665"""
        rm = _make_risk_manager()
        decision = rm.evaluate(btc_buy_signal, base_portfolio, no_open_trades)
        assert decision.approved

    def test_rr_exactly_at_minimum(self, base_portfolio, no_open_trades):
        rm = _make_risk_manager()
        signal = {
            'asset': 'BTC', 'direction': 'BUY', 'strategy': 'TEST',
            'stop_loss': 74000.0,
            'take_profit': 76500.0,     # RR = 1500/1000 = 1.5 exacto
            'indicators': {'price': 75000.0, 'rsi': 55, 'atr': 500, 'trend': 'UP'},
        }
        decision = rm.evaluate(signal, base_portfolio, no_open_trades)
        assert decision.approved


# ═══════════════════════════════════════════════════════════════════
# REGLA 6: Claude Anomaly Check
# ═══════════════════════════════════════════════════════════════════

class TestClaudeAnomaly:
    """Claude puede bloquear trade si detecta anomalía CRITICAL ≥ 85% conf."""

    def test_critical_anomaly_blocks(self, base_portfolio, btc_buy_signal, no_open_trades):
        rm = _make_risk_manager()
        rm.claude.call.return_value = {
            'anomaly_detected': True,
            'severity': 'CRITICAL',
            'confidence': 90,
            'reasoning': 'Market manipulation detected',
            'flags': ['flash_crash_risk'],
        }
        decision = rm.evaluate(btc_buy_signal, base_portfolio, no_open_trades)
        assert not decision.approved
        assert decision.reason == 'CLAUDE_CRITICAL_ANOMALY'

    def test_high_anomaly_low_confidence_passes(self, base_portfolio, btc_buy_signal, no_open_trades):
        rm = _make_risk_manager()
        rm.claude.call.return_value = {
            'anomaly_detected': True,
            'severity': 'CRITICAL',
            'confidence': 60,  # < 85
            'reasoning': 'Possible anomaly',
            'flags': [],
        }
        decision = rm.evaluate(btc_buy_signal, base_portfolio, no_open_trades)
        assert decision.approved  # Confidence too low

    def test_medium_anomaly_passes(self, base_portfolio, btc_buy_signal, no_open_trades):
        rm = _make_risk_manager()
        rm.claude.call.return_value = {
            'anomaly_detected': True,
            'severity': 'HIGH',  # Not CRITICAL
            'confidence': 95,
            'reasoning': 'Unusual volume',
            'flags': ['volume_spike'],
        }
        decision = rm.evaluate(btc_buy_signal, base_portfolio, no_open_trades)
        assert decision.approved  # Only CRITICAL blocks


# ═══════════════════════════════════════════════════════════════════
# REGLA 3c: Cooldown post stop-loss
# ═══════════════════════════════════════════════════════════════════

class TestSLCooldown:
    """Tras un stop-loss, el activo queda bloqueado por SL_COOLDOWN_MINUTES."""

    def test_cooldown_blocks_reentry(self, base_portfolio, btc_buy_signal, no_open_trades):
        rm = _make_risk_manager()
        rm.register_sl_close('BTC')
        decision = rm.evaluate(btc_buy_signal, base_portfolio, no_open_trades)
        assert not decision.approved
        assert 'SL_COOLDOWN:BTC' in decision.reason

    def test_cooldown_only_affects_same_asset(self, base_portfolio, no_open_trades):
        rm = _make_risk_manager()
        rm.register_sl_close('BTC')  # BTC en cooldown

        # ETH debería poder entrar
        eth_signal = {
            'asset': 'ETH',
            'direction': 'BUY',
            'score': 75,
            'stop_loss': 2240.0,
            'take_profit': 2400.0,
            'indicators': {'price': 2300.0, 'atr': 40.0},
        }
        decision = rm.evaluate(eth_signal, base_portfolio, no_open_trades)
        assert decision.approved

    def test_cooldown_expires(self, base_portfolio, btc_buy_signal, no_open_trades):
        rm = _make_risk_manager()
        # Simulate expired cooldown: ttl returns -2 (key not found)
        rm._redis.ttl.return_value = -2
        decision = rm.evaluate(btc_buy_signal, base_portfolio, no_open_trades)
        assert decision.approved  # Cooldown expirado, puede entrar


# ═══════════════════════════════════════════════════════════════════
# Persistent Drawdown Halt
# ═══════════════════════════════════════════════════════════════════

class TestPersistentHalt:
    """Drawdown halt persiste entre restarts vía check_persistent_halt."""

    def test_persistent_halt_activates_on_high_drawdown(self, base_portfolio):
        rm = _make_risk_manager()
        assert not rm._trading_halted
        portfolio = {**base_portfolio, 'drawdown_pct': 0.12}  # 12%
        rm.check_persistent_halt(portfolio)
        assert rm._trading_halted

    def test_persistent_halt_noop_on_low_drawdown(self, base_portfolio):
        rm = _make_risk_manager()
        portfolio = {**base_portfolio, 'drawdown_pct': 0.05}  # 5%
        rm.check_persistent_halt(portfolio)
        assert not rm._trading_halted

    def test_paper_auto_resume_after_quarantine(self, base_portfolio):
        rm = _make_risk_manager()
        rm.paper_mode = True
        # Use mock-relative time: mock is 2025-01-15 10:00, breach 4h ago = 06:00
        portfolio = {
            **base_portfolio,
            'drawdown_pct': 0.09,
            'historical_max_drawdown': 0.11,
            'halt_triggered': True,
            'last_halt_breach_at': datetime(2025, 1, 15, 6, 0, 0, tzinfo=timezone.utc),
        }
        rm.check_persistent_halt(portfolio)
        assert not rm._trading_halted

    def test_paper_auto_resume_not_allowed_too_early(self, base_portfolio):
        rm = _make_risk_manager()
        rm.paper_mode = True
        # Use mock-relative time: mock is 2025-01-15 10:00, breach 1h ago = 09:00
        portfolio = {
            **base_portfolio,
            'drawdown_pct': 0.09,
            'historical_max_drawdown': 0.11,
            'halt_triggered': True,
            'last_halt_breach_at': datetime(2025, 1, 15, 9, 0, 0, tzinfo=timezone.utc),
        }
        rm.check_persistent_halt(portfolio)
        assert rm._trading_halted


# ═══════════════════════════════════════════════════════════════════
# REGLA 0b: Filtro Horario (Dead Hours)
# ═══════════════════════════════════════════════════════════════════

class TestDeadHours:
    """Bloquear trades durante horas con 0% WR histórico (1-4 UTC)."""

    @pytest.mark.parametrize('hour', [1, 2, 3, 4])
    def test_dead_hour_rejects(self, base_portfolio, btc_buy_signal, no_open_trades, hour):
        rm = _make_risk_manager()
        fake_now = datetime(2025, 1, 15, hour, 30, 0, tzinfo=timezone.utc)
        with patch('risk.risk_manager.datetime') as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.fromtimestamp = datetime.fromtimestamp
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            decision = rm.evaluate(btc_buy_signal, base_portfolio, no_open_trades)
        assert not decision.approved
        assert 'DEAD_HOUR' in decision.reason

    @pytest.mark.parametrize('hour', [0, 5, 8, 12, 18, 23])
    def test_allowed_hour_passes(self, base_portfolio, btc_buy_signal, no_open_trades, hour):
        rm = _make_risk_manager()
        fake_now = datetime(2025, 1, 15, hour, 30, 0, tzinfo=timezone.utc)
        with patch('risk.risk_manager.datetime') as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.fromtimestamp = datetime.fromtimestamp
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            decision = rm.evaluate(btc_buy_signal, base_portfolio, no_open_trades)
        assert decision.approved


# ═══════════════════════════════════════════════════════════════════
# REGLA 3d: Signal Dedup (tras SL)
# ═══════════════════════════════════════════════════════════════════

class TestSignalDedup:
    """Tras SL, bloquear reentrada mismo asset+dirección por SIGNAL_DEDUP_HOURS."""

    def test_dedup_blocks_same_direction(self, base_portfolio, btc_buy_signal, no_open_trades):
        rm = _make_risk_manager()
        rm.register_sl_close('BTC', 'BUY')
        # Simulate: cooldown expired but dedup still active
        def mock_ttl(key):
            if key == 'cooldown:BTC':
                return -2  # expired
            if key == 'dedup:BTC:BUY':
                return 14000  # ~4h remaining
            return -2
        rm._redis.ttl.side_effect = mock_ttl
        decision = rm.evaluate(btc_buy_signal, base_portfolio, no_open_trades)
        assert not decision.approved
        assert 'SIGNAL_DEDUP' in decision.reason

    def test_dedup_allows_opposite_direction(self, base_portfolio, no_open_trades):
        rm = _make_risk_manager()
        rm.register_sl_close('BTC', 'BUY')
        sell_signal = {
            'asset': 'BTC',
            'direction': 'SELL',
            'strategy': 'TREND_MOMENTUM',
            'timeframe': '15m',
            'score': 80,
            'stop_loss': 76000.0,
            'take_profit': 73500.0,
            'indicators': {'price': 75000.0, 'rsi': 45.0, 'atr': 666.0, 'trend': 'DOWN'},
        }
        decision = rm.evaluate(sell_signal, base_portfolio, no_open_trades)
        # Should pass dedup (opposite direction), but may be blocked by cooldown
        # since cooldown blocks ALL directions for the asset.
        # After cooldown passes, only same-direction remains blocked.
        assert 'SIGNAL_DEDUP' not in decision.reason

    def test_dedup_expires_after_window(self, base_portfolio, btc_buy_signal, no_open_trades):
        rm = _make_risk_manager()
        # Simulate all cooldowns/dedups expired
        rm._redis.ttl.return_value = -2
        decision = rm.evaluate(btc_buy_signal, base_portfolio, no_open_trades)
        assert decision.approved

    def test_dedup_without_direction_no_dedup(self, base_portfolio, btc_buy_signal, no_open_trades):
        """register_sl_close sin dirección solo activa cooldown, no dedup."""
        rm = _make_risk_manager()
        rm.register_sl_close('BTC')  # sin dirección
        # Verify setex was called for cooldown but NOT for dedup
        calls = rm._redis.setex.call_args_list
        cooldown_calls = [c for c in calls if str(c).startswith("call('cooldown:")]
        dedup_calls = [c for c in calls if str(c).startswith("call('dedup:")]
        assert len(cooldown_calls) == 1
        assert len(dedup_calls) == 0


# ═══════════════════════════════════════════════════════════════════
# REGLA: Cooldown universal post-cierre (TP incluido)
# ═══════════════════════════════════════════════════════════════════

class TestUniversalCloseCooldown:
    """register_close() debe aplicar cooldown a CUALQUIER motivo de cierre."""

    def test_tp_close_activates_short_cooldown(self, base_portfolio, btc_buy_signal, no_open_trades):
        rm = _make_risk_manager()
        rm.register_close('BTC', 'BUY', reason='TAKE_PROFIT')
        decision = rm.evaluate(btc_buy_signal, base_portfolio, no_open_trades)
        assert not decision.approved
        assert 'COOLDOWN' in decision.reason

    def test_tp_close_does_not_activate_dedup(self):
        rm = _make_risk_manager()
        rm.register_close('BTC', 'BUY', reason='TAKE_PROFIT')
        # Verify no dedup key was set (only cooldown)
        calls = rm._redis.setex.call_args_list
        dedup_calls = [c for c in calls if 'dedup:' in str(c[0][0])]
        assert len(dedup_calls) == 0

    def test_sl_close_activates_dedup(self):
        rm = _make_risk_manager()
        rm.register_close('BTC', 'BUY', reason='STOP_LOSS')
        # Verify dedup key was set
        calls = rm._redis.setex.call_args_list
        dedup_calls = [c for c in calls if 'dedup:BTC:BUY' in str(c[0][0])]
        assert len(dedup_calls) == 1

    def test_trailing_close_short_cooldown_no_dedup(self, base_portfolio, btc_buy_signal, no_open_trades):
        rm = _make_risk_manager()
        rm.register_close('BTC', 'BUY', reason='TRAILING_STOP')
        # Cooldown sí (simulate active)
        rm._redis.ttl.return_value = 200  # 200s remaining
        decision = rm.evaluate(btc_buy_signal, base_portfolio, no_open_trades)
        assert not decision.approved
        # Dedup no (no fue pérdida pura)
        calls = rm._redis.setex.call_args_list
        dedup_calls = [c for c in calls if 'dedup:BTC:BUY' in str(c[0][0])]
        assert len(dedup_calls) == 0

    def test_register_sl_close_backward_compat(self):
        rm = _make_risk_manager()
        rm.register_sl_close('ETH', 'BUY')
        # Verify both cooldown and dedup were set via Redis
        calls = rm._redis.setex.call_args_list
        cooldown_calls = [c for c in calls if 'cooldown:ETH' in str(c[0][0])]
        dedup_calls = [c for c in calls if 'dedup:ETH:BUY' in str(c[0][0])]
        assert len(cooldown_calls) == 1
        assert len(dedup_calls) == 1


# ═══════════════════════════════════════════════════════════════════
# REGLA: Cash validation — no abrir trade sin cash suficiente
# ═══════════════════════════════════════════════════════════════════

class TestCashValidation:
    """Rechazar trade si available_cash < position_value."""

    def test_reject_when_no_cash(self, btc_buy_signal, no_open_trades):
        rm = _make_risk_manager()
        rm._redis.ttl.return_value = -2  # No cooldowns active
        portfolio_no_cash = {
            'total_balance': 10000.0,
            'available_cash': 0.0,
            'exposure_pct': 0.0,
            'drawdown_pct': 0.0,
            'peak_balance': 10000.0,
        }
        decision = rm.evaluate(btc_buy_signal, portfolio_no_cash, no_open_trades)
        assert not decision.approved
        assert 'INSUFFICIENT_CASH' in decision.reason

    def test_reject_when_negative_cash(self, btc_buy_signal, no_open_trades):
        rm = _make_risk_manager()
        rm._redis.ttl.return_value = -2  # No cooldowns active
        portfolio_neg = {
            'total_balance': 10000.0,
            'available_cash': -5000.0,
            'exposure_pct': 0.0,
            'drawdown_pct': 0.0,
            'peak_balance': 10000.0,
        }
        decision = rm.evaluate(btc_buy_signal, portfolio_neg, no_open_trades)
        assert not decision.approved
        assert 'INSUFFICIENT_CASH' in decision.reason

    def test_approve_when_enough_cash(self, base_portfolio, eth_buy_signal, no_open_trades):
        rm = _make_risk_manager()
        rm._redis.ttl.return_value = -2  # No cooldowns active
        decision = rm.evaluate(eth_buy_signal, base_portfolio, no_open_trades)
        assert decision.approved


# ═══════════════════════════════════════════════════════════════════
# REGLA: Notional cap — limitar nocional al MAX_NOTIONAL_PCT del balance
# ═══════════════════════════════════════════════════════════════════

class TestNotionalCap:
    """position_value nunca debe superar MAX_NOTIONAL_PCT * balance."""

    def test_capped_position_size(self, no_open_trades):
        """Con balance de $1k y BTC a $75k, position_value = ~$100 (1% riesgo).
        Si fuese un activo barato donde raw sizing da más de 50% del balance, se recorta."""
        rm = _make_risk_manager()
        # Crear señal con SL muy ajustado (riesgo por unidad mínimo → sizing enorme)
        tight_sl_signal = {
            'asset': 'CHEAP',
            'direction': 'BUY',
            'strategy': 'TREND_MOMENTUM',
            'timeframe': '15m',
            'score': 80,
            'stop_loss': 9.99,       # solo $0.01 de riesgo por unidad
            'take_profit': 10.05,
            'indicators': {'price': 10.0, 'rsi': 55.0, 'atr': 0.05, 'trend': 'UP'},
        }
        portfolio = {
            'total_balance': 1000.0,
            'available_cash': 1000.0,
            'exposure_pct': 0.0,
            'drawdown_pct': 0.0,
            'peak_balance': 1000.0,
        }
        decision = rm.evaluate(tight_sl_signal, portfolio, no_open_trades)
        if decision.approved:
            max_notional = 1000.0 * 0.50
            assert decision.position_size * 10.0 <= max_notional + 0.01
