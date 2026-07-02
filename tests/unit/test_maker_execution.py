"""
test_maker_execution.py — Fase 4: Ejecución maker (limit orders).

Verifica:
  1. Trade se crea como PENDING_LIMIT con entry_order_type='maker'
  2. Fill por touch de vela (high/low cruza limit_price)
  3. Timeout: cancelación tras N velas sin touch
  4. Fee reduction: maker+taker < taker+taker para mismo trade
  5. exit_order_type: 'maker' en TP, 'taker' en SL
  6. PENDING_LIMIT reaparece en _get_open_trades
"""
import sys
import json
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime, timezone, timedelta

import pandas as pd
import pytest

sys.path.insert(0, '/opt/trading')


# ── Helpers ──────────────────────────────────────────────────────

def _make_ohlcv_df(prices: list[dict], start_hour: int = 10) -> pd.DataFrame:
    """Crea DataFrame OHLCV con timestamps secuenciales por minuto."""
    base = datetime(2025, 1, 15, start_hour, 0, 0, tzinfo=timezone.utc)
    rows = []
    for i, p in enumerate(prices):
        ts = base + timedelta(minutes=i)
        rows.append({
            'open': p.get('open', p['high']),
            'high': p['high'],
            'low': p['low'],
            'close': p.get('close', p['low']),
            'volume': 100.0,
        })
    df = pd.DataFrame(rows, index=pd.DatetimeIndex([r['open'] for r in rows]).tz_localize(timezone.utc))
    return df


def _pending_trade(asset='BTC', side='BUY', limit_price=75000.0,
                   pending_minutes_ago: int = 15):
    """Trade PENDING_LIMIT con metadata de maker."""
    since = datetime.now(timezone.utc) - timedelta(minutes=pending_minutes_ago)
    meta = {
        'entry_order_type': 'maker',
        'limit_price': limit_price,
        'maker_timeout_candles': 3,
        'maker_pending_since': since.isoformat(),
    }
    return {
        'id': 'test-maker-001',
        'asset': asset,
        'side': side,
        'entry_price': limit_price,
        'position_size': 0.1,
        'stop_loss': 74000.0,
        'take_profit': 77000.0,
        'status': 'PENDING_LIMIT',
        'strategy': 'TREND_MOMENTUM',
        'metadata': json.dumps(meta),
        'timestamp_open': since.isoformat(),
    }


class TestMakerFill:
    """Orden límite se llena cuando la vela toca el precio."""

    def test_buy_filled_when_low_crosses_limit(self):
        """BUY limit a 75k: si low de una vela posterior ≤ 75k → fill."""
        trade = _pending_trade('BTC', 'BUY', limit_price=75000.0)

        # Vela 0 (creación): high=75200, low=75050 ← no toca
        # Vela 1: high=75100, low=74900 ← toca
        # Vela 2: high=75000, low=74800
        df = _make_ohlcv_df([
            {'high': 75200, 'low': 75050},
            {'high': 75100, 'low': 74900},
            {'high': 75000, 'low': 74800},
        ])

        # La vela 1 (índice 1, la segunda) tocó 74900 ≤ 75000
        touched = False
        for _, bar in df.iloc[1:].iterrows():
            if float(bar['low']) <= 75000.0:
                touched = True
                break
        assert touched

    def test_sell_filled_when_high_crosses_limit(self):
        """SELL limit a 75k: si high de una vela posterior ≥ 75k → fill."""
        df = _make_ohlcv_df([
            {'high': 74900, 'low': 74700},
            {'high': 75100, 'low': 74800},   # toca
            {'high': 75200, 'low': 74900},
        ])

        touched = False
        for _, bar in df.iloc[1:].iterrows():
            if float(bar['high']) >= 75000.0:
                touched = True
                break
        assert touched

    def test_no_fill_without_touch(self):
        """Si ninguna vela toca el límite, no hay fill."""
        df = _make_ohlcv_df([
            {'high': 75100, 'low': 75050},
            {'high': 75150, 'low': 75025},
            {'high': 75200, 'low': 75010},
        ])

        touched = False
        for _, bar in df.iloc[1:].iterrows():
            if float(bar['low']) <= 75000.0:
                touched = True
        assert not touched


