"""
btc_multifeed.py — Feed multi-timeframe para mercados "Bitcoin Up or Down" de Polymarket.

Descubre automáticamente mercados activos en 5 timeframes:
  - 5m:    slug determinístico  btc-updown-5m-{slot_ts}
  - 15m:   slug determinístico  btc-updown-15m-{slot_ts}  (original)
  - 4H:    slug determinístico  btc-updown-4h-{slot_ts}
  - 1H:    scan paginado /markets  (cache 5 min)
  - Daily: scan paginado /markets  (cache 5 min)

Todos los market dicts son compatibles con BtcDirectionFeed (mismos campos)
más tres campos extra: timeframe (str), slot_secs (int), end_ts (int).
"""

import json
import re
import time
from datetime import datetime, timezone

import requests
from loguru import logger


GAMMA_API = 'https://gamma-api.polymarket.com'
CLOB_API  = 'https://clob.polymarket.com'

# ── Configuración por timeframe ───────────────────────────────────────────────

# Assets soportados para mercados no-determinísticos (up-or-down por hora)
# Clave: keyword en la pregunta  →  asset ticker para señales
SCAN_ASSETS: dict[str, str] = {
    'bitcoin':  'BTC',
    'ethereum': 'ETH',
    'solana':   'SOL',
    'xrp':      'XRP',
}

# Determinísticos: tf → (slot_secs, slug_template)  — solo BTC por ahora
DETERMINISTIC_TF: dict[str, tuple[int, str]] = {
    '5m':  (300,   'btc-updown-5m-{}'),
    '15m': (900,   'btc-updown-15m-{}'),
    '4h':  (14400, 'btc-updown-4h-{}'),
}

# Slot en segundos por TF
SLOT_SECS: dict[str, int] = {
    '5m':    300,
    '15m':   900,
    '1h':    3600,
    '4h':    14400,
    'daily': 86400,
}

# Ventanas de entrada: (max_elapsed_secs, min_remaining_secs)
# max_elapsed: cuánto tiempo puede haber pasado desde el inicio del slot
# min_remaining: mínimo de segundos restantes para entrar
ENTRY_WINDOWS: dict[str, tuple[int, int]] = {
    '5m':    (120,   60),    # entrar en los primeros 2m, quedan ≥60s
    '15m':   (600,   60),    # entrar en los primeros 10m, quedan ≥60s
    '1h':    (2700,  120),   # entrar en la primera mitad (45m), quedan ≥2m
    '4h':    (7200,  300),   # entrar en las primeras 2h, quedan ≥5m
    'daily': (21600, 600),   # entrar en las primeras 6h, quedan ≥10m
}


