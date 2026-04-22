"""
theta_farming.py — Estrategia de Theta Farming / Options Selling.

Filosofía: vender PUTs semanales OTM en BTC cuando las condiciones favorecen al vendedor.
El vendedor cobra la prima. Si BTC no cae hasta el strike, la prima es ganancia pura.

═══════════════════════════════════════════════════════════════════════════════
LÓGICA DE ENTRADA (todos deben cumplirse):

  1. IV RANK ≥ 20%
     Prima suficientemente cara para el riesgo. Con IV baja, la prima no compensa.

  2. DTE entre 3 y 21 días
     < 3 días: muy poco tiempo para que el theta decaiga de forma significativa.
     > 21 días: demasiada exposición a gamma / eventos macro inesperados.

  3. Delta del PUT ≤ -0.20 (OTM)
     Probabilidad de que expire In-The-Money ≤ 20%.
     Preferencia: delta entre -0.05 y -0.15 (5–8% OTM).

  4. Strike 5–10% OTM del precio actual de BTC
     Gap suficiente para absorber movimientos normales sin ser asignado.

  5. Spread bid/ask ≤ 25% del mark price
     Liquidez mínima. Un spread mayor indica poca contraparte disponible.

  6. Sin posición abierta en el mismo instrumento (no duplicar)

  7. Máximo MAX_OPEN_POSITIONS (3) contratos abiertos simultáneos
     Diversificación de strikes y expiraciones. No todo en el mismo strike.

═══════════════════════════════════════════════════════════════════════════════
LÓGICA DE SALIDA:

  A. EXPIRACIÓN NATURAL  (exit_reason = EXPIRED)
     La opción llega al vencimiento sin ser ejercida.
     PnL = +100% de la prima cobrada. El resultado más deseado.

  B. STOP LOSS 2× PRIMA  (exit_reason = STOP_LOSS_2X)
     Si el mark price del PUT sube a 2× la prima que cobramos, recompramos.
     Ejemplo: vendiste a 0.005 BTC → stop si sube a 0.010 BTC.
     Limitamos la pérdida máxima a -100% de la prima (pierdes lo que cobraste).
     Equivalente a una pérdida de ~1× la prima = riesgo controlado.

  C. 80% DE GANANCIA ASEGURADA (exit_reason = PROFIT_LOCK)
     Si la prima cae al 20% del valor de entrada, cerramos antes del vencimiento
     para no exponernos de forma innecesaria al último gamma risk.
     Ejemplo: vendiste a 0.010 → cierra si cae a 0.002.

  D. ASIGNACIÓN (exit_reason = ASSIGNED)
     BTC cerró por debajo del strike al vencimiento → hay que comprar BTC
     al strike (solo en live). En paper se trata como pérdida máxima.

═══════════════════════════════════════════════════════════════════════════════
MARGIN CALCULATION (Deribit PUT, régimen portfolio margin):

  initial_margin = max(0.10, 0.15 - OTM_pct) × contracts × btc_price

  Ejemplo con BTC $74,085, strike $69,000, contracts=0.1:
    OTM_pct = (74,085 - 69,000) / 74,085 = 0.0686 (6.86%)
    margin = max(0.10, 0.15 - 0.0686) × 0.1 × 74,085
             = max(0.10, 0.0814) × 7,408
             = 0.10 × 7,408 = $740.85

═══════════════════════════════════════════════════════════════════════════════
CHANGELOG:

  2026-04-14  v1.0 — Versión inicial. PUTs semanales BTC. Paper mode.
                     Filtros: IV rank, DTE, delta, spread, max positions.
                     Stop 2× prima y profit lock 80%.
"""

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, date
from typing import Optional

import requests
from loguru import logger


# ── Constantes de estrategia ──────────────────────────────────────────────────

DERIBIT_BASE = "https://www.deribit.com/api/v2"

# Filtros de entrada
MIN_IV_RANK = 20.0           # IV Rank mínimo para vender (%)
MIN_DTE = 3                   # Días hasta expiración mínimos
MAX_DTE = 21                  # Días hasta expiración máximos
TARGET_DTE_MIN = 5            # DTE óptimo mínimo (preferencia)
TARGET_DTE_MAX = 10           # DTE óptimo máximo (preferencia)
MAX_DELTA_ABS = 0.20          # Delta absoluto máximo (-0.20 = 20% prob ITM)
TARGET_DELTA_MIN = -0.15      # Delta óptimo mínimo
TARGET_DELTA_MAX = -0.05      # Delta óptimo máximo
MIN_OTM_PCT = 0.04            # Strike mínimo 4% OTM del precio actual
MAX_OTM_PCT = 0.12            # Strike máximo 12% OTM
MAX_SPREAD_PCT = 0.25         # Spread máximo como % del mark price
MAX_OPEN_POSITIONS = 3        # Posiciones simultáneas máximas
CONTRACT_SIZE = 0.1           # Tamaño mínimo en BTC (está fijo en Deribit)