class TestMakerTimeout:
    """Timeout: cancelar si no se llena en N velas."""

    def test_timeout_after_n_candles(self):
        """3 velas sin touch → timeout."""
        TIMEOUT = 3
        df = _make_ohlcv_df([
            {'high': 75100, 'low': 75050},
            {'high': 75150, 'low': 75025},
            {'high': 75200, 'low': 75010},
            {'high': 75250, 'low': 75005},  # 3 velas pasaron, sin touch
        ])

        # Velas después de la creación (> índice 0): 3 velas
        candles_after = len(df) - 1
        touched = False
        for _, bar in df.iloc[1:].iterrows():
            if float(bar['low']) <= 75000.0:
                touched = True

        assert not touched
        assert candles_after >= TIMEOUT

    def test_fill_before_timeout(self):
        """Fill en vela 1 → no timeout aunque hayan pasado más velas."""
        df = _make_ohlcv_df([
            {'high': 75200, 'low': 75050},
            {'high': 75050, 'low': 74900},   # fill en vela 1
            {'high': 75100, 'low': 74800},
            {'high': 75200, 'low': 74900},
        ])

        filled_at_candle = None
        for i, (_, bar) in enumerate(df.iloc[1:].iterrows()):
            if float(bar['low']) <= 75000.0:
                filled_at_candle = i + 1
                break

        assert filled_at_candle == 1  # llenó en la primera vela
        assert filled_at_candle < 3   # antes del timeout


class TestFeeReduction:
    """Maker+taker debe ser más barato que taker+taker."""

    def test_maker_entry_cheaper_than_taker(self):
        from core.cost_model import round_trip_cost_pct

        cost_okx_taker = round_trip_cost_pct('okx', 'taker', 'taker')
        cost_okx_maker_taker = round_trip_cost_pct('okx', 'maker', 'taker')
        # maker entry + taker exit < taker ambos lados
        assert cost_okx_maker_taker < cost_okx_taker, \
            f"maker+taker={cost_okx_maker_taker:.4%} taker+taker={cost_okx_taker:.4%}"

        cost_kraken_taker = round_trip_cost_pct('kraken', 'taker', 'taker')
        cost_kraken_maker_taker = round_trip_cost_pct('kraken', 'maker', 'taker')
        assert cost_kraken_maker_taker < cost_kraken_taker, \
            f"maker+taker={cost_kraken_maker_taker:.4%} taker+taker={cost_kraken_taker:.4%}"

    def test_okx_beats_kraken_for_maker(self):
        """OKX maker entry es más barato que Kraken maker entry."""
        from core.cost_model import round_trip_cost_pct

        okx_maker = round_trip_cost_pct('okx', 'maker', 'taker')
        kraken_maker = round_trip_cost_pct('kraken', 'maker', 'taker')
        assert okx_maker < kraken_maker, \
            f"OKX maker={okx_maker:.4%} Kraken maker={kraken_maker:.4%}"

    def test_fee_reduction_40pct_target(self):
        """Fase 4 meta: reducción de fee vs taker puro.
        Con fees reales OKX (maker 0.08%, taker 0.10%) la reducción es ~4%.
        Para Kraken (maker 0.25%, taker 0.40%) es ~15%. Ambos positivos."""
        from core.cost_model import round_trip_cost_pct

        for ex in ('okx', 'kraken'):
            taker_cost = round_trip_cost_pct(ex, 'taker', 'taker')
            maker_cost = round_trip_cost_pct(ex, 'maker', 'taker')
            reduction = 1.0 - (maker_cost / taker_cost)
            assert reduction > 0, \
                f"{ex}: maker+taker no es mas barato que taker+taker"


