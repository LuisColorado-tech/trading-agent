"""
btc_direction_feed.py — Feed para mercados BTC Up/Down 15m de Polymarket.

Descubrimiento determinístico: el slug del mercado se deriva del timestamp
actual sin búsqueda ni paginación.

  Slug = btc-updown-15m-{floor(unix_ts / 900) * 900}

Cada slot dura exactamente 900 segundos (15 minutos). El mercado se crea
en Polymarket ~2-5 min antes del inicio del slot.
"""
import json
import sys
import time
from datetime import datetime, timezone

import requests
from loguru import logger

sys.path.insert(0, '/opt/trading')

SLOT_SECS = 900  # 15 minutos


class BtcDirectionFeed:
    """Obtiene el mercado BTC Up/Down 15m activo del slot actual."""

    def __init__(self, config: dict):
        poly_cfg = config.get('polymarket', {})
        self.gamma_api       = poly_cfg.get('gamma_api', 'https://gamma-api.polymarket.com')
        self.clob_api        = poly_cfg.get('clob_api', 'https://clob.polymarket.com')
        self.min_remaining   = poly_cfg.get('min_remaining_seconds', 60)
        self.max_entry_secs  = poly_cfg.get('max_entry_seconds', 600)

        self._session = requests.Session()
        self._session.headers.update({'User-Agent': 'btc-direction-agent/1.0'})

    # ── Helpers de slot ──────────────────────────────────────────────────────

    @staticmethod
    def current_slot_ts() -> int:
        """Timestamp Unix del inicio del slot actual (múltiplo de 900s)."""
        return int(time.time()) // SLOT_SECS * SLOT_SECS

    @staticmethod
    def market_slug(slot_ts: int) -> str:
        return f'btc-updown-15m-{slot_ts}'

    # ── Mercado actual ───────────────────────────────────────────────────────

    def get_current_market(self) -> dict | None:
        """
        Obtiene datos del mercado activo del slot actual.

        Returns:
            dict con: slot_ts, slug, condition_id, token_up, token_down,
                      price_up, price_down, end_time, seconds_remaining,
                      accepting_orders
            None si el mercado no está disponible o el timing no es apropiado.
        """
        now = time.time()
        slot_ts = int(now) // SLOT_SECS * SLOT_SECS
        end_ts  = slot_ts + SLOT_SECS
        seconds_remaining = end_ts - now
        elapsed           = now - slot_ts

        # Timing checks
        if seconds_remaining < self.min_remaining:
            logger.debug(
                f'FEED: Slot {self.market_slug(slot_ts)} casi terminado '
                f'({seconds_remaining:.0f}s), omitiendo'
            )
            return None

        if elapsed > self.max_entry_secs:
            logger.debug(
                f'FEED: Slot {self.market_slug(slot_ts)} muy avanzado '
                f'({elapsed:.0f}s transcurridos), omitiendo'
            )
            return None

        slug = self.market_slug(slot_ts)

        # Consultar Gamma API
        try:
            resp = self._session.get(
                f'{self.gamma_api}/events',
                params={'slug': slug},
                timeout=10,
            )
            resp.raise_for_status()
            events = resp.json()
        except Exception as e:
            logger.warning(f'FEED: Error Gamma API para {slug}: {e}')
            return None

        if not events:
            logger.debug(f'FEED: Mercado {slug} aún no creado en Gamma API')
            return None

        event   = events[0]
        markets = event.get('markets', [])
        if not markets:
            logger.warning(f'FEED: Evento {slug} sin mercados')
            return None

        market       = markets[0]
        condition_id = market.get('conditionId', '')
        if not condition_id:
            logger.warning(f'FEED: conditionId vacío para {slug}')
            return None

        # Parsear token IDs (pueden venir como JSON string o lista)
        clob_ids_raw = market.get('clobTokenIds', '[]')
        try:
            clob_ids = json.loads(clob_ids_raw) if isinstance(clob_ids_raw, str) else clob_ids_raw
        except Exception:
            logger.warning(f'FEED: No se pudieron parsear clobTokenIds para {slug}')
            return None

        if len(clob_ids) < 2:
            logger.warning(f'FEED: Token IDs incompletos para {slug}: {clob_ids}')
            return None

        # outcomes[0]="Up" → token[0], outcomes[1]="Down" → token[1]
        token_up   = str(clob_ids[0]).strip()
        token_down = str(clob_ids[1]).strip()

        # Precios actuales del CLOB
        price_up   = self._get_midpoint(token_up)
        price_down = self._get_midpoint(token_down)
        end_time   = datetime.fromtimestamp(end_ts, tz=timezone.utc)

        result = {
            'slot_ts':           slot_ts,
            'slug':              slug,
            'condition_id':      condition_id,
            'token_up':          token_up,
            'token_down':        token_down,
            'price_up':          price_up,
            'price_down':        price_down,
            'end_time':          end_time,
            'seconds_remaining': seconds_remaining,
            'accepting_orders':  market.get('acceptingOrders', False),
        }

        logger.debug(
            f'FEED: {slug} | Up={price_up:.3f} Down={price_down:.3f} '
            f'accepting={result["accepting_orders"]} remaining={seconds_remaining:.0f}s'
        )
        return result

    # ── Precio midpoint ──────────────────────────────────────────────────────

    def _get_midpoint(self, token_id: str) -> float:
        """Obtiene precio midpoint del CLOB para un token (datos públicos, sin auth)."""
        try:
            resp = self._session.get(
                f'{self.clob_api}/midpoint',
                params={'token_id': token_id},
                timeout=5,
            )
            resp.raise_for_status()
            return float(resp.json().get('mid', 0.5))
        except Exception as e:
            logger.warning(f'FEED: Error midpoint token {token_id[:16]}...: {e}')
            return 0.5

    # ── Outcome de mercado resuelto ──────────────────────────────────────────

    def get_market_outcome(self, condition_id: str) -> str | None:
        """
        Consulta si un mercado ya resolvió y cuál fue el resultado.

        Returns:
            'Up' | 'Down' | None (si aún no resolvió o hay error)
        """
        try:
            resp = self._session.get(
                f'{self.gamma_api}/markets',
                params={'conditionId': condition_id},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(f'FEED: Error consultando outcome de {condition_id[:16]}...: {e}')
            return None

        if not data:
            return None

        market     = data[0]
        uma_status = market.get('umaResolutionStatus', '')
        if uma_status != 'resolved':
            return None

        # outcomePrices: ["1","0"] → Up ganó  |  ["0","1"] → Down ganó
        prices_raw = market.get('outcomePrices', '[]')
        try:
            prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
            if len(prices) >= 2:
                if float(prices[0]) >= 0.99:
                    return 'Up'
                if float(prices[1]) >= 0.99:
                    return 'Down'
        except Exception:
            pass

        return None