class BtcMultiFeed:
    """Feed multi-timeframe para mercados BTC Up/Down de Polymarket."""

    # Cache de clase para scan no-determinístico
    _scan_cache: list[dict] = []
    _scan_cache_ts: float = 0.0
    SCAN_TTL = 300.0  # 5 minutos entre scans

    def __init__(self, config: dict):
        poly_cfg = config.get('polymarket', {})
        self.gamma_api = poly_cfg.get('gamma_api', GAMMA_API)
        self.clob_api  = poly_cfg.get('clob_api', CLOB_API)

        self._session = requests.Session()
        self._session.headers.update({'User-Agent': 'btc-direction-agent/2.0'})

    # ── CLOB midpoint ────────────────────────────────────────────────────────

    def _get_midpoint(self, token_id: str) -> float:
        """Precio midpoint del CLOB para un token (datos públicos, sin auth)."""
        try:
            resp = self._session.get(
                f'{self.clob_api}/midpoint',
                params={'token_id': token_id},
                timeout=5,
            )
            resp.raise_for_status()
            return float(resp.json().get('mid', 0.5))
        except Exception as e:
            logger.warning(f'MULTIFEED: Error midpoint {token_id[:16]}...: {e}')
            return 0.5

    # ── Construcción del market dict ─────────────────────────────────────────

    def _build_market_dict(
        self,
        slug: str,
        condition_id: str,
        clob_ids: list,
        end_ts: int,
        tf: str,
        accepting: bool = True,
        asset: str = 'BTC',
    ) -> dict | None:
        """Construye el market dict consultando CLOB para precios en tiempo real."""
        if len(clob_ids) < 2:
            return None

        token_up   = str(clob_ids[0]).strip()
        token_down = str(clob_ids[1]).strip()

        price_up   = self._get_midpoint(token_up)
        price_down = self._get_midpoint(token_down)

        now       = time.time()
        slot_secs = SLOT_SECS[tf]
        slot_ts   = end_ts - slot_secs

        return {
            # Campos compatibles con BtcDirectionFeed
            'slot_ts':           slot_ts,
            'slug':              slug,
            'condition_id':      condition_id,
            'token_up':          token_up,
            'token_down':        token_down,
            'price_up':          price_up,
            'price_down':        price_down,
            'end_time':          datetime.fromtimestamp(end_ts, tz=timezone.utc),
            'seconds_remaining': end_ts - now,
            'accepting_orders':  accepting,
            # Campos extra para multi-TF + multi-asset
            'timeframe':         tf,
            'slot_secs':         slot_secs,
            'end_ts':            end_ts,
            'asset':             asset,
        }

    # ── Mercados determinísticos (5m, 15m, 4H) ──────────────────────────────

    def get_deterministic_markets(self) -> list[dict]:
        """
        Obtiene mercados 5m, 15m y 4H via slug determinístico.
        No requiere paginación: slug derivado del timestamp actual.
        """
        now = time.time()
        markets = []

        for tf, (slot_secs, slug_tmpl) in DETERMINISTIC_TF.items():
            slot_ts = int(now) // slot_secs * slot_secs
            end_ts  = slot_ts + slot_secs
            elapsed   = now - slot_ts
            remaining = end_ts - now

            max_elapsed, min_remaining = ENTRY_WINDOWS[tf]
            if elapsed > max_elapsed:
                logger.debug(
                    f'MULTIFEED: {tf} muy avanzado '
                    f'({elapsed:.0f}s > {max_elapsed}s max)'
                )
                continue
            if remaining < min_remaining:
                logger.debug(
                    f'MULTIFEED: {tf} casi terminado '
                    f'({remaining:.0f}s < {min_remaining}s min)'
                )
                continue

            slug = slug_tmpl.format(slot_ts)
            try:
                resp = self._session.get(
                    f'{self.gamma_api}/events',
                    params={'slug': slug},
                    timeout=10,
                )
                resp.raise_for_status()
                events = resp.json()
            except Exception as e:
                logger.warning(f'MULTIFEED: Error fetcheando {slug}: {e}')
                continue

            if not events:
                logger.debug(f'MULTIFEED: {tf} no encontrado aún ({slug})')
                continue

            event       = events[0]
            mkts_raw    = event.get('markets', [])
            if not mkts_raw:
                continue
            m_raw = mkts_raw[0]

            cid = m_raw.get('conditionId', '')
            if not cid:
                continue

            clob_ids_raw = m_raw.get('clobTokenIds', '[]')
            try:
                clob_ids = (
                    json.loads(clob_ids_raw)
                    if isinstance(clob_ids_raw, str)
                    else clob_ids_raw
                )
            except Exception:
                continue

            # Usar endDate del evento si está disponible (más preciso que slot+secs)
            end_date_str = m_raw.get('endDate', '')
            try:
                end_dt = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
                end_ts_actual = int(end_dt.timestamp())
            except Exception:
                end_ts_actual = end_ts

            m = self._build_market_dict(
                slug=event.get('slug', slug),
                condition_id=cid,
                clob_ids=clob_ids,
                end_ts=end_ts_actual,
                tf=tf,
                accepting=m_raw.get('acceptingOrders', True),
                asset='BTC',
            )
            if m:
                markets.append(m)
                logger.info(
                    f'MULTIFEED: BTC {tf.upper():<5s} '
                    f'Up={m["price_up"]:.3f} Down={m["price_down"]:.3f} | '
                    f'rem={m["seconds_remaining"]:.0f}s | slug={slug}'
                )

        return markets

    # ── Mercados horarios deterministicos (1H, todos los assets) ─────────────

    def get_hourly_markets(self) -> list[dict]:
        """
        Obtiene mercados 1H para BTC, ETH, SOL, XRP via slug determinístico.

        Patrón: {asset}-up-or-down-{month}-{day}-{year}-{hour}{ampm}-et
        Ejemplo: ethereum-up-or-down-april-14-2026-1pm-et

        Busca la hora actual + próxima hora (hora en ET para coincidir con Polymarket).
        ET = UTC-4 (EDT, Abril).
        """
        now_utc = datetime.now(timezone.utc)
        now_ts  = time.time()
        markets = []

        # ET offset: UTC-4 en horario de verano (EDT)
        ET_OFFSET = -4

        for hour_offset in range(0, 3):  # hora actual + próximas 2h
            et_hour_raw = (now_utc.hour + ET_OFFSET + hour_offset) % 24
            # Calcular fecha ET (puede cambiar con el offset)
            et_dt = now_utc + __import__('datetime').timedelta(hours=ET_OFFSET + hour_offset)
            month = et_dt.strftime('%B').lower()   # 'april'
            day   = et_dt.day
            year  = et_dt.year

            # Convertir a formato 12h
            h12   = et_hour_raw % 12 or 12
            ampm  = 'pm' if et_hour_raw >= 12 else 'am'

            # end_ts: inicio de la hora ET + 1h (en UTC)
            # La hora ET X pm = (X+4) UTC; la resolución ocurre al final de esa hora
            end_utc_hour = (et_hour_raw + 1 - ET_OFFSET) % 24  # convertir back a UTC + 1h
            # Construir timestamp de resolución
            import math
            end_date_approx = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date_approx = end_date_approx + __import__('datetime').timedelta(
                hours=(et_hour_raw + 1 - ET_OFFSET) % 24 + (
                    24 if (et_hour_raw + 1 - ET_OFFSET) < 0 else 0
                ) + (
                    24 if hour_offset > 0 and (et_hour_raw + 1 - ET_OFFSET) % 24 < now_utc.hour else 0
                ),
            )
            # Aproximación suficiente — el API retorna la fecha exacta
            # Usar end_date del API como fuente de verdad

            for asset_name, asset_ticker in SCAN_ASSETS.items():
                slug = f'{asset_name}-up-or-down-{month}-{day}-{year}-{h12}{ampm}-et'

                try:
                    resp = self._session.get(
                        f'{self.gamma_api}/markets',
                        params={'slug': slug},
                        timeout=8,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as e:
                    logger.debug(f'MULTIFEED: 1H {asset_ticker} {h12}{ampm} error: {e}')
                    continue

                if not data:
                    continue

                m_raw = data[0]
                if not m_raw.get('active', False):
                    continue

                cid = m_raw.get('conditionId', '')
                if not cid:
                    continue

                clob_raw = m_raw.get('clobTokenIds', '[]')
                try:
                    clob_ids = json.loads(clob_raw) if isinstance(clob_raw, str) else clob_raw
                except Exception:
                    continue

                end_str = m_raw.get('endDate', '')
                try:
                    end_dt  = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
                    end_ts  = int(end_dt.timestamp())
                except Exception:
                    continue

                slot_secs = SLOT_SECS['1h']
                slot_ts   = end_ts - slot_secs
                elapsed   = now_ts - slot_ts
                remaining = end_ts - now_ts

                max_elapsed, min_remaining = ENTRY_WINDOWS['1h']
                if elapsed > max_elapsed or remaining < min_remaining:
                    logger.debug(
                        f'MULTIFEED: 1H {asset_ticker} {h12}{ampm} fuera de ventana '
                        f'(e={elapsed:.0f}s r={remaining:.0f}s)'
                    )
                    continue

                m = self._build_market_dict(
                    slug=slug,
                    condition_id=cid,
                    clob_ids=clob_ids,
                    end_ts=end_ts,
                    tf='1h',
                    accepting=m_raw.get('acceptingOrders', True),
                    asset=asset_ticker,
                )
                if m:
                    markets.append(m)
                    logger.info(
                        f'MULTIFEED: {asset_ticker} 1H    '
                        f'Up={m["price_up"]:.3f} Down={m["price_down"]:.3f} | '
                        f'rem={m["seconds_remaining"]:.0f}s | slug={slug}'
                    )

        return markets

    # ── Scan no-determinístico (Daily + ventanas cortas) ─────────────────────

    def _scan_nondeterministic(self) -> list[dict]:
        """
        Scan paginado de /markets para encontrar mercados 1H, Daily y ventanas
        de tiempo corto (5m, 15m, 4H) para BTC, ETH, SOL y XRP.
        Cachea resultados 5 minutos para evitar paginar en cada ciclo (30s).
        """
        now = time.time()
        if now - self._scan_cache_ts < self.SCAN_TTL and self._scan_cache:
            logger.debug('MULTIFEED: usando cache 1H/Daily')
            return self._scan_cache

        found = []

        # Paginar hasta offset 2000 o volumen < $500
        # ETH/SOL/XRP aparecen en offsets 600-1700, XRP cae hasta ~$5k de volumen
        for offset in range(0, 2100, 100):
            try:
                resp = self._session.get(
                    f'{self.gamma_api}/markets',
                    params={
                        'limit': 100, 'offset': offset,
                        'active': True, 'closed': False,
                        'order': 'volume24hr', 'ascending': False,
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                page = resp.json()
            except Exception as e:
                logger.warning(f'MULTIFEED: Error scan offset={offset}: {e}')
                break

            if not page:
                break

            for m_raw in page:
                q    = m_raw.get('question', '').lower()
                slug = m_raw.get('slug', '')

                # Filtro: al menos un asset conocido + 'up or down'
                if 'up or down' not in q:
                    continue
                asset_kw = next(
                    (kw for kw in SCAN_ASSETS if kw in q), None
                )
                if not asset_kw:
                    continue
                asset = SCAN_ASSETS[asset_kw]

                # Excluir determinísticos BTC (ya cubiertos)
                if any(
                    slug.startswith(p)
                    for p in ('btc-updown-15m-', 'btc-updown-5m-', 'btc-updown-4h-')
                ):
                    continue

                tf = self._classify_slug(slug)
                if tf == 'unknown':
                    continue

                parsed = self._parse_scan_market(m_raw, tf, asset=asset)
                if parsed:
                    found.append(parsed)

            # Cortar si el volumen cae de $500
            try:
                last_vol = float(
                    str(
                        page[-1].get('volume24hr') or page[-1].get('volume') or 0
                    ).replace(',', '') or 0
                )
                if last_vol < 500:
                    break
            except Exception:
                break

        self._scan_cache    = found
        self._scan_cache_ts = now
        logger.debug(f'MULTIFEED: scan 1H/Daily/ventanas → {len(found)} mercados')
        return found

    @staticmethod
    def _classify_slug(slug: str) -> str:
        """
        Clasifica un slug como timeframe.

        Patrones:
          Daily: bitcoin-up-or-down-on-april-14-2026
                 solana-up-or-down-on-april-14-2026
          1H:    bitcoin-up-or-down-april-14-2026-1am-et
                 ethereum-up-or-down-april-14-2026-5pm-et
          15m:   bitcoin-up-or-down-april-14-2026-12-45pm-1-00pm-et  (ventana 15 min)
          5m:    bitcoin-up-or-down-april-14-2026-12-50pm-12-55pm-et (ventana 5 min)
          4h:    bitcoin-up-or-down-april-14-2026-12-00pm-4-00pm-et  (ventana 4H)
        """
        s = slug.lower()

        # Daily: patrón {asset}-up-or-down-on-<date>
        if re.search(r'up-or-down-on-', s):
            return 'daily'
        if 'daily' in s:
            return 'daily'

        # Ventanas con rango horario: {H}:{MM}{am|pm}-{H}:{MM}{am|pm}-et
        # o simplificado como {H}-{MM}{am|pm}-{H}-{MM}{am|pm}-et
        window_match = re.search(r'(\d+)-?(\d+)?(am|pm)-?(\d+)-?(\d+)?(am|pm)-et$', s)
        if window_match:
            # Calcular duración aproximada del intervalo
            try:
                start_h = int(window_match.group(1))
                start_m = int(window_match.group(2) or 0)
                end_h   = int(window_match.group(4))
                end_m   = int(window_match.group(5) or 0)
                start_ampm = window_match.group(3)
                end_ampm   = window_match.group(6)
                if start_ampm == 'pm' and start_h < 12: start_h += 12
                if end_ampm   == 'pm' and end_h   < 12: end_h   += 12
                if start_ampm == 'am' and start_h == 12: start_h = 0
                if end_ampm   == 'am' and end_h   == 12: end_h   = 0
                duration_min = (end_h * 60 + end_m) - (start_h * 60 + start_m)
                if duration_min <= 0:
                    duration_min += 24 * 60
                if duration_min <= 10:
                    return '5m'
                if duration_min <= 20:
                    return '15m'
                if duration_min <= 70:
                    return '1h'
                if duration_min <= 255:
                    return '4h'
                return '1h'  # fallback
            except Exception:
                return '1h'

        # 1H puro: termina en {N}am-et / {N}pm-et (sin rango)
        if re.search(r'\d+(am|pm)-et$', s):
            return '1h'

        return 'unknown'

    def _parse_scan_market(self, m_raw: dict, tf: str, asset: str = 'BTC') -> dict | None:
        """
        Parsea un mercado crudo del endpoint /markets con ventana de entrada.
        Retorna None si está fuera de la ventana o le faltan datos.
        """
        cid = m_raw.get('conditionId', '')
        if not cid:
            return None

        clob_ids_raw = m_raw.get('clobTokenIds', '[]')
        try:
            clob_ids = (
                json.loads(clob_ids_raw)
                if isinstance(clob_ids_raw, str)
                else clob_ids_raw
            )
        except Exception:
            return None

        if len(clob_ids) < 2:
            return None

        end_date_str = m_raw.get('endDate', '')
        try:
            end_dt = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
            end_ts = int(end_dt.timestamp())
        except Exception:
            return None

        now       = time.time()
        slot_secs = SLOT_SECS[tf]
        slot_ts   = end_ts - slot_secs
        elapsed   = now - slot_ts
        remaining = end_ts - now

        max_elapsed, min_remaining = ENTRY_WINDOWS[tf]
        if elapsed > max_elapsed or remaining < min_remaining:
            return None

        m = self._build_market_dict(
            slug=m_raw.get('slug', ''),
            condition_id=cid,
            clob_ids=clob_ids,
            end_ts=end_ts,
            tf=tf,
            accepting=m_raw.get('acceptingOrders', True),
            asset=asset,
        )
        if m:
            logger.info(
                f'MULTIFEED: {asset} {tf.upper():<5s} '
                f'Up={m["price_up"]:.3f} Down={m["price_down"]:.3f} | '
                f'rem={m["seconds_remaining"]:.0f}s | slug={m["slug"]}'
            )
        return m

    # ── Interface principal ──────────────────────────────────────────────────

    def scan(self) -> list[dict]:
        """
        Obtiene todos los mercados Up/Down activos para BTC, ETH, SOL y XRP
        en todos los timeframes.

        Fuentes:
          - determinísticos BTC: 5m, 15m, 4H (slug por slot_ts)
          - determinísticos 1H: todos los assets (slug por hora ET)
          - paginado: Daily y ventanas cortas (5m/15m/4H de ventana)
        """
        markets = self.get_deterministic_markets()
        markets += self.get_hourly_markets()
        markets += self._scan_nondeterministic()

        # Deduplicar por condition_id
        seen = set()
        unique = []
        for m in markets:
            if m['condition_id'] not in seen:
                seen.add(m['condition_id'])
                unique.append(m)

        if unique:
            summary = ', '.join(f'{m["asset"]} {m["timeframe"]}' for m in unique)
            logger.info(f'MULTIFEED: {len(unique)} mercados activos [{summary}]')
        else:
            logger.debug('MULTIFEED: ningún mercado activo en este ciclo')

        return unique

    # ── Outcome de mercado resuelto ──────────────────────────────────────────

    def get_market_outcome(self, slug: str) -> str | None:
        """
        Consulta si un mercado ya resolvió y cuál fue el resultado.
        Usa el endpoint /events?slug= que funciona correctamente para
        mercados fast (5m, 15m, 1h) de Polymarket.

        Returns:
            'Up' | 'Down' | None  (si aún no resolvió o hay error)
        """
        try:
            resp = self._session.get(
                f'{self.gamma_api}/events',
                params={'slug': slug},
                timeout=10,
            )
            resp.raise_for_status()
            events = resp.json()
        except Exception as e:
            logger.warning(
                f'MULTIFEED: Error consultando outcome {slug}: {e}'
            )
            return None

        if not events:
            return None

        markets = events[0].get('markets', [])
        if not markets:
            return None

        market     = markets[0]
        uma_status = market.get('umaResolutionStatus', '')
        is_closed  = market.get('closed', False)
        if uma_status != 'resolved' and not is_closed:
            return None

        # outcomePrices: ["1","0"] → Up ganó  |  ["0","1"] → Down ganó
        prices_raw = market.get('outcomePrices', '[]')
        try:
            prices = (
                json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
            )
            if len(prices) >= 2:
                if float(prices[0]) >= 0.99:
                    return 'Up'
                if float(prices[1]) >= 0.99:
                    return 'Down'
        except Exception:
            pass

        return None
