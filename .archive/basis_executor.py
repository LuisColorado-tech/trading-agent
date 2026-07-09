"""
BasisExecutor — Ejecutor de la estrategia Basis Trade.

Monitorea funding rates, abre y cierra pares spot+futuro.
Paper trading únicamente. Se integra como agente independiente
o se puede llamar desde un cron/orquestador.
"""
import os
import sys
import time
import json
import uuid
import traceback
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')

import yaml
from sqlalchemy import create_engine, text

from strategies.basis_trade import BasisTradeStrategy, BasisTradePosition
from core.notifications import send_telegram

# ── OKX Funding Feed (Kraken Futures API requiere key separada) ──
import ccxt
_okx = ccxt.okx({'enableRateLimit': True})

class OKXFundingFeed:
    """Feed de funding rates usando OKX (sin API key)."""
    SYMBOLS = {'BTC': 'BTC/USDT:USDT', 'ETH': 'ETH/USDT:USDT'}
    INTERVALS_PER_DAY = 3.0

    def get_funding_rate_annual(self, asset: str) -> Optional[float]:
        symbol = self.SYMBOLS.get(asset)
        if not symbol:
            return None
        try:
            r = _okx.fetch_funding_rate(symbol)
            rate = float(r.get('fundingRate', 0) or 0)
            return rate * self.INTERVALS_PER_DAY * 365 * 100
        except Exception:
            return None

    def get_spot_price(self, asset: str) -> Optional[float]:
        try:
            pair = f'{asset}/USDT'
            ticker = _okx.fetch_ticker(pair)
            return float(ticker.get('last', 0)) if ticker else None
        except Exception:
            return None

    def get_futures_price(self, asset: str) -> Optional[float]:
        """Precio del futuro (mark price del swap perpetuo)."""
        try:
            symbol = self.SYMBOLS.get(asset)
            if not symbol:
                return None
            ticker = _okx.fetch_ticker(symbol)
            return float(ticker.get('last', 0)) if ticker else None
        except Exception:
            return None

    def get_avg_funding_annual(self, asset: str, _days: int = 30) -> Optional[float]:
        """Funding rate anualizado promedio (usamos el actual como proxy)."""
        return self.get_funding_rate_annual(asset)

    def get_basis_pct(self, asset: str) -> Optional[float]:
        """Diferencia porcentual entre futuro y spot."""
        spot = self.get_spot_price(asset)
        fut = self.get_futures_price(asset)
        if spot and fut and spot > 0:
            return (fut - spot) / spot * 100
        return None

okx_feed = OKXFundingFeed()


with open('/opt/trading/config/exchange_config.yaml') as f:
    CFG = yaml.safe_load(f).get('basis_trade', {})

INITIAL_BALANCE = CFG.get('initial_balance', 500.0)
CHECK_INTERVAL = CFG.get('check_interval_minutes', 60) * 60
MAX_POSITIONS = CFG.get('max_positions', 2)

db_url = (
    f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
    f"@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}"
    f"/{os.getenv('POSTGRES_DB', 'trading_agent')}"
)
engine = create_engine(db_url)
feed = okx_feed
strategy = BasisTradeStrategy(CFG)

logger.info(f"BasisExecutor: {len(CFG.get('contracts', []))} contratos, "
            f"min_funding={CFG.get('min_funding_rate_annual', 8.0)}% anual")


def open_positions() -> list[dict]:
    """Retorna posiciones BASIS_TRADE abiertas desde DB."""
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM trades WHERE status='OPEN' AND strategy='BASIS_TRADE'")
        ).fetchall()
    return [dict(r._mapping) for r in rows]


def count_open() -> int:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT COUNT(*) FROM trades WHERE status='OPEN' AND strategy='BASIS_TRADE'")
        ).scalar() or 0


