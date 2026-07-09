"""
test_sizing_units.py — Fix de unidades en el sizing de GRID_STABLE (Fase 2).

Bug corregido: pares BTC-quoted (ETH/BTC, LINK/BTC) calculaban
size = riesgo_USD / distancia_precio_BTC sin convertir moneda, produciendo
posiciones de millones de tokens (visto en vivo: SELL 7.8M LINK en cuenta
de $500). Ver docs/FEASIBILITY_STUDY.md §6c.

Requiere el venv completo (pandas, ccxt, sqlalchemy, redis) — correr en la VPS:
  venv/bin/python3 -m pytest tests/unit/test_sizing_units.py -v

Nota: NO hay un guard de "distancia mínima de SL vs costo" en open_trade() —
se consideró y se descartó durante esta misma sesión de fix. Una comparación
cruda sl_dist_pct < cost_pct no es equivalente al net_rr real (gain_pct -
cost_pct) / risk_pct y habría rechazado niveles de LINK/BTC retuneado que el
gate correcto en strategies/grid_stable.py::build_grid ya aprueba (ver ese
archivo — es la única vía de llamada a open_trade, vía run_cycle).

grid_stable_agent.py es un módulo "script" con efectos secundarios a nivel de
import (abre config/exchange_config.yaml, crea engine de DB, cliente Redis,
MarketFeed) — se mockean todos antes de importar, mismo patrón que
tests/unit/test_trade_monitor.py::_make_monitor().
"""
import sys
import os
import importlib
import yaml
import pytest
from unittest.mock import patch, mock_open, MagicMock

sys.path.insert(0, '/opt/trading')

_FAKE_CFG = yaml.dump({
    'grid_stable': {
        'pairs': {'ETH/BTC': {'enabled': True}, 'LINK/BTC': {'enabled': True}},
        'cycle_interval_seconds': 120,
        'initial_balance': 500.0,
        'risk': {'max_concurrent_total': 5, 'cooldown_minutes': 10},
    }
})


def _import_agent():
    """Importa (o recarga) agents.grid_stable_agent con todo el I/O mockeado."""
    with patch('builtins.open', mock_open(read_data=_FAKE_CFG)), \
         patch('sqlalchemy.create_engine'), \
         patch('redis.Redis'), \
         patch('data.market_feed.MarketFeed'), \
         patch.dict(os.environ, {
             'POSTGRES_USER': 'x', 'POSTGRES_PASSWORD': 'x',
             'POSTGRES_DB': 'x', 'POSTGRES_HOST': 'localhost',
         }):
        if 'agents.grid_stable_agent' in sys.modules:
            importlib.reload(sys.modules['agents.grid_stable_agent'])
        else:
            importlib.import_module('agents.grid_stable_agent')
    return sys.modules['agents.grid_stable_agent']


def _mock_btc_price(gsa, btc_usdt_price: float):
    """Mockea el ticker BTC/USDT que usa quote_to_usd_rate() para pares BTC-quoted."""
    mock_exchange = MagicMock()
    mock_exchange.fetch_ticker.return_value = {'close': btc_usdt_price}
    gsa._exchange_stable = mock_exchange
    gsa._quote_rate_cache.clear()


class _Level:
    def __init__(self, price, sl, tp, direction='SELL', level_idx=1):
        self.price = price
        self.sl = sl
        self.tp = tp
        self.direction = direction
        self.level_idx = level_idx


class _Profile:
    def __init__(self, risk_fraction=0.20, grid_levels=10):
        self.risk_fraction = risk_fraction
        self.grid_levels = grid_levels


# ═══════════════════════════════════════════════════════════════════
# quote_to_usd_rate
# ═══════════════════════════════════════════════════════════════════

class TestQuoteToUsdRate:

    def test_usdt_pair_is_one(self):
        gsa = _import_agent()
        assert gsa.quote_to_usd_rate('DAI/USDT') == 1.0
        assert gsa.quote_to_usd_rate('USDC/USDT') == 1.0

    def test_btc_pair_uses_live_price(self):
        gsa = _import_agent()
        _mock_btc_price(gsa, 65000.0)
        assert gsa.quote_to_usd_rate('ETH/BTC') == pytest.approx(65000.0)
        assert gsa.quote_to_usd_rate('LINK/BTC') == pytest.approx(65000.0)

    def test_caches_within_ttl(self):
        gsa = _import_agent()
        _mock_btc_price(gsa, 65000.0)
        gsa.quote_to_usd_rate('ETH/BTC')
        gsa._exchange_stable.fetch_ticker.return_value = {'close': 999999.0}
        # Segunda llamada dentro del TTL: debe devolver el valor cacheado, no 999999
        assert gsa.quote_to_usd_rate('ETH/BTC') == pytest.approx(65000.0)


# ═══════════════════════════════════════════════════════════════════
# open_trade: notional cap en USD, sea cual sea la moneda de cotización
# ═══════════════════════════════════════════════════════════════════