# Gestión de riesgo
STOP_LOSS_MULTIPLIER = 2.0    # Stop a 2× la prima cobrada
PROFIT_LOCK_PCT = 0.80        # Cerrar cuando la prima cae al 20% del original (ganemos 80%)

# Máximo capital comprometido en margen (% del balance total de la sesión)
MAX_MARGIN_USAGE_PCT = 0.70   # Máximo 70% del balance como margen activo


@dataclass
class OptionSignal:
    """Resultado del análisis de un instrumento PUT de Deribit."""

    # Instrumento
    instrument_name: str
    underlying: str = 'BTC'
    option_type: str = 'PUT'
    strike: float = 0.0
    expiration_date: date = None
    dte: int = 0

    # Decisión
    approved: bool = False
    reason: str = ''

    # Datos de mercado
    btc_price: float = 0.0
    bid_btc: float = 0.0
    ask_btc: float = 0.0
    mark_btc: float = 0.0
    iv_pct: float = 0.0
    iv_rank: float = 0.0
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    spread_pct: float = 0.0
    otm_pct: float = 0.0

    # Sizing
    contracts: float = CONTRACT_SIZE
    entry_premium_usd: float = 0.0
    entry_premium_btc: float = 0.0
    margin_required_usd: float = 0.0

    # Para el stop y profit lock
    stop_price_btc: float = 0.0       # recomprar si mark supera esto
    profit_lock_price_btc: float = 0.0  # cerrar si mark cae a esto

    # Contexto
    iv_rank_signal: str = ''
    strategy_reasoning: str = ''
    market_conditions: str = '{}'


