"""
StocksAgent — Agente de trading de acciones NYSE/NASDAQ.

Arquitectura idéntica al StrategyEngine del crypto agent, adaptada para:
- Acciones (Alpaca como broker)
- Horario NYSE: 14:30-21:00 UTC, lunes a viernes
- Señales xsignals como boost (no como bloqueante)
- Macro filter: bloquear BUY cuando SPY+QQQ están en BEAR
- Fractional shares: operamos en USD notional (no en unidades)

Ciclo:
  1. Verificar horario NYSE
  2. Calcular macro bias (SPY/QQQ)
  3. Para cada activo: calcular indicadores → StocksMomentumStrategy
  4. Buscar boost xsignals en PostgreSQL (últimas 48h)
  5. Evaluar confluencia mínima
  6. Ejecutar orden en Alpaca (paper o live)
  7. Monitorear posiciones abiertas (SL/TP)
  8. Notificar por Telegram

Uso:
  python3 agents/stocks_agent.py            # loop continuo
  python3 agents/stocks_agent.py --once     # un ciclo y salir
  python3 agents/stocks_agent.py --dry-run  # evalúa pero no ejecuta órdenes
"""
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text

load_dotenv('/opt/trading/config/.env')
sys.path.insert(0, '/opt/trading')

from agents.indicators import IndicatorEngine
from core.market_regime import classify_market_regime
from core.notifications import send_telegram
from core.stocks_profiles import get_stocks_profile, stocks_direction_allowed
from data.stocks_feed import StocksFeed
from strategies.stocks_momentum import StocksMomentumStrategy
from strategies.stocks_trend_etf import StocksTrendEtfStrategy


# ── Parámetros globales del agente ────────────────────────────────────────────

STOCKS_UNIVERSE = [
    # Acciones individuales — solo TSLA (PF=1.23 backtest 2Y)
    'TSLA',
    # ETFs USA
    'QQQ',   # PF=1.06 — TREND_ETF strategy
    'GLD',   # PF=1.21 — TREND_ETF strategy, bull run oro 2024-26
    # ETFs internacionales
    'EEM',   # PF=1.23 — Emergentes
    'FXI',   # PF=1.23 — China
    'EWJ',   # PF=1.19 — Japón
]
# Eliminados por PF < 1.0 en backtest 2Y:
# NVDA 0.96, AAPL 0.81, META 0.88, AMZN 0.88, SPY 0.93, EWZ 0.91
CYCLE_INTERVAL_SECONDS = 60 * 5     # evaluar cada 5 minutos
MAX_CONCURRENT_TRADES = 3
MAX_RISK_PER_TRADE_PCT = 0.01       # 1% del balance por trade
MAX_PORTFOLIO_EXPOSURE = 0.08       # 8% del balance total en stocks
MAX_DRAWDOWN_STOP = 0.10            # detener si balance cae 10%
MIN_CONFLUENCE = 3                  # indicadores alineados mínimos
XSIGNAL_LOOKBACK_HOURS = 48        # horas de lookback para xsignals boost


