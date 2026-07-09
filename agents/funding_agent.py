"""
FundingAgent v2 — Funding Rate Arbitrage en OKX.

Estrategia market-neutral: long spot + short perpetual.
Cobra funding rate sin riesgo direccional.
No usa indicadores técnicos, no predice dirección.

Paper mode por defecto (PAPER_TRADING=true en .env).
"""
import os
import sys
import json
import time
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import ccxt
import redis
from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text

sys.path.insert(0, '/opt/trading')
load_dotenv('/opt/trading/config/.env')

logger.remove()
logger.add(sys.stderr, format='<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}', level='INFO')
logger.add('/opt/trading/logs/funding_{time:YYYY-MM-DD}.log', rotation='1 day', retention='30 days', level='DEBUG')

# ─── Config ────────────────────────────────────────────────────────
MIN_FUNDING_ANNUAL = 0.08     # 8% anual mínimo para entrar
MAX_POSITIONS = 5             # máximo posiciones simultáneas
CAPITAL_PER_POSITION = 500.0  # $500 por par
SCAN_INTERVAL = 3600          # escanear cada hora
MONITOR_INTERVAL = 28800      # 8h = un ciclo de funding
PAPER_MODE = os.getenv('PAPER_TRADING', 'true').lower() == 'true'

PAIRS = ['BTC', 'ETH', 'SOL', 'ADA', 'AAVE', 'LINK', 'DOT', 'AVAX', 'INJ', 'XRP', 'DOGE']

# ─── Database ──────────────────────────────────────────────────────

DB_URL = (
    f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
    f"@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}"
    f"/{os.getenv('POSTGRES_DB', 'trading_agent')}"
)
engine = create_engine(DB_URL)


def get_portfolio():
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT * FROM portfolio_v2 ORDER BY timestamp DESC LIMIT 1"
        )).fetchone()
    if row:
        return dict(row._mapping)
    return {'total_balance': 5500.0, 'available_cash': 5500.0}