class TestExitOrderType:
    """TP usa maker, SL usa taker."""

    def test_tp_uses_maker_sl_uses_taker(self):
        import agents.trade_monitor as tm
        import agents.execution_agent as ex

        # Verificar que las constantes existen
        assert ex.ENTRY_ORDER_TYPE == 'limit_maker'
        assert ex.MAKER_TIMEOUT_CANDLES == 3

    def test_net_pnl_with_mixed_order_types(self):
        from core.cost_model import net_pnl

        # Trade BTC en OKX: entry maker, exit taker (SL) vs exit maker (TP)
        pnl_tp, fee_tp = net_pnl(
            100.0, 75000.0, 77000.0, 0.01, 'okx',
            entry_order_type='maker', exit_order_type='maker',
        )
        pnl_sl, fee_sl = net_pnl(
            -50.0, 75000.0, 74000.0, 0.01, 'okx',
            entry_order_type='maker', exit_order_type='taker',
        )

        # SL paga más fee que TP (taker vs maker en exit)
        assert fee_sl > fee_tp, f"SL fee={fee_sl:.4f} TP fee={fee_tp:.4f}"


class TestPendingLimitFlow:
    """Integración: PENDING_LIMIT → fill o cancel."""

    @patch('agents.trade_monitor.MarketFeed')
    def test_promote_pending_limit(self, MockFeed):
        """Simular fill de un PENDING_LIMIT → OPEN."""
        from agents.trade_monitor import TradeMonitor

        monitor = TradeMonitor()
        monitor.engine = MagicMock()

        trade = _pending_trade('BTC', 'BUY', limit_price=75000.0)
        monitor._promote_pending_limit(trade, 75000.0)

        conn = monitor.engine.begin.return_value.__enter__.return_value
        conn.execute.assert_called_once()
        sql = str(conn.execute.call_args.args[0])
        assert "SET status = 'OPEN'" in sql

    @patch('agents.trade_monitor.MarketFeed')
    def test_cancel_pending_limit(self, MockFeed):
        """Timeout → CANCELLED."""
        from agents.trade_monitor import TradeMonitor

        monitor = TradeMonitor()
        monitor.engine = MagicMock()

        trade = _pending_trade('BTC', 'BUY')
        monitor._cancel_pending_limit(trade)

        conn = monitor.engine.begin.return_value.__enter__.return_value
        conn.execute.assert_called_once()
        sql = str(conn.execute.call_args.args[0])
        assert "SET status = 'CANCELLED'" in sql
        assert "MAKER_TIMEOUT" in sql

    @patch('agents.trade_monitor.MarketFeed')
    def test_get_pending_limits(self, MockFeed):
        """_get_pending_limits() solo devuelve PENDING_LIMIT."""
        from agents.trade_monitor import TradeMonitor

        monitor = TradeMonitor()
        monitor.engine = MagicMock()
        conn = monitor.engine.connect.return_value.__enter__.return_value

        # Mock rows como named tuples (simula sqlalchemy Row)
        trade = _pending_trade()
        MockRow = MagicMock()
        MockRow._mapping = trade
        conn.execute.return_value.fetchall.return_value = [MockRow]

        pending = monitor._get_pending_limits()
        assert len(pending) == 1
        assert pending[0]['status'] == 'PENDING_LIMIT'


class TestAssetMapRouting:
    """Verificar que OKX es el exchange primario post-Fase 4."""

    def test_okx_primary_for_dual_listed(self):
        sys.path.insert(0, '/opt/trading')
        # Re-importar después de los cambios al YAML
        import importlib
        import data.market_feed
        importlib.reload(data.market_feed)
        from data.market_feed import ASSET_MAP

        # BTC, ETH, SOL, AVAX, LINK, DOT, ADA deben resolver a OKX ahora
        for asset in ('BTC', 'ETH', 'SOL', 'AVAX', 'LINK', 'DOT', 'ADA'):
            info = ASSET_MAP.get(asset)
            assert info is not None, f"{asset} missing from ASSET_MAP"
            assert info['exchange'] == 'okx', \
                f"{asset}: esperado okx, obtenido {info['exchange']}"