class ThetaFarmingStrategy:
    """
    Motor de decisión para Theta Farming en Deribit.

    Selecciona el PUT semanal de BTC más adecuado para vender
    en función de condiciones de mercado y filtros de riesgo.
    """

    def __init__(self):
        self._iv_rank_cache: Optional[float] = None
        self._iv_rank_cache_time: float = 0.0
        self._iv_rank_ttl = 3600.0  # 1 hora

    # ── Punto de entrada principal ────────────────────────────────────────────

    def evaluate(
        self,
        open_instruments: set[str],
        session_balance: float,
        margin_in_use: float,
    ) -> Optional[OptionSignal]:
        """
        Busca el mejor PUT de BTC para vender ahora mismo.

        Args:
            open_instruments: set de instrument_name ya abiertos en la sesión
            session_balance: balance total disponible de la sesión (USD)
            margin_in_use: margen actual comprometido en posiciones abiertas (USD)

        Returns:
            OptionSignal con approved=True si hay una oportunidad válida,
            None si no hay nada que operar ahora.
        """
        # Cuántos contratos ya tenemos abiertos
        open_count = len(open_instruments)
        if open_count >= MAX_OPEN_POSITIONS:
            logger.info(f'THETA: max posiciones abiertas ({open_count}/{MAX_OPEN_POSITIONS}) — skip')
            return None

        # Verificar que el margen disponible es suficiente para una posición más
        margin_available = session_balance - margin_in_use
        min_margin_needed = session_balance * 0.05  # al menos 5% del balance como margen mínimo
        if margin_available < min_margin_needed:
            logger.info(f'THETA: margen insuficiente ({margin_available:.0f} USD < {min_margin_needed:.0f}) — skip')
            return None

        # 1. Obtener precio BTC y IV Rank
        btc_price = self._get_btc_index_price()
        if btc_price is None:
            logger.warning('THETA: no se pudo obtener BTC price')
            return None

        iv_rank = self._get_iv_rank()
        if iv_rank is None:
            logger.warning('THETA: no se pudo calcular IV Rank')
            return None

        # Filtro 1: IV Rank mínimo
        if iv_rank < MIN_IV_RANK:
            logger.info(f'THETA: IV Rank {iv_rank:.0f}% < {MIN_IV_RANK}% — prima muy baja, no es buen momento')
            return OptionSignal(
                instrument_name='',
                approved=False,
                reason=f'IV_RANK_LOW:{iv_rank:.0f}%<{MIN_IV_RANK}%',
                btc_price=btc_price,
                iv_rank=iv_rank,
            )

        iv_rank_signal = 'HIGH' if iv_rank >= 50 else ('MEDIUM' if iv_rank >= 30 else 'LOW')
        logger.info(f'THETA: BTC=${btc_price:,.0f} | IV Rank={iv_rank:.0f}% ({iv_rank_signal})')

        # 2. Listar PUTs disponibles
        puts = self._fetch_btc_puts()
        if not puts:
            logger.warning('THETA: no se pudieron obtener instrumentos BTC PUT')
            return None

        # 3. Filtrar por DTE y strike range
        now = datetime.now(timezone.utc)
        candidates = []
        for put in puts:
            exp_ts = put.get('expiration_timestamp', 0)
            exp_dt = datetime.fromtimestamp(exp_ts / 1000, tz=timezone.utc)
            dte = max(0, (exp_dt - now).days)
            strike = float(put.get('strike', 0))

            if dte < MIN_DTE or dte > MAX_DTE:
                continue
            if strike <= 0 or btc_price <= 0:
                continue

            otm_pct = (btc_price - strike) / btc_price
            if otm_pct < MIN_OTM_PCT or otm_pct > MAX_OTM_PCT:
                continue

            instrument_name = put['instrument_name']
            if instrument_name in open_instruments:
                continue  # ya tenemos esta posición abierta

            candidates.append({
                'instrument_name': instrument_name,
                'strike': strike,
                'exp_dt': exp_dt,
                'dte': dte,
                'otm_pct': otm_pct,
            })

        if not candidates:
            logger.info('THETA: sin candidatos en rango DTE/OTM')
            return None

        # 4. Pre-score rápido de prima estimada / margen para ordenar candidatos
        # sin llamar a la API todavía. Usamos prima_estimada = IV_actual * sqrt(DTE/365)
        # como proxy del valor temporal. Ordenamos por rendimiento esperado (prima/margen).
        current_iv_approx = iv_rank / 100.0 * 0.60 + 0.20  # estimación burda de IV actual
        for c in candidates:
            otm = c['otm_pct']
            dte = c['dte']
            strike = c['strike']
            # Valor temporal estimado (Black-Scholes simplificado: prima ≈ S × IV × sqrt(T))
            est_premium_usd = btc_price * current_iv_approx * (dte / 365) ** 0.5 * 0.4  # factor atm→otm
            est_margin_usd  = max(0.10, 0.15 - otm) * CONTRACT_SIZE * btc_price
            c['est_yield'] = est_premium_usd / est_margin_usd if est_margin_usd > 0 else 0
            c['in_target_dte'] = TARGET_DTE_MIN <= dte <= TARGET_DTE_MAX

        # Prioridad 1: DTE en rango óptimo
        # Prioridad 2: mayor rendimiento estimado prima/margen (descendente)
        candidates.sort(key=lambda c: (
            0 if c['in_target_dte'] else 1,
            -c['est_yield'],
        ))

        # 5. Evaluar cada candidato hasta encontrar uno aprobado
        for candidate in candidates[:10]:  # máximo 10 intentos para no saturar la API
            signal = self._evaluate_instrument(
                candidate, btc_price, iv_rank, iv_rank_signal,
                margin_available, session_balance
            )
            if signal and signal.approved:
                return signal
            # Pequeña pausa para no saturar el rate limit de Deribit
            time.sleep(0.3)

        logger.info('THETA: ningún candidato pasó todos los filtros')
        return None

    # ── Evaluación de instrumento individual ─────────────────────────────────

    def _evaluate_instrument(
        self,
        candidate: dict,
        btc_price: float,
        iv_rank: float,
        iv_rank_signal: str,
        margin_available: float,
        session_balance: float,
    ) -> Optional[OptionSignal]:
        instrument_name = candidate['instrument_name']
        strike = candidate['strike']
        dte = candidate['dte']
        otm_pct = candidate['otm_pct']
        exp_dt = candidate['exp_dt']

        # Obtener datos del orderbook
        ticker = self._get_ticker(instrument_name)
        if ticker is None:
            return None

        bid_btc = float(ticker.get('best_bid_price', 0) or 0)
        ask_btc = float(ticker.get('best_ask_price', 0) or 0)
        mark_btc = float(ticker.get('mark_price', 0) or 0)
        iv_pct = float(ticker.get('mark_iv', 0) or 0)
        greeks = ticker.get('greeks', {}) or {}
        delta = float(greeks.get('delta', 0) or 0)
        gamma = float(greeks.get('gamma', 0) or 0)
        theta = float(greeks.get('theta', 0) or 0)
        vega = float(greeks.get('vega', 0) or 0)

        # Filtro 2: liquidez (spread)
        if mark_btc <= 0:
            return None
        spread_pct = (ask_btc - bid_btc) / mark_btc if mark_btc > 0 else 999.0
        if spread_pct > MAX_SPREAD_PCT:
            logger.debug(f'THETA: {instrument_name} spread {spread_pct:.0%} > {MAX_SPREAD_PCT:.0%} — skip')
            return None

        # Filtro 3: delta (probabilidad de ser ejercida)
        if delta == 0 and mark_btc > 0:
            # Delta no disponible: estimación rough por OTM
            delta = -0.10 if otm_pct > 0.07 else -0.20
        if abs(delta) > MAX_DELTA_ABS:
            logger.debug(f'THETA: {instrument_name} delta={delta:.3f} demasiado alto — skip')
            return None

        # Filtro 4: prima mínima $5 para cubrir fees
        # Paper: usar mark price (midpoint) — refleja precio real de una limit order.
        # Live: usar bid (precio garantizado de ejecución inmediata).
        # El bid puede ser 15-30% menor que mark en opciones poco líquidas.
        entry_premium_btc = mark_btc  # paper: midpoint como proxy de limit order al mark
        entry_premium_usd = entry_premium_btc * btc_price
        if entry_premium_usd < 5.0:
            logger.debug(f'THETA: {instrument_name} prima ${entry_premium_usd:.1f} < $5 — skip')
            return None

        # Filtro 5: margen requerido vs margen disponible
        margin_usd = self._calculate_margin(strike, btc_price, CONTRACT_SIZE, otm_pct)
        if margin_usd > margin_available:
            logger.debug(f'THETA: {instrument_name} margen ${margin_usd:.0f} > disponible ${margin_available:.0f} — skip')
            return None

        # Filtro 6: no usar más del MAX del balance total en un solo contrato
        if margin_usd > session_balance * MAX_MARGIN_USAGE_PCT:
            logger.debug(f'THETA: {instrument_name} margen excede {MAX_MARGIN_USAGE_PCT:.0%} del balance — skip')
            return None

        # ── Todo OK — construir señal aprobada ──
        stop_price_btc = entry_premium_btc * STOP_LOSS_MULTIPLIER
        profit_lock_price_btc = entry_premium_btc * (1 - PROFIT_LOCK_PCT)

        reasoning = (
            f'PUT {instrument_name} | DTE={dte} | strike=${strike:,.0f} '
            f'({otm_pct*100:.1f}% OTM) | delta={delta:.3f} | '
            f'IV={iv_pct:.0f}% | IV_Rank={iv_rank:.0f}% ({iv_rank_signal}) | '
            f'prima=${entry_premium_usd:.1f} | margen=${margin_usd:.0f} | '
            f'stop=${stop_price_btc:.5f}BTC | lock80%=${profit_lock_price_btc:.5f}BTC'
        )

        market_conditions = json.dumps({
            'btc_price': btc_price,
            'iv_rank': iv_rank,
            'iv_pct': iv_pct,
            'dte': dte,
            'otm_pct': round(otm_pct, 4),
            'delta': delta,
            'spread_pct': round(spread_pct, 3),
        })

        return OptionSignal(
            instrument_name=instrument_name,
            underlying='BTC',
            option_type='PUT',
            strike=strike,
            expiration_date=exp_dt.date(),
            dte=dte,
            approved=True,
            reason='OK',
            btc_price=btc_price,
            bid_btc=bid_btc,
            ask_btc=ask_btc,
            mark_btc=mark_btc,
            iv_pct=iv_pct,
            iv_rank=iv_rank,
            delta=delta,
            gamma=gamma,
            theta=theta,
            vega=vega,
            spread_pct=spread_pct,
            otm_pct=otm_pct,
            contracts=CONTRACT_SIZE,
            entry_premium_usd=entry_premium_usd,
            entry_premium_btc=entry_premium_btc,
            margin_required_usd=margin_usd,
            stop_price_btc=stop_price_btc,
            profit_lock_price_btc=profit_lock_price_btc,
            iv_rank_signal=iv_rank_signal,
            strategy_reasoning=reasoning,
            market_conditions=market_conditions,
        )

    # ── Monitor de posición abierta ───────────────────────────────────────────

    def should_close_position(
        self,
        instrument_name: str,
        entry_premium_btc: float,
        btc_price: float,
    ) -> Optional[str]:
        """
        Evalúa si una posición abierta debe cerrarse ahora.

        Returns:
            'STOP_LOSS_2X' si la prima subió 2× (perdemos)
            'PROFIT_LOCK'  si la prima cayó 80% (aseguramos ganancia)
            None           si la posición debe mantenerse
        """
        ticker = self._get_ticker(instrument_name)
        if ticker is None:
            return None

        current_mark = float(ticker.get('mark_price', 0) or 0)
        if current_mark <= 0:
            return None

        stop_level = entry_premium_btc * STOP_LOSS_MULTIPLIER
        lock_level = entry_premium_btc * (1 - PROFIT_LOCK_PCT)

        if current_mark >= stop_level:
            current_usd = current_mark * btc_price
            loss_usd = (current_mark - entry_premium_btc) * btc_price
            logger.warning(
                f'THETA STOP: {instrument_name} mark={current_mark:.5f}BTC (${current_usd:.0f}) '
                f'>= stop={stop_level:.5f}BTC | pérdida ~${loss_usd:.0f}'
            )
            return 'STOP_LOSS_2X'

        if current_mark <= lock_level and lock_level > 0:
            gain_pct = (entry_premium_btc - current_mark) / entry_premium_btc * 100
            logger.info(
                f'THETA PROFIT LOCK: {instrument_name} mark={current_mark:.5f}BTC '
                f'<= lock={lock_level:.5f}BTC | ganancia {gain_pct:.0f}%'
            )
            return 'PROFIT_LOCK'

        return None

    def get_current_mark_price(self, instrument_name: str) -> Optional[float]:
        """Retorna el mark price actual en BTC de un instrumento."""
        ticker = self._get_ticker(instrument_name)
        if ticker is None:
            return None
        return float(ticker.get('mark_price', 0) or 0) or None

    # ── API Deribit (pública) ─────────────────────────────────────────────────

    def _deribit_get(self, method: str, params: dict = None) -> Optional[dict]:
        try:
            url = f"{DERIBIT_BASE}/public/{method}"
            resp = requests.get(url, params=params or {}, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if data.get('error'):
                logger.warning(f'Deribit API error [{method}]: {data["error"]}')
                return None
            return data.get('result')
        except Exception as e:
            logger.warning(f'Deribit API call failed [{method}]: {e}')
            return None

    def _get_btc_index_price(self) -> Optional[float]:
        result = self._deribit_get('get_index_price', {'index_name': 'btc_usd'})
        if result:
            return float(result.get('index_price', 0)) or None
        return None

    def _get_iv_rank(self) -> Optional[float]:
        """IV Rank calculado como percentil del IV actual en los últimos 30 días."""
        now = time.time()
        if self._iv_rank_cache is not None and (now - self._iv_rank_cache_time) < self._iv_rank_ttl:
            return self._iv_rank_cache

        result = self._deribit_get('get_historical_volatility', {'currency': 'BTC'})
        if not result or len(result) < 5:
            return None

        try:
            # 252 días (1 año de trading) — estándar del sector para IV Rank.
            # Con solo 30d, una semana volátil infla artificialmente el rank.
            ivs = [float(h[1]) for h in result[-252:]]
            current_iv = ivs[-1]
            iv_min = min(ivs)
            iv_max = max(ivs)
            iv_rank = (current_iv - iv_min) / (iv_max - iv_min) * 100 if iv_max > iv_min else 50.0
            self._iv_rank_cache = iv_rank
            self._iv_rank_cache_time = now
            logger.debug(f'THETA IV Rank: {iv_rank:.1f}% (periodo={len(ivs)}d, min={iv_min:.1f}%, max={iv_max:.1f}%, cur={current_iv:.1f}%)')
            return iv_rank
        except Exception as e:
            logger.warning(f'Error calculando IV Rank: {e}')
            return None

    def _fetch_btc_puts(self) -> list[dict]:
        result = self._deribit_get('get_instruments', {
            'currency': 'BTC',
            'kind': 'option',
            'expired': 'false',
        })
        if not result:
            return []
        return [i for i in result if i.get('instrument_name', '').endswith('-P')]

    def _get_ticker(self, instrument_name: str) -> Optional[dict]:
        return self._deribit_get('get_order_book', {
            'instrument_name': instrument_name,
            'depth': 1,
        })

    # ── Cálculo de margen (Deribit portfolio margin) ─────────────────────────

    @staticmethod
    def _calculate_margin(strike: float, btc_price: float, contracts: float, otm_pct: float) -> float:
        """
        Margen inicial estimado para un PUT corto en Deribit.

        Fórmula simplificada del régimen de margen de Deribit:
          margin_rate = max(0.10, 0.15 - OTM_pct)
          margin = margin_rate × contracts × btc_price

        Referencia: https://www.deribit.com/kb/deribit-portfolio-margin
        """
        margin_rate = max(0.10, 0.15 - otm_pct)
        return margin_rate * contracts * btc_price
