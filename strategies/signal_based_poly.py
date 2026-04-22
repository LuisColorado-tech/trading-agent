"""
signal_based_poly.py — Motor de decisión para Polymarket basado en señales técnicas propias.

Reemplaza prediction.py (que usaba LLM). Cero costo de API, cero alucinaciones.
Usa señales macro 1h/4h de la tabla `signals` + MarketRegime para tomar decisiones.

══════════════════════════════════════════════════════════════════════════════
CHANGELOG — 2026-04-14 (fixes post-diagnóstico SESSION_003)
══════════════════════════════════════════════════════════════════════════════

FIX 1 — Deduplicación de señales DB (CRÍTICO)
  PROBLEMA: el loop de trading insertaba el mismo EMA cross cada 30s → hasta 74
            duplicados del mismo precio_at_signal en una hora. Esto inflaba
            artificialmente el conteo de BUYs en la ventana de 10 min y forzaba
            la dirección a 'UP' independientemente del mercado real.
  SOLUCIÓN: _get_btc_direction_from_db usa DISTINCT ON (timeframe) → solo la
            señal MÁS RECIENTE por timeframe. Solo timeframes 1h y 4h (macro).

FIX 2 — Eliminar dead code regime_confirms (BUG)
  PROBLEMA: existían DOS bloques de `regime_confirms = False` consecutivos.
            El primero (que manejaba bien el path DB con signal_source) era
            inmediatamente sobreescrito por el segundo. El código que se
            ejecutaba realmente usaba momentum=0.0 → bloqueaba trades válidos.
  SOLUCIÓN: eliminado el bloque duplicado. Un solo bloque limpio.

FIX 3 — Filtro de factibilidad de precio objetivo (PREVIENE PÉRDIDAS)
  PROBLEMA: se entraba en mercados donde el precio objetivo era inalcanzable
            en el tiempo disponible. Ej: BTC@74,246, target $76,000 con 1 día
            restante → gap=2.4% cuando BTC típicamente mueve 2%/día máximo.
            Resultado: trade perdedor -$20 (-54%) en SESSION_003.
  SOLUCIÓN: _extract_price_target() extrae el precio objetivo de la pregunta.
            _get_current_price_from_db() obtiene precio actual del activo.
            Si gap% > (días_restantes × 2%), el mercado se descarta.
            Nuevos métodos: _detect_asset, _extract_price_target, _get_current_price_from_db.

FIX 4 — estimated_prob calibrado (KELLY SIZING CORRECTO)
  PROBLEMA: estimated_prob era 1.0 cuando side=YES y 0.0 cuando side=NO.
            El Kelly criterion recibía probabilidades imposibles (1.0 o 0.0)
            que producían sizing incorrecto.
  SOLUCIÓN: estimated_prob = min(0.90, entry_price + edge). Refleja la
            convicción real de la señal de forma coherente con el edge calculado.

FIX 5 — Reasoning descriptivo
  PROBLEMA: el log mostraba "BTC[DB] +0.000% → UP" porque momentum se
            inicializaba en 0.0 cuando la señal venía de DB (camino correcto).
            Era imposible saber qué señales macro habían votado.
  SOLUCIÓN: _get_btc_direction_from_db retorna (direction, description) donde
            description = "macro BUY=N SELL=M". El log ahora muestra
            "BTC[DB:macro BUY=1 SELL=0] → UP" con el conteo real de timeframes.

══════════════════════════════════════════════════════════════════════════════
ARQUITECTURA DE SEÑALES
══════════════════════════════════════════════════════════════════════════════

Fuente primaria (DB):
  SELECT DISTINCT ON (timeframe) ... WHERE timeframe IN ('1h','4h')
  Una señal por timeframe → mayoría simple determina UP/DOWN.
  Solo señales de las últimas 4 horas (evita información stale).

Fuente fallback (CCXT):
  fetch_ohlcv BTC/USDT 1m, retorno de 5 velas → threshold ±0.15%.
  Solo se usa si no hay señales 1h/4h recientes en DB.
  En RANGE/CHOPPY con señal CCXT: requiere 2× el threshold.

Filtro de factibilidad:
  gap_pct_al_objetivo > días_restantes × 2%/día → SKIP.
  Evita apostar en mercados donde el precio físicamente no puede llegar a tiempo.

Zona válida de precio YES: 0.20 – 0.80 (descuento calibrable por el mercado).
Edge mínimo: 10% (configurado en exchange_config.yaml → polymarket.risk.min_edge_pct).
"""
import os
import re
import sys
from datetime import datetime, timezone

