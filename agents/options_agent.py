"""
options_agent.py — Agente de Theta Farming para Deribit.

Responsabilidades:
  1. Scan periódico: buscar y ejecutar nuevas posiciones PUT
  2. Monitor: revisar stop loss y profit lock en posiciones abiertas
  3. Expiración: cerrar automáticamente posiciones que llegaron al vencimiento
  4. Heartbeat: publicar estado en Redis para el dashboard
  5. Backtesting: guardar snapshots IV para análisis histórico
  6. Notificaciones: Telegram en cada evento importante

Flujo de cada ciclo:
  ┌─────────────────────────────────────────────────────┐
  │  1. Cargar sesión activa (crear si no existe)        │
  │  2. Verificar drawdown halt                          │
  │  3. MONITOR: cerrar posiciones expiradas             │
  │  4. MONITOR: evaluar stop / profit lock en abiertas  │
  │  5. SCAN: buscar nueva entrada si hay cupo           │
  │  6. Guardar snapshot IV (para backtesting)            │
  │  7. Publicar heartbeat Redis                         │
  └─────────────────────────────────────────────────────┘
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

import redis
from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text

sys.path.insert(0, '/opt/trading')
load_dotenv('/opt/trading/config/.env')

from core.deribit_session_manager import DeribitSessionManager
from core.notifications import send_telegram
from strategies.theta_farming import ThetaFarmingStrategy, CONTRACT_SIZE

# ── Config ────────────────────────────────────────────────────────────────────

PAPER_MODE = True                    # Cambiar a False cuando se quiera ir a live
INITIAL_BALANCE_USD = 2000.0         # Capital inicial de la sesión paper
MAX_DRAWDOWN_PCT = 30.0              # Halt si el drawdown supera este %
SCAN_INTERVAL_SECONDS = 3600        # Evaluar nueva entrada cada 1 hora
MONITOR_INTERVAL_SECONDS = 300      # Verificar stops cada 5 minutos

_db_url = (
    f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
    f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT', '5432')}"
    f"/{os.getenv('POSTGRES_DB')}"
)


class OptionsAgent:
    """Agente de theta farming: ciclo completo scan + monitor + heartbeat."""

    def __init__(self):
        self.session_mgr = DeribitSessionManager(_db_url)
        self.strategy = ThetaFarmingStrategy()
        self.engine = create_engine(_db_url)
        self._redis = self._connect_redis()
        self._last_scan_time: float = 0.0
        self._last_snapshot_time: float = 0.0
        self._snapshot_interval = 3600.0  # guardar snapshot IV cada hora

    def _connect_redis(self):
        try:
            r = redis.Redis(
                host=os.getenv('REDIS_HOST', 'localhost'),
                port=int(os.getenv('REDIS_PORT', 6379)),
                password=os.getenv('REDIS_PASSWORD') or None,
                decode_responses=True,
            )
            r.ping()
            return r
        except Exception as e:
            logger.warning(f'Redis no disponible: {e} — heartbeat desactivado')
            return None

    # ── Ciclo principal ────────────────────────────────────────────────────────

    def run_cycle(self):
        """Ejecuta un ciclo completo del agente."""
        now = time.time()

        # 1. Sesión
        session = self.session_mgr.ensure_active_session(INITIAL_BALANCE_USD)
        session_name = session['session_name']
        logger.info(f'OPTIONS CYCLE START | session={session_name} | mode={"paper" if PAPER_MODE else "live"}')

        # 2. Drawdown halt
        dd_check = self.session_mgr.check_drawdown_halt(str(session['id']), MAX_DRAWDOWN_PCT)
        if dd_check['halt']:
            msg = (
                f'⛔ <b>OPTIONS HALT</b>\n'
                f'Sesión: {session_name}\n'
                f'Drawdown: {dd_check["current_dd"]:.1f}% ≥ {MAX_DRAWDOWN_PCT:.0f}%\n'
                f'Balance: ${float(session["current_balance_usd"]):.2f}'
            )
            send_telegram(msg)
            self._publish_heartbeat(session, halted=True)
            return

        open_positions = self.session_mgr.get_open_positions(session_name)
        open_instruments = {p['instrument_name'] for p in open_positions}

        # 3. Cerrar expired
        self._close_expired_positions(session_name)

        # 4. Monitor stops / profit lock en abiertas
        self._monitor_open_positions(open_positions, session_name)

        # Re-cargar session después de cierres
        session = self.session_mgr.ensure_active_session()
        open_positions = self.session_mgr.get_open_positions(session_name)
        open_instruments = {p['instrument_name'] for p in open_positions}

        # 5. Scan nueva entrada (solo cada SCAN_INTERVAL)
        if now - self._last_scan_time >= SCAN_INTERVAL_SECONDS:
            self._scan_new_entry(session, open_instruments)
            self._last_scan_time = now

        # 6. Snapshot IV para backtesting (cada hora)
        if now - self._last_snapshot_time >= self._snapshot_interval:
            self._save_iv_snapshot()
            self._last_snapshot_time = now

        # 7. Heartbeat
        session = self.session_mgr.ensure_active_session()
        open_positions_final = self.session_mgr.get_open_positions(session['session_name'])
        self._publish_heartbeat(session)

        logger.info(
            f'OPTIONS CYCLE END | open={len(open_positions_final)} | '
            f'balance=${float(session["current_balance_usd"]):.2f} | '
            f'PnL=${float(session["total_pnl_usd"]):+.2f}'
        )

    # ── Gestión de posiciones expiradas ───────────────────────────────────────

    def _close_expired_positions(self, session_name: str):
        """Cierra posiciones cuya fecha de expiración ya pasó."""
        expired = self.session_mgr.get_expired_open_positions(session_name)
        if not expired:
            return

        for pos in expired:
            instrument_name = pos['instrument_name']
            btc_price = self.strategy._get_btc_index_price() or float(pos.get('btc_price_at_entry', 74000))
            strike = float(pos['strike'])

            if PAPER_MODE:
                # En paper: verificamos si BTC cerró por debajo del strike
                if btc_price < strike:
                    # Asignado: pérdida = intrínseco del PUT = (strike - btc_price) × contratos
                    loss_usd = (strike - btc_price) * float(pos['contracts'])
                    exit_premium_usd = loss_usd + float(pos['entry_premium_usd'])
                    exit_premium_btc = exit_premium_usd / btc_price if btc_price > 0 else 0
                    reason = 'ASSIGNED'
                else:
                    # Expiró worthless: ganamos la prima completa
                    exit_premium_btc = 0.0
                    exit_premium_usd = 0.0
                    reason = 'EXPIRED'
            else:
                # Live: consultar valor real del instrumento
                mark = self.strategy.get_current_mark_price(instrument_name)
                if mark is None:
                    mark = 0.0
                exit_premium_btc = mark
                exit_premium_usd = mark * btc_price
                reason = 'ASSIGNED' if btc_price < strike else 'EXPIRED'

            result = self.session_mgr.close_position(
                position_id=str(pos['id']),
                exit_premium_btc=exit_premium_btc,
                exit_premium_usd=exit_premium_usd,
                btc_price_at_exit=btc_price,
                exit_reason=reason,
            )

            pnl = result['pnl_usd']
            icon = '✅' if reason == 'EXPIRED' else '⚠️'
            msg = (
                f'{icon} <b>OPTIONS EXPIRACIÓN</b>\n'
                f'Instrumento: <code>{instrument_name}</code>\n'
                f'Strike: ${strike:,.0f} | BTC: ${btc_price:,.0f}\n'
                f'Resultado: <b>{reason}</b>\n'
                f'PnL: <b>${pnl:+.2f}</b>\n'
                f'Sesión: {session_name}'
            )
            send_telegram(msg)
            logger.info(f'EXPIRED: {instrument_name} | {reason} | PnL=${pnl:+.2f}')

    # ── Monitor de posiciones abiertas ────────────────────────────────────────

    def _monitor_open_positions(self, open_positions: list[dict], session_name: str):
        """Revisa stop loss y profit lock en cada posición abierta."""
        btc_price = self.strategy._get_btc_index_price()

        for pos in open_positions:
            instrument_name = pos['instrument_name']
            entry_premium_btc = float(pos['entry_premium_btc'])

            if btc_price is None:
                logger.warning(f'MONITOR: sin precio BTC para {instrument_name}')
                continue

            close_reason = self.strategy.should_close_position(
                instrument_name=instrument_name,
                entry_premium_btc=entry_premium_btc,
                btc_price=btc_price,
            )

            if close_reason is None:
                continue

            # Obtener precio actual de cierre
            mark = self.strategy.get_current_mark_price(instrument_name)
            if mark is None:
                logger.warning(f'MONITOR: no se pudo obtener mark price de {instrument_name} para cerrar')
                continue

            exit_premium_usd = mark * btc_price
            result = self.session_mgr.close_position(
                position_id=str(pos['id']),
                exit_premium_btc=mark,
                exit_premium_usd=exit_premium_usd,
                btc_price_at_exit=btc_price,
                exit_reason=close_reason,
            )

            pnl = result['pnl_usd']
            icon = '🛑' if 'STOP' in close_reason else '🔒'
            msg = (
                f'{icon} <b>OPTIONS CIERRE</b>\n'
                f'Instrumento: <code>{instrument_name}</code>\n'
                f'Razón: <b>{close_reason}</b>\n'
                f'PnL: <b>${pnl:+.2f}</b>\n'
                f'Entrada: {entry_premium_btc:.5f} BTC\n'
                f'Salida:  {mark:.5f} BTC\n'
                f'Sesión: {session_name}'
            )
            send_telegram(msg)
            logger.info(f'MONITOR CLOSE: {instrument_name} | {close_reason} | PnL=${pnl:+.2f}')

    # ── Scan nueva entrada ────────────────────────────────────────────────────

    def _scan_new_entry(self, session: dict, open_instruments: set[str]):
        """Busca y ejecuta una nueva posición PUT si las condiciones son favorables."""
        session_balance = float(session['current_balance_usd'])
        open_positions = self.session_mgr.get_open_positions(session['session_name'])
        margin_in_use = sum(float(p.get('margin_required_usd', 0)) for p in open_positions)

        signal = self.strategy.evaluate(
            open_instruments=open_instruments,
            session_balance=session_balance,
            margin_in_use=margin_in_use,
        )

        if signal is None:
            logger.info('SCAN: sin señal de theta farming')
            return

        if not signal.approved:
            logger.info(f'SCAN: señal rechazada — {signal.reason}')
            return

        # Ejecutar (paper: solo registra en DB; live: llamada a Deribit)
        if not PAPER_MODE:
            success = self._execute_live_sell(signal)
            if not success:
                logger.error(f'SCAN: fallo en ejecución live de {signal.instrument_name}')
                return

        # Registrar en DB
        position_data = {
            'instrument_name': signal.instrument_name,
            'underlying': signal.underlying,
            'option_type': signal.option_type,
            'strike': signal.strike,
            'expiration_date': signal.expiration_date,
            'dte_at_entry': signal.dte,
            'contracts': signal.contracts,
            'entry_premium_btc': signal.entry_premium_btc,
            'entry_premium_usd': signal.entry_premium_usd,
            'btc_price_at_entry': signal.btc_price,
            'iv_at_entry': signal.iv_pct,
            'iv_rank_at_entry': signal.iv_rank,
            'delta_at_entry': signal.delta,
            'theta_at_entry': signal.theta,
            'margin_required_usd': signal.margin_required_usd,
            'expires_at': datetime.combine(signal.expiration_date, datetime.min.time()).replace(
                tzinfo=timezone.utc, hour=8  # Deribit expira a las 08:00 UTC
            ),
            'strategy_reasoning': signal.strategy_reasoning,
            'iv_rank_signal': signal.iv_rank_signal,
            'market_conditions': signal.market_conditions,
        }

        pos_id = self.session_mgr.open_position(session, position_data)

        msg = (
            f'📝 <b>OPTIONS NUEVA POSICIÓN {"PAPER" if PAPER_MODE else "LIVE"}</b>\n'
            f'Instrumento: <code>{signal.instrument_name}</code>\n'
            f'Strike: ${signal.strike:,.0f} ({signal.otm_pct*100:.1f}% OTM)\n'
            f'DTE: {signal.dte} días | Expira: {signal.expiration_date}\n'
            f'Prima cobrada: ${signal.entry_premium_usd:.2f}\n'
            f'Margen: ${signal.margin_required_usd:.0f}\n'
            f'IV: {signal.iv_pct:.0f}% | IV Rank: {signal.iv_rank:.0f}% ({signal.iv_rank_signal})\n'
            f'Delta: {signal.delta:.3f}\n'
            f'Stop (2×): {signal.stop_price_btc:.5f} BTC\n'
            f'Lock 80%: {signal.profit_lock_price_btc:.5f} BTC'
        )
        send_telegram(msg)
        logger.info(f'SCAN EXECUTED: {signal.instrument_name} | premium=${signal.entry_premium_usd:.2f}')

    # ── Snapshot IV para backtesting ──────────────────────────────────────────

    def _save_iv_snapshot(self):
        """Guarda datos del better candidate en options_market_data."""
        try:
            btc_price = self.strategy._get_btc_index_price()
            iv_rank = self.strategy._get_iv_rank()
            if not btc_price:
                return

            puts = self.strategy._fetch_btc_puts()
            if not puts:
                return

            now = datetime.now(timezone.utc)
            count = 0
            for put in puts[:20]:  # guardar los 20 primeros PUTs para análisis histórico
                try:
                    ticker = self.strategy._get_ticker(put['instrument_name'])
                    if not ticker:
                        continue
                    from datetime import date as date_type
                    exp_ts = put.get('expiration_timestamp', 0)
                    exp_dt = datetime.fromtimestamp(exp_ts / 1000, tz=timezone.utc)
                    dte = max(0, (exp_dt - now).days)
                    greeks = ticker.get('greeks', {}) or {}

                    self.session_mgr.save_market_snapshot({
                        'instrument_name': put['instrument_name'],
                        'underlying': 'BTC',
                        'timestamp': now,
                        'btc_price': btc_price,
                        'strike': float(put.get('strike', 0)),
                        'expiration_date': exp_dt.date(),
                        'dte': dte,
                        'option_type': 'PUT',
                        'bid_btc': float(ticker.get('best_bid_price', 0) or 0),
                        'ask_btc': float(ticker.get('best_ask_price', 0) or 0),
                        'mark_btc': float(ticker.get('mark_price', 0) or 0),
                        'iv_pct': float(ticker.get('mark_iv', 0) or 0),
                        'delta': float((greeks.get('delta') or 0)),
                        'gamma': float((greeks.get('gamma') or 0)),
                        'theta': float((greeks.get('theta') or 0)),
                        'vega': float((greeks.get('vega') or 0)),
                        'dvol_current': iv_rank,
                        'dvol_rank_30d': iv_rank,
                    })
                    count += 1
                    time.sleep(0.2)  # rate limit Deribit
                except Exception as e:
                    logger.debug(f'Snapshot error {put["instrument_name"]}: {e}')
                    continue

            logger.info(f'IV SNAPSHOT: {count} instrumentos guardados')
        except Exception as e:
            logger.warning(f'Save IV snapshot error: {e}')

    # ── Heartbeat Redis ───────────────────────────────────────────────────────

    def _publish_heartbeat(self, session: dict, halted: bool = False):
        """Publica estado del agente en Redis para el dashboard."""
        if self._redis is None:
            return
        try:
            open_positions = self.session_mgr.get_open_positions(session['session_name'])
            payload = {
                'agent': 'options',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'session_name': session['session_name'],
                'mode': 'paper' if PAPER_MODE else 'live',
                'status': 'HALTED' if halted else 'ACTIVE',
                'balance_usd': float(session['current_balance_usd']),
                'initial_balance_usd': float(session['initial_balance_usd']),
                'total_pnl_usd': float(session['total_pnl_usd']),
                'total_contracts': int(session['total_contracts']),
                'open_positions': len(open_positions),
                'open_instruments': [p['instrument_name'] for p in open_positions],
                'max_drawdown_pct': float(session['max_drawdown_pct']),
            }
            self._redis.set('options:heartbeat', json.dumps(payload), ex=7200)
        except Exception as e:
            logger.warning(f'Heartbeat Redis error: {e}')

    # ── Ejecución live (Deribit API) ──────────────────────────────────────────

    def _execute_live_sell(self, signal) -> bool:
        """Vende un PUT en Deribit (modo live). Requiere API keys."""
        try:
            import ccxt
            exchange = ccxt.deribit({
                'apiKey': os.getenv('DERIBIT_API_KEY', ''),
                'secret': os.getenv('DERIBIT_SECRET', ''),
                'enableRateLimit': True,
            })
            # SELL = vender el PUT (cobrar prima)
            order = exchange.create_order(
                symbol=signal.instrument_name,
                type='limit',
                side='sell',
                amount=signal.contracts,
                price=signal.bid_btc,  # vendemos al bid para asegurar ejecución
            )
            logger.info(f'LIVE ORDER: {order}')
            return True
        except Exception as e:
            logger.error(f'Live order failed: {e}')
            return False