def open_basis_trade(signal, spot_price: float, capital: float):
    """Abre un basis trade: compra spot + vende futuro. PAPER."""
    size = strategy.calculate_position_size(capital, spot_price)
    if size <= 0:
        logger.warning(f"BASIS: size=0 para {signal.asset}")
        return

    trade_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    meta = json.dumps({
        'basis_trade': True,
        'funding_rate': signal.funding_rate,
        'funding_annual_pct': signal.funding_annual_pct,
        'futures_entry': signal.futures_price,
        'basis_pct': signal.basis_pct,
    })

    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO trades (id, asset, side, strategy, entry_price, stop_loss, take_profit,
                                position_size, position_pct, pnl, status, close_reason, paper_trade,
                                timestamp_open, metadata)
            VALUES (:id, :asset, 'BUY', 'BASIS_TRADE', :entry, 0, 0,
                    :size, 0, 0, 'OPEN', NULL, true, :now, CAST(:meta AS jsonb))
        """), {
            'id': trade_id,
            'asset': signal.asset,
            'entry': round(spot_price, 2),
            'size': round(size, 8),
            'now': now,
            'meta': meta,
        })

    logger.info(
        f"BASIS_TRADE OPEN: {signal.asset} size={size:.6f} "
        f"funding={signal.funding_annual_pct:.1f}%/yr spot=${spot_price:.2f}"
    )


def close_basis_trade(trade: dict, reason: str, pnl: float, exit_price: float):
    """Cierra un basis trade: vender spot + recomprar futuro."""
    now = datetime.now(timezone.utc)
    pnl_pct = (pnl / (float(trade['entry_price']) * float(trade['position_size']))) * 100 if float(trade['position_size']) else 0

    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE trades SET status='CLOSED', exit_price=:ep, close_reason=:reason,
                pnl=:pnl, pnl_pct=:pnl_pct, timestamp_close=:now
            WHERE id=:id
        """), {
            'id': trade['id'], 'ep': round(exit_price, 2),
            'reason': reason, 'pnl': round(pnl, 4),
            'pnl_pct': round(pnl_pct, 2), 'now': now,
        })

    logger.info(f"BASIS_TRADE CLOSE: {trade['asset']} {reason} PnL=${pnl:.4f}")


def run_cycle():
    """Un ciclo de evaluacion de funding rates."""
    for asset in strategy.contracts:
        funding_annual = feed.get_funding_rate_annual(asset)
        if funding_annual is None:
            logger.debug(f'BASIS {asset}: sin datos de funding')
            continue
        logger.info(f'BASIS {asset}: funding={funding_annual:.1f}%/yr min={strategy.min_funding}%')

        spot = feed.get_spot_price(asset)
        fut = feed.get_futures_price(asset)
        basis = feed.get_basis_pct(asset) or 0
        avg_30d = feed.get_avg_funding_annual(asset) or 0

        signal = strategy.evaluate(asset, funding_annual, spot, fut, basis, avg_30d)
        if signal and signal.is_valid:
            open_basis_trade(signal, spot, INITIAL_BALANCE)


def monitor_positions():
    """Monitorea posiciones abiertas de basis trade."""
    positions = open_positions()
    for pos in positions:
        asset = pos['asset']
        funding_annual = feed.get_funding_rate_annual(asset)
        if funding_annual is None:
            funding_annual = 0

        should_close, reason = strategy.should_close(
            BasisTradePosition(
                asset=asset,
                spot_size=float(pos['position_size']),
                futures_size=float(pos['position_size']),
                spot_entry=float(pos['entry_price']),
                futures_entry=float(pos['entry_price']),
                entry_time=str(pos['timestamp_open']),
            ),
            funding_annual,
            days_to_expiry=60,
        )

        if should_close:
            spot = feed.get_spot_price(asset) or float(pos['entry_price'])
            pnl = 0  # PnL es 0 en market-neutral real; varía solo por tracking
            close_basis_trade(pos, reason, pnl, spot)


def main():
    logger.info("BasisExecutor iniciado — paper trading")
    send_telegram(
        f"📊 <b>Basis Trade Agent iniciado</b>\n"
        f"Contratos: {', '.join(strategy.contracts)}\n"
        f"Min funding: {strategy.min_funding}% anual\n"
        f"Capital: ${INITIAL_BALANCE:.0f}",
        silent=True,
    )

    cycle = 0
    while True:
        try:
            cycle += 1
            monitor_positions()
            run_cycle()
            if cycle % 60 == 0:
                n = count_open()
                logger.info(f"BasisTrade cycle {cycle}: {n} posiciones abiertas")
        except Exception:
            logger.error(f"BasisTrade cycle error:\n{traceback.format_exc()}")
        time.sleep(CHECK_INTERVAL)


if __name__ == '__main__':
    main()