class TestOpenTradeSizing:

    @patch('agents.grid_stable_agent.engine')
    @patch('agents.grid_stable_agent.redis_client')
    def test_eth_btc_notional_capped_at_50pct_balance(self, mock_redis, mock_engine):
        """Balance $500, riesgo 0.1% del perfil: notional en USD nunca > 50% ($250),
        incluso si el bug de unidades reaparece — este test lo habría detectado
        (con el bug viejo, notional real era ~$300,000+)."""
        gsa = _import_agent()
        _mock_btc_price(gsa, 65000.0)
        gsa.INITIAL_BALANCE = 500.0

        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__.return_value = mock_conn

        # Nivel ETH/BTC realista: precio 0.027 BTC/ETH, SL a 0.4% de distancia
        level = _Level(price=0.027, sl=0.027 * 1.004, tp=0.027 * 0.988)
        profile = _Profile(risk_fraction=0.20)

        gsa.open_trade('ETH/BTC', level, profile, price=0.027)

        insert_call = mock_conn.execute.call_args
        params = insert_call.args[1]
        size = params['size']
        notional_usd = size * level.price * 65000.0

        assert notional_usd <= 500.0 * 0.50 + 1e-6

    @patch('agents.grid_stable_agent.engine')
    @patch('agents.grid_stable_agent.redis_client')
    def test_stable_pair_notional_capped(self, mock_redis, mock_engine):
        """DAI/USDT: quote_rate=1.0, pero igual debe respetar el cap de 50%."""
        gsa = _import_agent()
        gsa.INITIAL_BALANCE = 500.0

        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__.return_value = mock_conn

        # SL muy ceñido (como el perfil real de DAI/USDT) para forzar un size grande
        level = _Level(price=1.0014, sl=1.0014 * 1.0001, tp=1.0014 * 0.9998)
        profile = _Profile(risk_fraction=0.10)

        gsa.open_trade('DAI/USDT', level, profile, price=1.0014)

        insert_call = mock_conn.execute.call_args
        params = insert_call.args[1]
        notional_usd = params['size'] * level.price

        assert notional_usd <= 500.0 * 0.50 + 1e-6

    @patch('agents.grid_stable_agent.engine')
    @patch('agents.grid_stable_agent.redis_client')
    def test_zero_sl_distance_rejected(self, mock_redis, mock_engine):
        gsa = _import_agent()
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__.return_value = mock_conn

        level = _Level(price=0.027, sl=0.027, tp=0.0265)
        gsa.open_trade('ETH/BTC', level, _Profile(), price=0.027)

        mock_conn.execute.assert_not_called()


# ═══════════════════════════════════════════════════════════════════
# close_trade: PnL de pares BTC-quoted convertido a USD
# ═══════════════════════════════════════════════════════════════════

class TestCloseTradePnlConversion:

    @patch('agents.grid_stable_agent.engine')
    @patch('agents.grid_stable_agent.redis_client')
    def test_eth_btc_pnl_converted_to_usd(self, mock_redis, mock_engine):
        """Trade ganador ETH/BTC: pnl_gross llega en BTC (~0.0001 BTC), debe
        quedar persistido en USD (magnitud ~riesgo de la cuenta, no ~riesgo×100k
        ni una fracción de centavo por el error de escala BTC vs USD)."""
        gsa = _import_agent()
        _mock_btc_price(gsa, 65000.0)

        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__.return_value = mock_conn

        trade = {
            'id': 'test-1', 'asset': 'ETH/BTC', 'entry_price': 0.027,
            'position_size': 10.0,
        }
        pnl_gross_btc = 0.0001   # 10 ETH * (0.02710 - 0.02700) = 0.0001 BTC

        gsa.close_trade(trade, exit_price=0.02710, reason='TAKE_PROFIT',
                        pnl_gross_quote=pnl_gross_btc)

        update_call = mock_conn.execute.call_args
        params = update_call.args[1]

        expected_gross_usd = pnl_gross_btc * 65000.0  # = $6.50
        assert params['pnl_gross'] == pytest.approx(expected_gross_usd, rel=1e-6)
        # Neto debe ser positivo pero menor que el bruto (fee restado)
        assert 0 < params['pnl'] < params['pnl_gross']
        # Sanity de magnitud: ni 100,000x más chico (bug viejo) ni 100,000x más grande
        assert 0.5 < params['pnl'] < 20.0

    @patch('agents.grid_stable_agent.engine')
    @patch('agents.grid_stable_agent.redis_client')
    def test_stable_pair_pnl_unchanged_by_conversion(self, mock_redis, mock_engine):
        """DAI/USDT: quote_rate=1.0, así que el PnL en USD debe coincidir con
        el bruto pasado (antes de restar fee) — no hay conversión real que aplicar."""
        gsa = _import_agent()

        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__.return_value = mock_conn

        trade = {'id': 'test-2', 'asset': 'DAI/USDT', 'entry_price': 1.0014,
                 'position_size': 100.0}
        gsa.close_trade(trade, exit_price=1.0013, reason='TAKE_PROFIT',
                        pnl_gross_quote=0.94)

        params = mock_conn.execute.call_args.args[1]
        assert params['pnl_gross'] == pytest.approx(0.94)