import ccxt
import yaml
from loguru import logger
from sqlalchemy import create_engine, text

sys.path.insert(0, '/opt/trading')

with open('/opt/trading/config/exchange_config.yaml') as f:
    _CFG = yaml.safe_load(f).get('polymarket', {})

_RISK = _CFG.get('risk', {})
MIN_EDGE = _RISK.get('min_edge_pct', 10.0) / 100.0          # 0.10
MIN_PRICE_YES = _CFG.get('market_filters', {}).get('min_price_yes', 0.20)
MAX_PRICE_YES = _CFG.get('market_filters', {}).get('max_price_yes', 0.80)

# ── Patrones de clasificación de evento ─────────────────────────────────────
# DOWN_EVENT: el mercado pregunta si BTC/ETH va a caer
_DOWN_PATTERNS = [
    r'\bdrop\b', r'\bfall\b', r'\bdip\b', r'\bbelow\b', r'\bunder\b',
    r'\bcrash\b', r'\bdecline\b', r'\blose\b', r'\bsell.?off\b',
    r'\bbear\b', r'\bdown\b', r'\blow(er)?\b',
]
# UP_EVENT: el mercado pregunta si BTC/ETH va a subir
_UP_PATTERNS = [
    r'\breach\b', r'\babove\b', r'\bover\b', r'\bgain\b', r'\brise\b',
    r'\bbull\b', r'\brally\b', r'\bsurge\b', r'\bhit\b', r'\bbreak\b',
    r'\bup\b', r'\bhigh(er)?\b',
]

_DOWN_RE = re.compile('|'.join(_DOWN_PATTERNS), re.IGNORECASE)
_UP_RE = re.compile('|'.join(_UP_PATTERNS), re.IGNORECASE)

# ── Momentum BTC via CCXT ────────────────────────────────────────────────────
_BTC_EXCHANGE_ID = 'kraken'
_BTC_FALLBACK_ID = 'okx'
_BTC_PAIR = 'BTC/USDT'
_MOMENTUM_THRESHOLD = 0.0015   # 0.15% en 5 velas de 1m (fallback CCXT)


def _db_url() -> str:
    from dotenv import load_dotenv
    load_dotenv('/opt/trading/config/.env')
    return (
        f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
        f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT', '5432')}"
        f"/{os.getenv('POSTGRES_DB')}"
    )


