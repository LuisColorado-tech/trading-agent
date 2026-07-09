"""
test_cost_model.py — Tests unitarios del modelo de costos (fee + slippage).

Verifica:
  - round_trip_cost_pct por exchange y tipo de orden (maker/taker)
  - net_pnl resta el costo correcto y puede volver negativo un trade ganador
  - min_rr_for_breakeven coincide con el costo round-trip
  - exchange desconocido lanza KeyError (fail-loud, no fail-silent)
  - El caso GRID_STABLE que motivó todo esto: ganancia bruta de nivel
    menor que el costo → neto negativo
"""
import sys
import pytest

sys.path.insert(0, '/opt/trading')

from core.cost_model import (
    FEE_SCHEDULES,
    MIN_NET_RR_RATIO,
    get_fee_schedule,
    min_rr_for_breakeven,
    net_pnl,
    round_trip_cost_pct,
    trade_cost_usd,
)


# ═══════════════════════════════════════════════════════════════════
# round_trip_cost_pct
# ═══════════════════════════════════════════════════════════════════

class TestRoundTripCost:

    def test_kraken_taker_both_legs(self):
        fs = FEE_SCHEDULES['kraken']
        expected = 2 * fs.taker_pct + 2 * fs.slippage_pct
        assert round_trip_cost_pct('kraken') == pytest.approx(expected)

    def test_maker_both_legs_is_cheaper(self):
        taker = round_trip_cost_pct('kraken')
        maker = round_trip_cost_pct('kraken', 'maker', 'maker')
        assert maker < taker

    def test_mixed_order_types(self):
        fs = FEE_SCHEDULES['kraken']
        cost = round_trip_cost_pct('kraken', entry_order_type='maker',
                                   exit_order_type='taker')
        expected = fs.maker_pct + fs.taker_pct + 2 * fs.slippage_pct
        assert cost == pytest.approx(expected)

    def test_exchange_case_insensitive(self):
        assert round_trip_cost_pct('KRAKEN') == round_trip_cost_pct('kraken')

    def test_unknown_exchange_raises(self):
        with pytest.raises(KeyError):
            get_fee_schedule('binance_futures_inexistente')

    def test_all_schedules_positive(self):
        for name in FEE_SCHEDULES:
            assert round_trip_cost_pct(name) > 0


# ═══════════════════════════════════════════════════════════════════
# net_pnl / trade_cost_usd
# ═══════════════════════════════════════════════════════════════════

class TestNetPnl:

    def test_cost_proportional_to_notional(self):
        c1 = trade_cost_usd('kraken', 100.0, 100.0)
        c2 = trade_cost_usd('kraken', 200.0, 200.0)
        assert c2 == pytest.approx(2 * c1)

    def test_net_pnl_subtracts_cost(self):
        # BUY BTC: entry 75000, exit 76500, qty 0.1 → gross +150
        gross = (76500.0 - 75000.0) * 0.1
        net, cost = net_pnl(gross, 75000.0, 76500.0, 0.1, 'kraken')
        assert cost > 0
        assert net == pytest.approx(gross - cost)

    def test_losing_trade_loses_more_net(self):
        # SL: entry 75000, exit 74000, qty 0.1 → gross -100
        gross = (74000.0 - 75000.0) * 0.1
        net, cost = net_pnl(gross, 75000.0, 74000.0, 0.1, 'kraken')
        assert net < gross

    def test_grid_stable_level_dies_to_fees(self):
        """El caso que quemó capital: nivel de grid con ganancia 0.15%
        sobre notional ~$150 en Kraken taker — bruto positivo, neto negativo."""
        entry, exit_, qty = 100.0, 100.15, 1.5
        gross = (exit_ - entry) * qty
        net, cost = net_pnl(gross, entry, exit_, qty, 'kraken')
        assert gross > 0
        assert net < 0

    def test_trend_momentum_survives_fees(self):
        """TP de TREND_MOMENTUM (2.5×ATR, ATR~1.5% del precio) debe seguir
        siendo positivo neto — es la estrategia que el estudio declaró viable."""
        entry = 75000.0
        exit_ = entry * 1.0375   # +3.75% (2.5 × ATR 1.5%)
        qty = 0.01
        gross = (exit_ - entry) * qty
        net, _ = net_pnl(gross, entry, exit_, qty, 'kraken')
        assert net > 0

    def test_maker_execution_reduces_cost(self):
        gross = 10.0
        net_taker, cost_taker = net_pnl(gross, 100.0, 101.0, 10.0, 'kraken')
        net_maker, cost_maker = net_pnl(gross, 100.0, 101.0, 10.0, 'kraken',
                                        entry_order_type='maker',
                                        exit_order_type='maker')
        assert cost_maker < cost_taker
        assert net_maker > net_taker


# ═══════════════════════════════════════════════════════════════════
# min_rr_for_breakeven / constantes
# ═══════════════════════════════════════════════════════════════════

class TestBreakeven:

    def test_matches_round_trip_cost(self):
        for name in FEE_SCHEDULES:
            assert min_rr_for_breakeven(name) == pytest.approx(round_trip_cost_pct(name))

    def test_min_net_rr_ratio_sane(self):
        # El piso compartido por RiskManager y GridStable debe existir y ser ≥ 0.5
        assert MIN_NET_RR_RATIO >= 0.5
