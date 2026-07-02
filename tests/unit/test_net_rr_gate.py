"""
test_net_rr_gate.py — Tests del gate 5b: R:R neto de costos reales.

Verifica que RiskManager rechaza trades cuyo RR nominal sobrevive (≥1.5)
pero cuyo RR neto de fee+slippage cae bajo MIN_NET_RR_RATIO — el patrón
exacto que quemó capital en los grids (docs/FEASIBILITY_STUDY.md).
"""
import sys
import pytest
from unittest.mock import patch
from datetime import datetime, timezone

sys.path.insert(0, '/opt/trading')

from core.cost_model import round_trip_cost_pct


# ── Autouse: hora segura (mismo patrón que test_risk_manager) ──────

@pytest.fixture(autouse=True)
def _safe_hour():
    safe_now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    with patch('risk.risk_manager.datetime') as mock_dt:
        mock_dt.now.return_value = safe_now
        mock_dt.fromtimestamp = datetime.fromtimestamp
        mock_dt.fromisoformat = datetime.fromisoformat
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        yield mock_dt


def _make_risk_manager():
    with patch('risk.risk_manager.ClaudeBridge') as MockClaude, \
         patch('risk.risk_manager.redis.Redis') as MockRedis:
        mock_claude = MockClaude.return_value
        mock_claude.call.return_value = {
            'anomaly_detected': False, 'severity': 'LOW',
            'confidence': 10, 'reasoning': 'ok', 'flags': [],
        }
        mock_redis = MockRedis.return_value
        mock_redis.ttl.return_value = -2
        from risk.risk_manager import RiskManager
        rm = RiskManager()
        rm.claude = mock_claude
    return rm


def _tight_grid_signal(entry=100_000.0, risk_pct=0.004, gross_rr=1.5):
    """Señal estilo grid: RR bruto exactamente en el mínimo (1.5) pero con
    distancias tan cortas que el fee de Kraken se come la ganancia."""
    risk = entry * risk_pct
    return {
        'asset': 'BTC',
        'direction': 'BUY',
        'strategy': 'GRID_BOT',
        'timeframe': '15m',
        'score': 80,
        'stop_loss': entry - risk,
        'take_profit': entry + risk * gross_rr,
        'indicators': {'price': entry, 'rsi': 50.0, 'atr': risk / 1.5, 'trend': 'UP'},
    }


class TestNetRRGate:

    def test_tight_signal_passes_gross_but_fails_net(self, base_portfolio, no_open_trades):
        """Riesgo 0.4%, ganancia 0.6% → RR bruto 1.5 (pasa gate 5),
        pero neto de ~0.68% de costo → RR neto negativo (rechaza 5b)."""
        rm = _make_risk_manager()
        signal = _tight_grid_signal(risk_pct=0.004)
        decision = rm.evaluate(signal, base_portfolio, no_open_trades)
        assert not decision.approved
        assert 'INSUFFICIENT_NET_RR' in decision.reason

    def test_wide_signal_passes_both_gates(self, base_portfolio, btc_buy_signal, no_open_trades):
        """La señal fixture estándar (ATR real, distancias amplias) debe
        seguir aprobándose — el gate no puede matar TREND_MOMENTUM."""
        rm = _make_risk_manager()
        decision = rm.evaluate(btc_buy_signal, base_portfolio, no_open_trades)
        assert decision.approved, decision.reason

    def test_rejection_reason_includes_cost(self, base_portfolio, no_open_trades):
        """El motivo de rechazo debe incluir el costo usado — es lo que el
        protocolo de diagnóstico (AGENTS.md paso 3.4) va a leer en los logs."""
        rm = _make_risk_manager()
        decision = rm.evaluate(_tight_grid_signal(), base_portfolio, no_open_trades)
        assert 'cost=' in decision.reason

    def test_breakeven_boundary(self, base_portfolio, no_open_trades):
        """Alrededor del punto de equilibrio, con riesgo 1% (< 2× costo) para
        que ambos casos pasen el gate bruto (RR ≥ 1.5) y sea el gate NETO el
        que decida: ganancia = riesgo + costo → aprueba; un poco menos → rechaza."""
        rm = _make_risk_manager()
        entry = 100_000.0
        cost_pct = round_trip_cost_pct('kraken')
        risk_pct = 0.01

        gain_pct_ok = risk_pct + cost_pct + 1e-5   # net RR apenas sobre 1.0, gross ~1.68
        signal = _tight_grid_signal(entry=entry, risk_pct=risk_pct,
                                    gross_rr=gain_pct_ok / risk_pct)
        decision = rm.evaluate(signal, base_portfolio, no_open_trades)
        assert decision.approved, decision.reason

        gain_pct_bad = risk_pct + cost_pct - 0.001  # net RR 0.9, gross ~1.58 (pasa gate bruto)
        signal = _tight_grid_signal(entry=entry, risk_pct=risk_pct,
                                    gross_rr=gain_pct_bad / risk_pct)
        decision = rm.evaluate(signal, base_portfolio, no_open_trades)
        assert not decision.approved
        assert 'INSUFFICIENT_NET_RR' in decision.reason