class SignalBasedPolyStrategy:
    """Genera señales de trading Polymarket a partir de señales técnicas propias."""

    NAME = 'SIGNAL_BASED'

    def __init__(self):
        self._exchange = None
        self._fallback = None
        try:
            self._engine = create_engine(_db_url())
        except Exception:
            self._engine = None

    # ── Señales desde DB ─────────────────────────────────────────────────────

    def _get_btc_direction_from_db(self) -> tuple[str | None, str]:
        """Lee señales macro (1h/4h) deduplicadas para dirección estructural de BTC.

        Usa DISTINCT ON (timeframe) para obtener UNA señal por timeframe
        (la más reciente), evitando que duplicados del loop inflen el conteo.
        Solo usa 1h/4h: señales relevantes para mercados que resuelven en días/semanas.

        Returns:
            (direction, description)
            direction: 'UP' | 'DOWN' | None si no hay mayoría clara
        """
        if self._engine is None:
            return None, 'NO_ENGINE'
        try:
            with self._engine.connect() as conn:
                rows = conn.execute(text("""
                    SELECT direction, timeframe
                    FROM (
                        SELECT DISTINCT ON (timeframe) timeframe, direction, timestamp
                        FROM signals
                        WHERE asset = 'BTC'
                          AND timeframe IN ('1h', '4h')
                          AND timestamp > now() - interval '4 hours'
                        ORDER BY timeframe, timestamp DESC
                    ) latest
                    WHERE direction IN ('BUY', 'SELL')
                """)).fetchall()
        except Exception as e:
            logger.debug(f'SIGNAL_POLY: DB signals error: {e}')
            return None, 'DB_ERROR'

        if not rows:
            return None, 'NO_MACRO_SIGNALS'

        buys = sum(1 for r in rows if r[0] == 'BUY')
        sells = sum(1 for r in rows if r[0] == 'SELL')
        desc = f'macro BUY={buys} SELL={sells}'

        if buys > sells:
            return 'UP', desc
        if sells > buys:
            return 'DOWN', desc
        return None, f'{desc} CONFLICT'

    # ── Exchange ─────────────────────────────────────────────────────────────

    def _get_btc_momentum(self) -> float | None:
        """Retorna el retorno % de BTC en las últimas 5 velas de 1m.

        Positivo → momentum alcista. Negativo → bajista.
        Returns None si no se puede obtener el dato.
        """
        for ex_id in (_BTC_EXCHANGE_ID, _BTC_FALLBACK_ID):
            try:
                if ex_id == _BTC_EXCHANGE_ID:
                    if self._exchange is None:
                        self._exchange = getattr(ccxt, ex_id)({'enableRateLimit': True})
                    ex = self._exchange
                else:
                    if self._fallback is None:
                        self._fallback = getattr(ccxt, ex_id)({'enableRateLimit': True})
                    ex = self._fallback

                candles = ex.fetch_ohlcv(_BTC_PAIR, '1m', limit=10)
                if candles and len(candles) >= 5:
                    closes = [float(c[4]) for c in candles]
                    return (closes[-1] - closes[-5]) / closes[-5]
            except Exception as e:
                logger.warning(f'SIGNAL_POLY: BTC OHLCV error ({ex_id}): {e}')
        return None

    # ── Clasificación del evento ─────────────────────────────────────────────

    @staticmethod
    def _classify_event(question: str) -> str:
        """Clasifica la pregunta como DOWN_EVENT, UP_EVENT o AMBIGUOUS."""
        q = question.lower()
        has_down = bool(_DOWN_RE.search(q))
        has_up = bool(_UP_RE.search(q))

        if has_down and not has_up:
            return 'DOWN_EVENT'
        if has_up and not has_down:
            return 'UP_EVENT'
        # Ambos o ninguno: necesitamos más contexto
        return 'AMBIGUOUS'

    # ── Factibilidad de precio objetivo ──────────────────────────────────────

    @staticmethod
    def _detect_asset(question: str) -> str:
        """Detecta el activo principal de la pregunta: 'BTC' | 'ETH' | 'UNKNOWN'."""
        q = question.lower()
        if 'bitcoin' in q or ' btc' in q or q.startswith('btc'):
            return 'BTC'
        if 'ethereum' in q or ' eth' in q or q.startswith('eth'):
            return 'ETH'
        return 'UNKNOWN'

    @staticmethod
    def _extract_price_target(question: str) -> float | None:
        """Extrae el precio objetivo en USD de la pregunta.

        Soporta: $80,000 | $80k | $80K | 80000
        """
        patterns = [
            r'\$(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*[kK]\b',  # $80k $80K
            r'\$(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\b',           # $80,000 $80000
        ]
        for pattern in patterns:
            m = re.search(pattern, question)
            if m:
                val_str = m.group(1).replace(',', '')
                try:
                    val = float(val_str)
                    if 'k' in m.group(0).lower():
                        val *= 1000
                    if 100 <= val <= 10_000_000:   # rango razonable para crypto
                        return val
                except ValueError:
                    continue
        return None

    def _get_current_price_from_db(self, asset: str) -> float | None:
        """Obtiene el precio más reciente del activo desde la tabla signals."""
        if self._engine is None:
            return None
        try:
            with self._engine.connect() as conn:
                row = conn.execute(text("""
                    SELECT price_at_signal FROM signals
                    WHERE asset = :asset
                    ORDER BY timestamp DESC LIMIT 1
                """), {'asset': asset}).fetchone()
            return float(row[0]) if row else None
        except Exception:
            return None

    # ── Evaluación principal ─────────────────────────────────────────────────

    def evaluate(self, market: dict, market_regime: str = 'UNKNOWN') -> dict:
        """Evalúa un mercado y retorna señal si hay edge técnico suficiente.

        Args:
            market: dict de PolymarketFeed con question, price_yes, price_no, etc.
            market_regime: string del régimen actual (TREND_DOWN, TREND_UP, RANGE, CHOPPY)

        Returns:
            dict con opportunity=True/False y detalles de la señal.
        """
        question = market.get('question', '')
        price_yes = float(market.get('price_yes', 0.5))
        price_no = float(market.get('price_no', 0.5))

        # Filtro de precio (0.20–0.80) — doble check por si feed no filtró
        if price_yes < MIN_PRICE_YES or price_yes > MAX_PRICE_YES:
            return {'opportunity': False, 'reason': f'PRICE_OUT_OF_RANGE:{price_yes:.3f}'}

        # Clasificar evento
        event_type = self._classify_event(question)
        if event_type == 'AMBIGUOUS':
            return {'opportunity': False, 'reason': 'AMBIGUOUS_EVENT'}

        # Verificar factibilidad del precio objetivo vs precio actual del activo
        price_asset = self._detect_asset(question)
        target_price = self._extract_price_target(question)
        if target_price and price_asset != 'UNKNOWN':
            current_price = self._get_current_price_from_db(price_asset)
            if current_price:
                gap_pct = abs(target_price - current_price) / current_price
                days_remaining = 30.0
                try:
                    end_date = market.get('end_date')
                    if end_date:
                        if isinstance(end_date, str):
                            end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                        else:
                            end_dt = end_date
                        days_remaining = max(1.0, (end_dt - datetime.now(timezone.utc)).total_seconds() / 86400)
                except Exception:
                    pass
                # BTC/ETH difícilmente mueve más de 2%/día de forma sostenida
                max_feasible_gap = days_remaining * 0.02
                if gap_pct > max_feasible_gap:
                    return {
                        'opportunity': False,
                        'reason': (
                            f'PRICE_TOO_FAR:{price_asset}@{current_price:.0f}'
                            f' target={target_price:.0f} gap={gap_pct:.1%}'
                            f' max={max_feasible_gap:.1%} ({days_remaining:.0f}d)'
                        ),
                    }

        # Obtener dirección BTC: DB signals macro 1h/4h (primario) → CCXT (fallback)
        momentum = 0.0
        btc_direction, db_desc = self._get_btc_direction_from_db()
        signal_source = 'DB'

        if btc_direction is None:
            # Fallback a CCXT
            momentum = self._get_btc_momentum()
            signal_source = 'CCXT'
            if momentum is None:
                return {'opportunity': False, 'reason': 'NO_BTC_DATA'}
            if momentum >= _MOMENTUM_THRESHOLD:
                btc_direction = 'UP'
            elif momentum <= -_MOMENTUM_THRESHOLD:
                btc_direction = 'DOWN'
            else:
                return {
                    'opportunity': False,
                    'reason': f'NO_MOMENTUM:{momentum:+.4f} (min±{_MOMENTUM_THRESHOLD:.4f})',
                }

        # Confirmar señal con régimen de mercado
        # TREND_UP/DOWN confirma la dirección; RANGE/CHOPPY:
        #   - señal DB macro 1h/4h es suficiente (ya es estructural)
        #   - señal CCXT requiere momentum fuerte (2× threshold)
        regime_confirms = False
        if 'DOWN' in market_regime and btc_direction == 'DOWN':
            regime_confirms = True
        elif 'UP' in market_regime and btc_direction == 'UP':
            regime_confirms = True
        elif market_regime in ('RANGE', 'CHOPPY', 'UNKNOWN'):
            if signal_source == 'DB':
                # Señal macro 1h/4h es estructuralmente válida aunque el régimen sea neutro
                regime_confirms = True
            elif abs(momentum) >= _MOMENTUM_THRESHOLD * 2:
                regime_confirms = True
            else:
                return {
                    'opportunity': False,
                    'reason': f'WEAK_MOMENTUM_NO_REGIME:{momentum:+.4f}',
                }

        if not regime_confirms:
            return {
                'opportunity': False,
                'reason': f'REGIME_CONFLICT: regime={market_regime} btc={btc_direction}',
            }

        # Determinar side: ¿el evento coincide con nuestra señal?
        if event_type == 'DOWN_EVENT' and btc_direction == 'DOWN':
            side = 'YES'   # El evento bajista VA a ocurrir
            entry_price = price_yes
            edge = entry_price - price_yes + (0.50 - price_yes)
            # Edge real: cuánto está descontando el mercado vs nuestra señal
            edge = 0.50 - price_yes if price_yes < 0.50 else price_yes - 0.50
        elif event_type == 'UP_EVENT' and btc_direction == 'UP':
            side = 'YES'   # El evento alcista VA a ocurrir
            entry_price = price_yes
            edge = 0.50 - price_yes if price_yes < 0.50 else price_yes - 0.50
        elif event_type == 'DOWN_EVENT' and btc_direction == 'UP':
            side = 'NO'    # El evento bajista NO va a ocurrir (BTC sube)
            entry_price = price_no
            edge = 0.50 - price_no if price_no < 0.50 else price_no - 0.50
        elif event_type == 'UP_EVENT' and btc_direction == 'DOWN':
            side = 'NO'    # El evento alcista NO va a ocurrir (BTC baja)
            entry_price = price_no
            edge = 0.50 - price_no if price_no < 0.50 else price_no - 0.50
        else:
            return {'opportunity': False, 'reason': 'LOGIC_ERROR'}

        # Edge mínimo
        if edge < MIN_EDGE:
            return {
                'opportunity': False,
                'reason': f'LOW_EDGE:{edge:.3f} (min={MIN_EDGE:.2f})',
            }

        # Probabilidad calibrada: precio de entrada + edge (consistente con Kelly sizing)
        estimated_prob = round(min(0.90, entry_price + edge), 4)

        signal_desc = db_desc if signal_source == 'DB' else f'CCXT {momentum:+.3%}'
        reasoning = (
            f'BTC[{signal_source}:{signal_desc}] → {btc_direction} | '
            f'Regime: {market_regime} | Event: {event_type} | '
            f'Side: {side} @ {entry_price:.3f} | Edge: {edge:.3f} | prob={estimated_prob:.2f}'
        )
        logger.info(f'SIGNAL_POLY OPPORTUNITY: {reasoning} | "{question[:60]}"')

        return {
            'opportunity': True,
            'side': side,
            'edge': edge,
            'entry_price': entry_price,
            'btc_direction': btc_direction,
            'btc_momentum_pct': round(momentum * 100, 4),
            'market_regime': market_regime,
            'event_type': event_type,
            'confidence': 80,
            'reasoning': reasoning,
            'estimated_prob': estimated_prob,
            'market': market,
            'strategy': SignalBasedPolyStrategy.NAME,
        }
