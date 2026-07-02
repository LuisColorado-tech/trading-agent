"""
test_grid_costs.py — Viabilidad de grids neta de costos.

Verifica el hallazgo central de docs/FEASIBILITY_STUDY.md §3b sobre el
código real (no sobre una réplica de la fórmula):
  - ETH/BTC (perfil original): build_grid no produce niveles operables
    dentro de su rango permitido — el gate de RR neto los rechaza todos.
  - LINK/BTC (retuneado 8→4 niveles, min_range 3%): sí produce niveles.
  - GridStableStrategy._net_rr calcula lo mismo que el cost model.
"""
import sys
import math
from types import SimpleNamespace

import pytest

sys.path.insert(0, '/opt/trading')

from core.cost_model import round_trip_cost_pct, MIN_NET_RR_RATIO
from core.grid_stable_profiles import GRID_STABLE_PROFILES


# ── Helpers ──────────────────────────────────────────────────────

def _range_df(low: float, high: float, n: int = 60):
    """DataFrame OHLCV sintético oscilando dentro de [low, high]."""
    pd = pytest.importorskip('pandas')
    mid = (low + high) / 2
    amp = (high - low) / 2
    rows = []
    for i in range(n):
        c = mid + amp * 0.9 * math.sin(i / 3)
        rows.append({
            'open': c, 'close': c,
            'high': min(c + amp * 0.1, high),
            'low': max(c - amp * 0.1, low),
            'volume': 100.0,
        })
    # Forzar que los extremos del rango existan en el lookback (no en las últimas 3)
    rows[5]['high'] = high
    rows[10]['low'] = low
    return pd.DataFrame(rows)


def _build(pair: str, low: float, high: float):
    from strategies.grid_stable import GridStableStrategy
    profile = GRID_STABLE_PROFILES[pair]
    strategy = GridStableStrategy(profile)
    df = _range_df(low, high)
    ind = SimpleNamespace(close=(low + high) / 2)
    return strategy.build_grid(df, ind)


# ═══════════════════════════════════════════════════════════════════
# Perfiles: la matemática de viabilidad (pura, sin pandas)
# ═══════════════════════════════════════════════════════════════════

class TestProfileViability:

    @staticmethod
    def _net_rr_at(profile, range_pct: float) -> float:
        spacing_pct = range_pct / (profile.grid_levels + 1)
        gain = spacing_pct * profile.tp_ratio
        risk = spacing_pct * profile.sl_ratio
        cost = round_trip_cost_pct(profile.exchange)
        return (gain - cost) / risk

    def test_link_btc_viable_across_range(self):
        """LINK/BTC retuneado debe cubrir costos en TODO su rango operable."""
        p = GRID_STABLE_PROFILES['LINK/BTC']
        assert self._net_rr_at(p, p.min_range_pct) >= MIN_NET_RR_RATIO
        assert self._net_rr_at(p, p.max_range_pct) >= MIN_NET_RR_RATIO

    def test_eth_btc_not_viable_documents_pause(self):
        """ETH/BTC NO es viable ni en el mejor caso de su rango — si este
        test empieza a fallar es que alguien retuneó el perfil: revisar que
        el cambio venga con la matemática, no borrar el test."""
        p = GRID_STABLE_PROFILES['ETH/BTC']
        assert self._net_rr_at(p, p.max_range_pct) < MIN_NET_RR_RATIO

    def test_all_profiles_use_known_exchange(self):
        for p in GRID_STABLE_PROFILES.values():
            round_trip_cost_pct(p.exchange)  # KeyError si no está en FEE_SCHEDULES


# ═══════════════════════════════════════════════════════════════════
# Estrategia real: build_grid con el gate activo (requiere pandas)
# ═══════════════════════════════════════════════════════════════════

class TestBuildGridGate:

    def test_net_rr_matches_cost_model(self):
        from strategies.grid_stable import GridStableStrategy
        cost = round_trip_cost_pct('kraken')
        # BUY: entry 100, tp 102 (gain 2%), sl 99 (risk 1%)
        net = GridStableStrategy._net_rr(100.0, 102.0, 99.0, cost)
        assert net == pytest.approx((0.02 - cost) / 0.01)

    def test_eth_btc_produces_no_levels(self):
        """Rango 2% (dentro del permitido 0.5%-3%): todos los niveles mueren
        al gate de costos → build_grid devuelve None."""
        config = _build('ETH/BTC', low=0.0300, high=0.0306)
        assert config is None

    def test_link_btc_produces_levels(self):
        """Rango 4% (dentro del retuneado 3%-5%): deben salir niveles con
        RR bruto ≥ min_rr Y RR neto ≥ MIN_NET_RR_RATIO."""
        config = _build('LINK/BTC', low=0.00250, high=0.00260)
        assert config is not None
        assert len(config.levels) > 0
        p = GRID_STABLE_PROFILES['LINK/BTC']
        cost = round_trip_cost_pct(p.exchange)
        from strategies.grid_stable import GridStableStrategy
        for level in config.levels:
            assert level.rr >= p.min_rr
            net = GridStableStrategy._net_rr(level.price, level.tp, level.sl, cost)
            assert net >= MIN_NET_RR_RATIO


# ═══════════════════════════════════════════════════════════════════
# GRID_BOT: mismo gate en calculate_grid (GridAgent inserta directo a
# DB sin RiskManager — este es su único gate de costos)
# ═══════════════════════════════════════════════════════════════════

class TestGridBotGate:

    def _calc(self, low: float, high: float):
        from strategies.grid_bot import GridBotStrategy
        df = _range_df(low, high)
        ind = SimpleNamespace(close=(low + high) / 2, asset='BTC')
        return GridBotStrategy().calculate_grid(ind, df, exchange='kraken')

    def test_narrow_range_produces_no_levels(self):
        """Rango 1% con 6 niveles default: spacing ~0.14%, ganancia por nivel
        ~0.21% < costo 0.68% → todos los niveles mueren al gate."""
        config = self._calc(low=100.0, high=101.0)
        assert config is None

    def test_wide_range_produces_viable_levels(self):
        """Rango 9% (tercio superior del permitido): spacing ~1.3%,
        ganancia ~1.9% > costo → niveles sobreviven, todos netos-viables."""
        config = self._calc(low=100.0, high=109.0)
        assert config is not None
        cost = round_trip_cost_pct('kraken')
        for level in config.levels:
            gain_pct = abs(level.tp - level.price) / level.price
            risk_pct = abs(level.sl - level.price) / level.price
            assert (gain_pct - cost) / risk_pct >= MIN_NET_RR_RATIO