class StocksAgent:
    """Agente de trading de acciones. Instanciar y llamar .run()."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run

        # DB
        db_url = (
            f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
            f"@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}"
            f"/{os.getenv('POSTGRES_DB', 'trading_agent')}"
        )
        self.engine = create_engine(db_url)

        # Brokers y feeds
        self.feed = StocksFeed()
        self._alpaca = None
        self._init_alpaca()

        # Sesión activa
        from core.alpaca_session_manager import AlpacaSessionManager
        self.session_mgr = AlpacaSessionManager(db_url)
        initial_balance = float(os.getenv('STOCKS_INITIAL_BALANCE', '220'))
        self.session = self.session_mgr.ensure_active_session(initial_balance)
        logger.info(f"Sesión activa: {self.session['session_name']} | balance={self.session['current_balance']}")

        # Estrategias — una instancia por tipo, elegida por perfil
        self._strategies = {
            'MOMENTUM':  StocksMomentumStrategy(),
            'TREND_ETF': StocksTrendEtfStrategy(),
        }
        # Mantener self.strategy apuntando al default para compatibilidad
        self.strategy = self._strategies['MOMENTUM']

        mode = 'DRY_RUN' if dry_run else ('PAPER' if os.getenv('PAPER_TRADING', 'true').lower() == 'true' else 'LIVE')
        send_telegram(
            f"🤖 <b>StocksAgent arrancado</b>\n"
            f"Modo: <b>{mode}</b>\n"
            f"Universo: {', '.join(STOCKS_UNIVERSE)}\n"
            f"Sesión: {self.session['session_name']}"
        )

    def _init_alpaca(self):
        try:
            from core.alpaca_session_manager import get_alpaca_client
            self._alpaca = get_alpaca_client()
            logger.info("Alpaca conectado")
        except RuntimeError as e:
            logger.warning(f"Alpaca no disponible: {e}")
            if not self.dry_run:
                logger.warning("Sin Alpaca, operando en dry_run mode")
                self.dry_run = True

    # ── Loop principal ────────────────────────────────────────────────────────

    def run(self, once: bool = False):
        """Loop principal del agente."""
        logger.info("StocksAgent iniciado")
        while True:
            try:
                self._cycle()
            except Exception as e:
                logger.error(f"Error en ciclo: {e}", exc_info=True)
                send_telegram(f"⚠️ StocksAgent error: {e}")

            if once:
                break

            logger.info(f"Próximo ciclo en {CYCLE_INTERVAL_SECONDS}s...")
            time.sleep(CYCLE_INTERVAL_SECONDS)

    def _cycle(self):
        """Un ciclo completo: evaluar activos + monitorear posiciones abiertas."""
        now = datetime.now(timezone.utc)

        # 1. Verificar horario NYSE
        if not self._is_nyse_open(now):
            logger.info(f"NYSE cerrado ({now.strftime('%H:%M UTC')}). Ciclo saltado.")
            return

        # 2. Monitorear posiciones abiertas (SL/TP)
        self._monitor_open_trades()

        # 3. Verificar límite de trades concurrentes
        open_trades = self.session_mgr.get_open_trades(self.session['id'])
        if len(open_trades) >= MAX_CONCURRENT_TRADES:
            logger.info(f"Máximo de trades concurrentes alcanzado ({MAX_CONCURRENT_TRADES})")
            return

        # 4. Macro bias
        macro = self.feed.get_macro_bias()
        logger.info(f"Macro bias: {macro}")

        # 5. Evaluar cada activo
        for symbol in STOCKS_UNIVERSE:
            try:
                self._evaluate_symbol(symbol, macro, open_trades)
            except Exception as e:
                logger.error(f"Error evaluando {symbol}: {e}")

    def _evaluate_symbol(self, symbol: str, macro: str, open_trades: list):
        """Evalúa un símbolo y ejecuta trade si hay señal."""
        profile = get_stocks_profile(symbol)

        # No abrir segundo trade en el mismo símbolo
        symbols_in_trade = {t['symbol'] for t in open_trades}
        if symbol in symbols_in_trade:
            return

        # Datos OHLCV
        df = self.feed.get_latest(symbol, '15m', 200)
        if df.empty or len(df) < 50:
            logger.debug(f"{symbol}: sin datos suficientes")
            return

        ind = IndicatorEngine.calculate(df, symbol, '15m')
        if ind is None:
            return

        # Régimen de mercado — solo para activos con use_regime_filter=True
        if profile.use_regime_filter:
            regime = classify_market_regime(ind)
            if not (regime.allow_trend or regime.allow_breakout):
                logger.debug(f"{symbol}: régimen bloqueante ({regime.name})")
                return

        # xsignals boost (últimas 48h)
        xboost, xside = self._get_xsignal_boost(symbol, profile)

        # Evaluar estrategia — elegida por perfil del símbolo
        strategy = self._strategies.get(profile.strategy_name, self._strategies['MOMENTUM'])
        result = strategy.score(ind, xsignal_boost=xboost if xside else 0)

        if result['direction'] == 'NEUTRAL':
            logger.debug(f"{symbol}: NEUTRAL score={result['score']}")
            return

        direction = result['direction']

        # Filtro macro: si hay bear macro, no abrir BUY en acciones individuales
        if macro == 'BEAR' and direction == 'BUY' and profile.use_macro_filter:
            logger.info(f"{symbol}: BUY bloqueado por macro BEAR")
            return

        # Filtro xsignal: si hay señal contraria fuerte, reducir boost
        if xside and xside != direction:
            logger.info(f"{symbol}: xsignal {xside} opuesto a {direction} — sin boost")
            result = strategy.score(ind, xsignal_boost=0)
            if result['direction'] != direction:
                return

        # Verificar dirección permitida
        if not stocks_direction_allowed(symbol, direction):
            logger.debug(f"{symbol}: dirección {direction} no permitida por perfil")
            return

        # Confluencia mínima
        n_conf = sum(1 for r in result.get('reasons', [])
                     if not r.startswith('XSIGNAL') and not r.startswith('RSI_'))
        if n_conf < MIN_CONFLUENCE:
            logger.debug(f"{symbol}: confluencia insuficiente ({n_conf}/{MIN_CONFLUENCE})")
            return

        logger.info(
            f"SEÑAL {symbol} {direction} score={result['score']} "
            f"conf={n_conf} reasons={result['reasons']}"
        )

        # Calcular tamaño de posición
        balance = float(self.session.get('current_balance', 0))
        if balance <= 0:
            logger.warning("Balance 0 — sin capital")
            return

        risk_usd = balance * MAX_RISK_PER_TRADE_PCT
        atr = ind.atr
        sl_dist = abs(ind.close - result['stop_loss'])
        if sl_dist <= 0:
            return

        qty = risk_usd / sl_dist
        notional = qty * ind.close

        # Cap de exposición total
        total_exposed = sum(float(t.get('notional', 0)) for t in open_trades)
        if total_exposed + notional > balance * MAX_PORTFOLIO_EXPOSURE:
            logger.info(f"{symbol}: cap de exposición alcanzado ({total_exposed:.2f} + {notional:.2f})")
            return

        # Mínimo $5 por trade (fractional shares Alpaca)
        if notional < 5:
            logger.info(f"{symbol}: notional ${notional:.2f} < $5 mínimo")
            return

        self._execute_trade(
            symbol=symbol,
            direction=direction,
            price=ind.close,
            qty=qty,
            notional=notional,
            stop_loss=result['stop_loss'],
            take_profit=result['take_profit'],
            reasons=result['reasons'],
            xsignal_boost=xboost if xside == direction else 0,
        )

    def _execute_trade(
        self, symbol, direction, price, qty, notional,
        stop_loss, take_profit, reasons, xsignal_boost=0,
    ):
        """Ejecuta la orden y registra el trade en PostgreSQL."""
        side = 'buy' if direction == 'BUY' else 'sell'
        alpaca_order_id = None

        if not self.dry_run and self._alpaca:
            try:
                order = self._alpaca.submit_order(
                    symbol=symbol,
                    notional=round(notional, 2),
                    side=side,
                    order_type='market',
                    time_in_force='day',
                )
                alpaca_order_id = order.get('id')
                logger.info(f"Alpaca order {alpaca_order_id} enviada: {side} {symbol} ${notional:.2f}")
            except Exception as e:
                logger.error(f"Error enviando orden Alpaca {symbol}: {e}")
                send_telegram(f"⚠️ Error orden Alpaca {symbol}: {e}")
                return

        # Registrar en PostgreSQL
        trade_id = self.session_mgr.open_trade(
            session_id=self.session['id'],
            symbol=symbol,
            direction=direction,
            entry_price=price,
            qty=round(qty, 6),
            notional=round(notional, 2),
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy=strategy.NAME,
            alpaca_order_id=alpaca_order_id,
            xsignal_boost=xsignal_boost,
        )

        send_telegram(
            f"{'📈' if direction == 'BUY' else '📉'} <b>TRADE {direction}</b> {symbol}\n"
            f"Entry: ${price:.2f} | Notional: ${notional:.2f}\n"
            f"SL: ${stop_loss:.2f} | TP: ${take_profit:.2f}\n"
            f"Score: {reasons}\n"
            f"{'🔵 xsignal boost' if xsignal_boost else ''}"
        )

    def _monitor_open_trades(self):
        """Verifica SL/TP para cada trade abierto."""
        open_trades = self.session_mgr.get_open_trades(self.session['id'])
        if not open_trades:
            return

        for trade in open_trades:
            symbol = trade['symbol']
            try:
                price = self.feed.get_price(symbol)
                if price <= 0:
                    continue

                hit_sl = (
                    (trade['direction'] == 'BUY' and price <= float(trade['stop_loss'])) or
                    (trade['direction'] == 'SELL' and price >= float(trade['stop_loss']))
                )
                hit_tp = (
                    (trade['direction'] == 'BUY' and price >= float(trade['take_profit'])) or
                    (trade['direction'] == 'SELL' and price <= float(trade['take_profit']))
                )

                if hit_sl or hit_tp:
                    reason = 'SL' if hit_sl else 'TP'
                    self._close_trade(trade, price, reason)

            except Exception as e:
                logger.error(f"Error monitoreando {symbol}: {e}")

    def _close_trade(self, trade: dict, exit_price: float, reason: str):
        """Cierra un trade: cancela en Alpaca y registra en PostgreSQL."""
        if not self.dry_run and self._alpaca and trade.get('alpaca_order_id'):
            try:
                self._alpaca.cancel_order(trade['alpaca_order_id'])
            except Exception:
                pass
            # Enviar orden de cierre
            close_side = 'sell' if trade['direction'] == 'BUY' else 'buy'
            try:
                self._alpaca.submit_order(
                    symbol=trade['symbol'],
                    qty=float(trade['qty']),
                    side=close_side,
                    order_type='market',
                    time_in_force='day',
                )
            except Exception as e:
                logger.error(f"Error cerrando {trade['symbol']} en Alpaca: {e}")

        closed = self.session_mgr.close_trade(trade['id'], exit_price, reason)
        if closed:
            pnl = closed['pnl']
            emoji = '✅' if pnl > 0 else '❌'
            send_telegram(
                f"{emoji} <b>TRADE CERRADO</b> {trade['symbol']} ({reason})\n"
                f"Entry: ${trade['entry_price']:.2f} → Exit: ${exit_price:.2f}\n"
                f"P&L: <b>${pnl:+.2f}</b>"
            )

    # ── xsignals ─────────────────────────────────────────────────────────────

    def _get_xsignal_boost(self, symbol: str, profile) -> tuple[int, Optional[str]]:
        """Busca señales de xsignals en las últimas 48h para el símbolo.

        Returns:
            (boost_points, direction_from_xsignal) — (0, None) si no hay señal
        """
        if not profile.xsignal_profiles:
            return 0, None
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=XSIGNAL_LOOKBACK_HOURS)
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT side, confidence
                        FROM xsignals_signals
                        WHERE ticker = :sym
                          AND profile = ANY(:profiles)
                          AND published_hint >= :cutoff
                          AND side != 'neutral'
                        ORDER BY published_hint DESC
                        LIMIT 5
                    """),
                    {
                        'sym': symbol.upper(),
                        'profiles': list(profile.xsignal_profiles),
                        'cutoff': cutoff.isoformat(),
                    },
                ).fetchall()

            if not rows:
                return 0, None

            # Mayoría de votos
            from collections import Counter
            sides = Counter(r.side for r in rows)
            dominant_side = sides.most_common(1)[0][0]
            direction = 'BUY' if dominant_side == 'long' else 'SELL'
            avg_conf = sum(r.confidence for r in rows) / len(rows)

            # Boost proporcional a confianza
            boost = profile.xsignal_boost if avg_conf >= 55 else profile.xsignal_boost // 2
            logger.info(f"xsignal {symbol}: {dominant_side} (n={len(rows)}, conf={avg_conf:.0f}) → boost={boost}")
            return boost, direction

        except Exception as e:
            logger.debug(f"xsignal lookup error {symbol}: {e}")
            return 0, None

    # ── Utilidades ────────────────────────────────────────────────────────────

    @staticmethod
    def _is_nyse_open(now: datetime) -> bool:
        """NYSE abierto: 14:30-21:00 UTC, lun-vie."""
        if now.weekday() >= 5:
            return False
        open_h, open_m = 14, 30
        close_h, close_m = 21, 0
        t = now.hour * 60 + now.minute
        return (open_h * 60 + open_m) <= t < (close_h * 60 + close_m)

    def get_status(self) -> dict:
        """Resumen del estado del agente para /stocks_status en Telegram."""
        open_trades = self.session_mgr.get_open_trades(self.session['id'])
        session = self.session

        positions = []
        for t in open_trades:
            price = self.feed.get_price(t['symbol'])
            if t['direction'] == 'BUY':
                unreal_pnl = (price - float(t['entry_price'])) * float(t['qty'])
            else:
                unreal_pnl = (float(t['entry_price']) - price) * float(t['qty'])
            positions.append({
                'symbol': t['symbol'],
                'direction': t['direction'],
                'entry': float(t['entry_price']),
                'current': price,
                'pnl': round(unreal_pnl, 2),
            })

        return {
            'session': session['session_name'],
            'balance': float(session.get('current_balance', 0)),
            'open_trades': len(open_trades),
            'positions': positions,
            'market_open': self._is_nyse_open(datetime.now(timezone.utc)),
            'macro_bias': self.feed.get_macro_bias(),
        }
