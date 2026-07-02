"""
conftest.py — Fixtures compartidos para toda la suite de tests.
Provee objetos mock (portfolio, signal, trades) para testing sin DB.
"""
import sys
import pytest

sys.path.insert(0, '/opt/trading')


# ── Portfolio fixtures ────────────────────────────────────────────

@pytest.fixture
def base_portfolio():
    """Portfolio base con $10,000 y sin posiciones abiertas."""
    return {
        'total_balance': 10000.0,
        'available_cash': 10000.0,
        'exposure_pct': 0.0,
        'drawdown_pct': 0.0,
        'peak_balance': 10000.0,
    }


@pytest.fixture
def portfolio_with_exposure():
    """Portfolio con 2% exposure (2 trades abiertos a 1% riesgo cada uno)."""
    return {
        'total_balance': 10000.0,
        'available_cash': 5000.0,
        'exposure_pct': 0.02,
        'drawdown_pct': 0.0,
        'peak_balance': 10000.0,
    }


@pytest.fixture
def portfolio_high_exposure():
    """Portfolio con 4.5% exposure — cerca del límite de 5%."""
    return {
        'total_balance': 10000.0,
        'available_cash': 2000.0,
        'exposure_pct': 0.045,
        'drawdown_pct': 0.0,
        'peak_balance': 10000.0,
    }


@pytest.fixture
def portfolio_max_drawdown():
    """Portfolio con drawdown 10% — debería detener trading."""
    return {
        'total_balance': 9000.0,
        'available_cash': 9000.0,
        'exposure_pct': 0.0,
        'drawdown_pct': 0.10,
        'peak_balance': 10000.0,
    }


# ── Signal fixtures ───────────────────────────────────────────────

@pytest.fixture
def btc_buy_signal():
    """Señal BUY BTC estándar con SL/TP basados en ATR."""
    return {
        'asset': 'BTC',
        'direction': 'BUY',
        'strategy': 'TREND_MOMENTUM',
        'timeframe': '15m',
        'score': 80,
        'stop_loss': 74000.0,      # entry - 1.5*ATR (ATR≈666)
        'take_profit': 77000.0,     # entry + 3.0*ATR (net RR≥1 con fee Kraken 0.96%)
        'indicators': {
            'price': 75000.0,
            'rsi': 55.0,
            'atr': 666.0,
            'trend': 'UP',
        },
    }


@pytest.fixture
def eth_buy_signal():
    """Señal BUY ETH estándar."""
    return {
        'asset': 'ETH',
        'direction': 'BUY',
        'strategy': 'TREND_MOMENTUM',
        'timeframe': '15m',
        'score': 75,
        'stop_loss': 2280.0,
        'take_profit': 2380.0,
        'indicators': {
            'price': 2320.0,
            'rsi': 52.0,
            'atr': 26.67,
            'trend': 'UP',
        },
    }


@pytest.fixture
def sol_sell_signal():
    """Señal SELL SOL estándar."""
    return {
        'asset': 'SOL',
        'direction': 'SELL',
        'strategy': 'TREND_MOMENTUM',
        'timeframe': '1h',
        'score': 85,
        'stop_loss': 100.0,        # entry + 1.5*ATR
        'take_profit': 92.0,       # entry - 2.5*ATR
        'indicators': {
            'price': 97.0,
            'rsi': 38.0,
            'atr': 2.0,
            'trend': 'DOWN',
        },
    }


@pytest.fixture
def bad_rr_signal():
    """Señal con R:R insuficiente (<1.5)."""
    return {
        'asset': 'BTC',
        'direction': 'BUY',
        'strategy': 'MEAN_REVERSION',
        'timeframe': '15m',
        'score': 70,
        'stop_loss': 74000.0,
        'take_profit': 75500.0,     # RR = 500/1000 = 0.5
        'indicators': {
            'price': 75000.0,
            'rsi': 30.0,
            'atr': 666.0,
            'trend': 'SIDEWAYS',
        },
    }


# ── Open trades fixtures ─────────────────────────────────────────

@pytest.fixture
def no_open_trades():
    """Sin trades abiertos."""
    return []


@pytest.fixture
def one_btc_open():
    """Un trade BTC abierto."""
    return [
        {
            'id': 'trade-001',
            'asset': 'BTC',
            'side': 'BUY',
            'entry_price': 74000.0,
            'stop_loss': 73000.0,
            'take_profit': 75500.0,
            'position_size': 0.1,
            'status': 'OPEN',
        }
    ]


@pytest.fixture
def two_trades_open():
    """Dos trades abiertos (BTC + ETH)."""
    return [
        {
            'id': 'trade-001',
            'asset': 'BTC',
            'side': 'BUY',
            'entry_price': 74000.0,
            'stop_loss': 73000.0,
            'take_profit': 75500.0,
            'position_size': 0.1,
            'status': 'OPEN',
        },
        {
            'id': 'trade-002',
            'asset': 'ETH',
            'side': 'BUY',
            'entry_price': 2300.0,
            'stop_loss': 2270.0,
            'take_profit': 2375.0,
            'position_size': 3.33,
            'status': 'OPEN',
        },
    ]


@pytest.fixture
def three_trades_open():
    """Tres trades abiertos (máximo permitido)."""
    return [
        {
            'id': 'trade-001', 'asset': 'BTC', 'side': 'BUY',
            'entry_price': 74000.0, 'stop_loss': 73000.0,
            'take_profit': 75500.0, 'position_size': 0.1,
        },
        {
            'id': 'trade-002', 'asset': 'ETH', 'side': 'BUY',
            'entry_price': 2300.0, 'stop_loss': 2270.0,
            'take_profit': 2375.0, 'position_size': 3.33,
        },
        {
            'id': 'trade-003', 'asset': 'SOL', 'side': 'BUY',
            'entry_price': 95.0, 'stop_loss': 93.0,
            'take_profit': 100.0, 'position_size': 50.0,
        },
    ]