def save_portfolio(balance, deployed, earned, fees):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO portfolio_v2 (total_balance, deployed_capital, available_cash,
                                       total_funding_earned, total_fees, net_pnl)
            VALUES (:bal, :dep, :cash, :earned, :fees, :pnl)
        """), {
            'bal': balance, 'dep': deployed,
            'cash': balance - deployed,
            'earned': earned, 'fees': fees,
            'pnl': earned - fees,
        })


def get_open_sessions():
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT * FROM funding_sessions WHERE status = 'ACTIVE'"
        )).fetchall()
    return [dict(r._mapping) for r in rows]


# ─── Funding Agent ─────────────────────────────────────────────────

class FundingAgent:
    def __init__(self):
        self.exchange = ccxt.okx({'enableRateLimit': True,
                                   'apiKey': '', 'secret': ''})
        self.redis = redis.Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            password=os.getenv('REDIS_PASSWORD') or None,
            decode_responses=True,
        )

    def scan(self):
        """Escanea funding rates. Entra si la tasa anualizada > umbral."""
        portfolio = get_portfolio()
        open_sessions = get_open_sessions()
        open_pairs = {s['pair'] for s in open_sessions}
        available = float(portfolio['available_cash'])

        logger.info(f'Scan: balance=${available:.0f} | {len(open_sessions)} open positions')

        for pair in PAIRS:
            if pair in open_pairs:
                continue
            if len(open_sessions) >= MAX_POSITIONS:
                logger.info(f'MAX_POSITIONS ({MAX_POSITIONS}) reached')
                break
            if available < CAPITAL_PER_POSITION:
                logger.info(f'Insufficient cash: ${available:.0f} < ${CAPITAL_PER_POSITION:.0f}')
                break

            try:
                rate_data = self._fetch_funding(pair)
            except Exception as e:
                logger.warning(f'{pair}: funding fetch error: {e}')
                continue

            if rate_data is None:
                continue

            annual = rate_data['annual']
            if annual >= MIN_FUNDING_ANNUAL:
                self._open(pair, rate_data, CAPITAL_PER_POSITION)
                available -= CAPITAL_PER_POSITION

    def _fetch_funding(self, pair):
        """Obtiene funding rate y precios de OKX."""
        perp_symbol = pair + '/USDT:USDT'
        spot_symbol = pair + '/USDT'

        funding = self.exchange.fetch_funding_rate(perp_symbol)
        rate_8h = funding['fundingRate']

        if rate_8h is None or rate_8h <= 0:
            return None

        spot_ticker = self.exchange.fetch_ticker(spot_symbol)
        perp_ticker = self.exchange.fetch_ticker(perp_symbol)

        annual = ((1 + rate_8h) ** (365 * 3) - 1)
        return {
            'pair': pair,
            'rate_8h': rate_8h,
            'annual': annual,
            'spot_price': spot_ticker['last'],
            'perp_price': perp_ticker['last'],
        }

    def _open(self, pair, rate_data, capital):
        """Abre posición: long spot + short perpetual."""
        spot_price = rate_data['spot_price']
        perp_price = rate_data['perp_price']

        qty = capital / spot_price  # mismo qty en spot y perp (market-neutral)

        session_id = str(uuid.uuid4())

        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO funding_sessions (id, pair, capital_usd,
                    entry_spot_price, entry_perp_price,
                    entry_funding_rate, entry_funding_annual,
                    spot_qty, perp_qty)
                VALUES (:id, :pair, :capital,
                    :spot, :perp, :rate, :annual, :qty, :qty)
            """), {
                'id': session_id, 'pair': pair, 'capital': capital,
                'spot': spot_price, 'perp': perp_price,
                'rate': rate_data['rate_8h'], 'annual': rate_data['annual'],
                'qty': qty,
            })

        # Registrar primer funding event
        self._record_funding(session_id, pair, rate_data, qty, spot_price, perp_price, capital)

        logger.info(f'OPEN {pair}: ${capital:.0f} | spot={spot_price:.2f} perp={perp_price:.2f} | '
                    f'rate={rate_data["rate_8h"]*100:.4f}%/8h annual={rate_data["annual"]*100:.1f}%')

    def _record_funding(self, session_id, pair, rate_data, qty, spot, perp, capital):
        funding_earned = capital * rate_data['rate_8h']
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO funding_events (session_id, funding_rate, funding_rate_annual,
                    funding_earned_usd, spot_price, perp_price, balance_usd)
                VALUES (:sid, :rate, :annual, :earned, :spot, :perp, :bal)
            """), {
                'sid': session_id, 'rate': rate_data['rate_8h'],
                'annual': rate_data['annual'],
                'earned': funding_earned, 'spot': spot, 'perp': perp, 'bal': capital,
            })

    def monitor(self):
        """Monitorea posiciones abiertas: cierra si funding_rate cae bajo 0 o umbral."""
        sessions = get_open_sessions()
        if not sessions:
            return

        for s in sessions:
            pair = s['pair']
            try:
                rate_data = self._fetch_funding(pair)
            except Exception as e:
                logger.warning(f'{pair}: monitor error: {e}')
                continue

            if rate_data is None:
                continue

            rate_8h = rate_data['rate_8h']

            # Registrar funding cobrado
            self._record_funding(s['id'], pair, rate_data, float(s['spot_qty']),
                                 rate_data['spot_price'], rate_data['perp_price'],
                                 float(s['capital_usd']))

            # Actualizar totales en la sesión
            funding_earned = float(s['capital_usd']) * rate_8h
            fee_paid = 0  # Fees are charged once at open, not per funding cycle

            with engine.begin() as conn:
                conn.execute(text("""
                    UPDATE funding_sessions
                    SET total_funding_earned = total_funding_earned + :earned,
                        total_fees_paid = total_fees_paid + :fee,
                        net_pnl = total_funding_earned + :earned - (total_fees_paid + :fee)
                    WHERE id = :id
                """), {'earned': funding_earned, 'fee': fee_paid, 'id': s['id']})

            # ¿Cerrar?
            annual = rate_data['annual']
            if annual < MIN_FUNDING_ANNUAL:
                self._close(s, rate_data, f'FUNDING_BELOW_THRESHOLD_{annual*100:.1f}%')
                logger.info(f'CLOSE {pair}: funding {annual*100:.1f}% < {MIN_FUNDING_ANNUAL*100:.0f}% threshold')

    def _close(self, session, rate_data, reason):
        """Cierra posición y liquida PnL."""
        exit_spot = rate_data['spot_price']
        exit_perp = rate_data['perp_price']
        entry_spot = float(session['entry_spot_price'])
        entry_perp = float(session['entry_perp_price'])
        qty = float(session['spot_qty'])

        # Spot PnL
        spot_pnl = (exit_spot - entry_spot) * qty
        # Perp PnL (short: ganancia si precio baja)
        perp_pnl = (entry_perp - exit_perp) * qty
        # Total PnL = spot + perp + funding earned - fees
        earned = float(session['total_funding_earned'] or 0)
        fees = float(session['total_fees_paid'] or 0)
        total_pnl = spot_pnl + perp_pnl + earned - fees

        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE funding_sessions
                SET status = 'CLOSED', close_reason = :reason,
                    net_pnl = :pnl, closed_at = NOW()
                WHERE id = :id
            """), {'reason': reason, 'pnl': total_pnl, 'id': session['id']})

        logger.info(f'CLOSED {session["pair"]}: net_pnl=${total_pnl:+.2f} | reason={reason}')

    def status(self):
        """Reporte de estado."""
        portfolio = get_portfolio()
        sessions = get_open_sessions()
        print(f'\n=== FUNDING AGENT v2 ===')
        print(f'Paper mode: {PAPER_MODE} | Balance: ${portfolio["total_balance"]:,.2f}')
        print(f'Deployed: ${portfolio["deployed_capital"]:,.2f} | Available: ${portfolio["available_cash"]:,.2f}')
        print(f'Funding earned: ${float(portfolio["total_funding_earned"]):.2f} | Fees: ${float(portfolio["total_fees"]):.2f}')
        print(f'\nOpen positions ({len(sessions)}):')
        for s in sessions:
            print(f'  {s["pair"]:<6s} ${float(s["capital_usd"]):>6.0f} | '
                  f'funding={float(s["entry_funding_annual"])*100:.1f}%/yr | '
                  f'earned=${float(s["total_funding_earned"]):.2f} | '
                  f'fees=${float(s["total_fees_paid"]):.2f} | '
                  f'net=${float(s["net_pnl"]):+.2f}')
        print()

    def update_portfolio(self):
        """Actualiza el portfolio con los totales de todas las sesiones."""
        with engine.connect() as conn:
            active = conn.execute(text(
                "SELECT COALESCE(SUM(capital_usd),0) FROM funding_sessions WHERE status='ACTIVE'"
            )).scalar()
            earned = conn.execute(text(
                "SELECT COALESCE(SUM(total_funding_earned),0) FROM funding_sessions"
            )).scalar()
            fees = conn.execute(text(
                "SELECT COALESCE(SUM(total_fees_paid),0) FROM funding_sessions"
            )).scalar()

        total_balance = 5500.0 + float(earned) - float(fees)
        save_portfolio(total_balance, float(active), float(earned), float(fees))


# ─── Main loop ─────────────────────────────────────────────────────

def main():
    agent = FundingAgent()
    logger.info(f'FundingAgent v2 started | Paper: {PAPER_MODE} | Min funding: {MIN_FUNDING_ANNUAL*100:.0f}%/yr')
    logger.info(f'Pairs: {PAIRS} | Max positions: {MAX_POSITIONS} | Capital/pos: ${CAPITAL_PER_POSITION:.0f}')

    scan_count = 0
    while True:
        try:
            scan_count += 1

            # Escanear y abrir posiciones
            agent.scan()

            # Cada 8h (o en cada monitor), registrar funding y evaluar cierres
            agent.monitor()

            # Actualizar portfolio
            agent.update_portfolio()

            logger.info(f'Cycle {scan_count} complete. Next scan in {SCAN_INTERVAL}s')
            time.sleep(SCAN_INTERVAL)

        except KeyboardInterrupt:
            logger.info('Stopped by user')
            break
        except Exception as e:
            logger.error(f'Cycle error: {e}')
            time.sleep(60)


if __name__ == '__main__':
    main()
