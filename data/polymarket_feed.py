"""
polymarket_feed.py — Fuente de datos para mercados de predicción Polymarket.

Usa Gamma Markets API para descubrimiento de mercados (preguntas, volumen,
categorías) y CLOB API para precios en tiempo real y order books.
Persiste mercados activos en DB.
"""
import json as _json
import os
import sys
from datetime import datetime, timezone, timedelta

import requests
import yaml
from loguru import logger
from py_clob_client.client import ClobClient
from sqlalchemy import create_engine, text

sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv

load_dotenv('/opt/trading/config/.env')

with open('/opt/trading/config/exchange_config.yaml') as f:
    _CFG = yaml.safe_load(f).get('polymarket', {})

_FILTERS = _CFG.get('market_filters', {})
MIN_VOLUME = _FILTERS.get('min_volume', 20000)
MIN_LIQUIDITY = _FILTERS.get('min_liquidity', 5000)
MAX_END_DAYS = _FILTERS.get('max_end_days', 30)
MIN_END_HOURS = _FILTERS.get('min_end_hours', 2)
MIN_PRICE_YES = _FILTERS.get('min_price_yes', 0.20)
MAX_PRICE_YES = _FILTERS.get('max_price_yes', 0.80)

_CATEGORIES_ALLOWED = set(c.lower() for c in _CFG.get('categories_allowed', ['crypto']))
_QUESTION_KEYWORDS = [kw.lower() for kw in _CFG.get('question_keywords', [
    'btc', 'bitcoin', 'eth', 'ethereum', 'crypto', 'cryptocurrency',
])]

GAMMA_API = 'https://gamma-api.polymarket.com'


def _db_url() -> str:
    return (
        f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
        f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT', '5432')}"
        f"/{os.getenv('POSTGRES_DB')}"
    )


class PolymarketFeed:
    """Read-only feed para mercados de predicción Polymarket."""

    def __init__(self):
        host = _CFG.get('host', 'https://clob.polymarket.com')
        self.client = ClobClient(host)
        self.engine = create_engine(_db_url())

    def scan_markets(self) -> list[dict]:
        """Descarga mercados activos desde Gamma API, filtrados por volumen/liquidez/tiempo."""
        now = datetime.now(timezone.utc)
        max_end = now + timedelta(days=MAX_END_DAYS)
        min_end = now + timedelta(hours=MIN_END_HOURS)

        all_markets = []
        offset = 0
        page_size = 100
        max_pages = 10

        for _ in range(max_pages):
            try:
                resp = requests.get(f'{GAMMA_API}/markets', params={
                    'limit': page_size,
                    'offset': offset,
                    'active': True,
                    'closed': False,
                    'order': 'volume24hr',
                    'ascending': False,
                }, timeout=15)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error(f'POLY FEED: Gamma API error: {e}')
                break

            if not data:
                break

            for m in data:
                try:
                    parsed = self._parse_market(m, now, min_end, max_end)
                    if parsed:
                        all_markets.append(parsed)
                except Exception as e:
                    logger.debug(f'POLY FEED: Skip market parse error: {e}')

            if len(data) < page_size:
                break
            offset += page_size

        logger.info(f'POLY FEED: Scanned {offset // page_size + 1} pages, found {len(all_markets)} qualifying markets')
        return all_markets

    def _parse_market(self, m: dict, now, min_end, max_end) -> dict | None:
        """Parsea un mercado de Gamma API y aplica filtros."""
        # Solo mercados binarios YES/NO
        outcomes = m.get('outcomes', '')
        if isinstance(outcomes, str):
            try:
                outcomes = _json.loads(outcomes)
            except (ValueError, TypeError):
                return None
        if not outcomes or len(outcomes) < 2:
            return None

        # Normalizar outcomes
        outcomes_upper = [o.strip().upper() for o in outcomes]
        if 'YES' not in outcomes_upper or 'NO' not in outcomes_upper:
            return None

        # Filtro: volumen
        volume = float(m.get('volume', 0) or 0)
        if volume < MIN_VOLUME:
            return None

        # Filtro: liquidez
        liquidity = float(m.get('liquidity', 0) or 0)
        if liquidity < MIN_LIQUIDITY:
            return None

        # Filtro: accepting orders
        if not m.get('acceptingOrders', False):
            return None

        # Filtro: fecha de resolución
        end_str = m.get('endDate') or m.get('endDateIso', '')
        if not end_str:
            return None
        try:
            end_date = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return None

        if end_date < min_end or end_date > max_end:
            return None

        # Precios desde outcomePrices (JSON string)
        prices_raw = m.get('outcomePrices', '')
        if isinstance(prices_raw, str):
            try:
                prices_raw = _json.loads(prices_raw)
            except (ValueError, TypeError):
                return None
        if not isinstance(prices_raw, list) or len(prices_raw) < 2:
            return None

        yes_idx = outcomes_upper.index('YES')
        no_idx = outcomes_upper.index('NO')
        price_yes = float(prices_raw[yes_idx])
        price_no = float(prices_raw[no_idx])

        # Filtro: precio en zona moderada (0.20–0.80)
        # Fuera de este rango señales técnicas no tienen edge confiable.
        if price_yes < MIN_PRICE_YES or price_yes > MAX_PRICE_YES:
            return None

        # Filtro: al menos una keyword crypto en la pregunta
        # (La Gamma API devuelve category=None en la mayoría de mercados,
        # así que filtramos por contenido de la pregunta directamente.)
        question_lower = m.get('question', '').lower()
        if not any(kw in question_lower for kw in _QUESTION_KEYWORDS):
            return None

        # Token IDs desde clobTokenIds (JSON string)
        token_ids_raw = m.get('clobTokenIds', '')
        if isinstance(token_ids_raw, str):
            try:
                token_ids_raw = _json.loads(token_ids_raw)
            except (ValueError, TypeError):
                return None
        if not isinstance(token_ids_raw, list) or len(token_ids_raw) < 2:
            return None

        token_yes = token_ids_raw[yes_idx]
        token_no = token_ids_raw[no_idx]

        category = (m.get('category', '') or '').lower()

        return {
            'condition_id': m.get('conditionId', ''),
            'question': m.get('question', ''),
            'description': m.get('description', '')[:500] if m.get('description') else '',
            'category': category,
            'end_date': end_date,
            'token_yes': token_yes,
            'token_no': token_no,
            'price_yes': price_yes,
            'price_no': price_no,
            'volume': volume,
            'liquidity': liquidity,
        }

    def get_price(self, token_id: str) -> float | None:
        """Obtiene precio actual de un token."""
        try:
            mid = self.client.get_midpoint(token_id)
            return float(mid.get('mid', 0)) if isinstance(mid, dict) else float(mid)
        except Exception as e:
            logger.warning(f'POLY FEED: Price error for {token_id[:12]}...: {e}')
            return None

    def get_order_book(self, token_id: str) -> dict | None:
        """Obtiene order book para un token."""
        try:
            book = self.client.get_order_book(token_id)
            return book
        except Exception as e:
            logger.warning(f'POLY FEED: OrderBook error: {e}')
            return None

    def save_markets(self, markets: list[dict]) -> int:
        """Persiste mercados en DB (upsert)."""
        if not markets:
            return 0
        saved = 0
        with self.engine.connect() as conn:
            for m in markets:
                conn.execute(
                    text('''
                        INSERT INTO poly_markets
                            (condition_id, question, category, end_date,
                             token_yes, token_no, price_yes, price_no,
                             volume, liquidity, active, updated_at)
                        VALUES
                            (:cid, :q, :cat, :end, :ty, :tn, :py, :pn,
                             :vol, :liq, true, now())
                        ON CONFLICT (condition_id) DO UPDATE SET
                            price_yes = EXCLUDED.price_yes,
                            price_no = EXCLUDED.price_no,
                            volume = EXCLUDED.volume,
                            liquidity = EXCLUDED.liquidity,
                            updated_at = now()
                    '''),
                    {
                        'cid': m['condition_id'], 'q': m['question'],
                        'cat': m['category'], 'end': m['end_date'],
                        'ty': m['token_yes'], 'tn': m['token_no'],
                        'py': m['price_yes'], 'pn': m['price_no'],
                        'vol': m['volume'], 'liq': m['liquidity'],
                    },
                )
                saved += 1
            conn.commit()
        logger.debug(f'POLY FEED: Saved {saved} markets to DB')
        return saved

    def check_resolutions(self) -> list[dict]:
        """Detecta mercados que han sido resueltos consultando el API."""
        resolved = []
        with self.engine.connect() as conn:
            rows = conn.execute(
                text('''
                    SELECT id, condition_id, token_yes, token_no, question
                    FROM poly_markets
                    WHERE active = true AND end_date < now()
                ''')
            ).fetchall()

        for row in rows:
            row = dict(row._mapping)
            try:
                price_yes = self.get_price(row['token_yes'])
                price_no = self.get_price(row['token_no'])
                if price_yes is None:
                    # CLOB 404: mercado expirado sin orderbook → marcar inactivo
                    with self.engine.connect() as conn:
                        conn.execute(
                            text("UPDATE poly_markets SET active = false WHERE id = :id"),
                            {'id': row['id']},
                        )
                        conn.commit()
                    continue
                # Resolved: price ≈ 1.0 or ≈ 0.0
                if price_yes >= 0.95:
                    outcome = 'YES'
                elif price_yes <= 0.05:
                    outcome = 'NO'
                else:
                    continue  # Not yet resolved

                with self.engine.connect() as conn:
                    conn.execute(
                        text('''
                            UPDATE poly_markets
                            SET outcome = :outcome, resolved_at = now(),
                                price_yes = :py, price_no = :pn, active = false
                            WHERE id = :id
                        '''),
                        {'outcome': outcome, 'py': price_yes,
                         'pn': price_no or 0, 'id': row['id']},
                    )
                    conn.commit()
                resolved.append({**row, 'outcome': outcome})
                logger.info(f'POLY FEED: Market RESOLVED: {row["question"][:60]} → {outcome}')
            except Exception as e:
                logger.warning(f'POLY FEED: Resolution check error: {e}')

        return resolved

    def get_active_markets_from_db(self) -> list[dict]:
        """Carga mercados activos desde DB, filtrados por precio y keyword crypto."""
        with self.engine.connect() as conn:
            rows = conn.execute(
                text('''
                    SELECT id, condition_id, question, category, end_date,
                           token_yes, token_no, price_yes, price_no,
                           volume, liquidity
                    FROM poly_markets
                    WHERE active = true
                      AND price_yes BETWEEN :min_p AND :max_p
                      AND end_date > now()
                      AND (
                          question ILIKE :kw1 OR question ILIKE :kw2
                          OR question ILIKE :kw3 OR question ILIKE :kw4
                          OR question ILIKE :kw5 OR question ILIKE :kw6
                      )
                    ORDER BY volume DESC
                '''),
                {
                    'min_p': MIN_PRICE_YES, 'max_p': MAX_PRICE_YES,
                    'kw1': '%btc%', 'kw2': '%bitcoin%',
                    'kw3': '%eth%', 'kw4': '%ethereum%',
                    'kw5': '%crypto%', 'kw6': '%cryptocurrency%',
                },
            ).fetchall()
        return [dict(r._mapping) for r in rows]

    def scan_tail_end_markets(self, min_price: float = 0.90, max_end_days: int = 7) -> list[dict]:
        """Escanea Gamma API buscando mercados con outcomes casi-ciertos.

        Para Tail-End Trading: outcomes donde price_yes ≥ min_price (near resolution).
        No requiere keyword filter — cualquier mercado binario sirve.

        Args:
            min_price: precio mínimo del outcome (default 0.90)
            max_end_days: días máximos hasta expiración (default 7)

        Returns:
            Lista de mercados candidatos para tail-end trading.
        """
        now = datetime.now(timezone.utc)
        max_end = now + timedelta(days=max_end_days)
        min_end = now + timedelta(hours=1)  # al menos 1 hora restante

        all_markets = []
        offset = 0
        page_size = 100

        for _ in range(5):  # máximo 5 páginas
            try:
                resp = requests.get(f'{GAMMA_API}/markets', params={
                    'limit': page_size,
                    'offset': offset,
                    'active': True,
                    'closed': False,
                    'order': 'endDate',
                    'ascending': True,
                }, timeout=15)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error(f'POLY FEED tail_end: Gamma API error: {e}')
                break

            if not data:
                break

            for m in data:
                try:
                    parsed = self._parse_tail_end_market(m, now, min_end, max_end, min_price)
                    if parsed:
                        all_markets.append(parsed)
                except Exception as e:
                    logger.debug(f'POLY FEED tail_end: Parse error: {e}')

            if len(data) < page_size:
                break
            offset += page_size

        logger.debug(f'POLY FEED tail_end: Found {len(all_markets)} tail-end candidates')
        return all_markets

    def _parse_tail_end_market(self, m: dict, now, min_end, max_end,
                                min_price: float) -> dict | None:
        """Parsea un mercado para Tail-End Trading."""
        outcomes = m.get('outcomes', '')
        if isinstance(outcomes, str):
            try:
                outcomes = _json.loads(outcomes)
            except (ValueError, TypeError):
                return None
        if not outcomes or len(outcomes) < 2:
            return None

        outcomes_upper = [o.strip().upper() for o in outcomes]
        if 'YES' not in outcomes_upper or 'NO' not in outcomes_upper:
            return None

        if not m.get('acceptingOrders', False):
            return None

        end_str = m.get('endDate') or m.get('endDateIso', '')
        if not end_str:
            return None
        try:
            end_date = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return None

        if end_date < min_end or end_date > max_end:
            return None

        prices_raw = m.get('outcomePrices', '')
        if isinstance(prices_raw, str):
            try:
                prices_raw = _json.loads(prices_raw)
            except (ValueError, TypeError):
                return None
        if not isinstance(prices_raw, list) or len(prices_raw) < 2:
            return None

        yes_idx = outcomes_upper.index('YES')
        no_idx = outcomes_upper.index('NO')
        price_yes = float(prices_raw[yes_idx])
        price_no = float(prices_raw[no_idx])

        # Al menos uno debe estar en zona near-resolution
        if price_yes < min_price and price_no < min_price:
            return None

        # Volumen mínimo (evitar mercados sin liquidez)
        volume = float(m.get('volume', 0) or 0)
        if volume < 1000:
            return None

        token_ids_raw = m.get('clobTokenIds', '')
        if isinstance(token_ids_raw, str):
            try:
                token_ids_raw = _json.loads(token_ids_raw)
            except (ValueError, TypeError):
                return None
        if not isinstance(token_ids_raw, list) or len(token_ids_raw) < 2:
            return None

        return {
            'condition_id': m.get('conditionId', ''),
            'question': m.get('question', ''),
            'description': m.get('description', '')[:200] if m.get('description') else '',
            'category': (m.get('category', '') or '').lower(),
            'end_date': end_date,
            'token_yes': token_ids_raw[yes_idx],
            'token_no': token_ids_raw[no_idx],
            'price_yes': price_yes,
            'price_no': price_no,
            'volume': volume,
            'liquidity': float(m.get('liquidity', 0) or 0),
        }

    def scan_15min_markets(self) -> list[dict]:
        """Escanea Gamma API buscando mercados de crypto que cierran en ≤15 minutos.

        Para Late Entry V3: entrar en los últimos 4 minutos de mercados 15-min.
        Activos: BTC, ETH, SOL, XRP.

        Returns:
            Lista de mercados ordenados por end_date ASC (los que cierran antes primero).
        """
        now = datetime.now(timezone.utc)
        max_end = now + timedelta(minutes=15)
        min_end = now + timedelta(seconds=30)  # al menos 30s restantes

        all_markets = []

        try:
            resp = requests.get(f'{GAMMA_API}/markets', params={
                'limit': 100,
                'offset': 0,
                'active': True,
                'closed': False,
                'order': 'endDate',
                'ascending': True,
            }, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f'POLY FEED 15min: Gamma API error: {e}')
            return []

        for m in data:
            try:
                end_str = m.get('endDate') or m.get('endDateIso', '')
                if not end_str:
                    continue
                end_date = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
                if end_date < min_end or end_date > max_end:
                    continue

                if not m.get('acceptingOrders', False):
                    continue

                q_lower = m.get('question', '').lower()
                late_entry_keywords = ['btc', 'bitcoin', 'eth', 'ethereum', 'sol', 'solana', 'xrp', 'ripple']
                if not any(kw in q_lower for kw in late_entry_keywords):
                    continue

                parsed = self._parse_market(m, now, min_end, max_end)
                # Para late entry, relajar el filtro de precio (queremos mercados con consenso ≥ 0.60)
                if parsed:
                    all_markets.append(parsed)
                else:
                    # Intentar parsear sin filtro de precio
                    prices_raw = m.get('outcomePrices', '')
                    if isinstance(prices_raw, str):
                        try:
                            prices_raw = _json.loads(prices_raw)
                        except (ValueError, TypeError):
                            continue
                    if not isinstance(prices_raw, list) or len(prices_raw) < 2:
                        continue

                    outcomes = m.get('outcomes', '')
                    if isinstance(outcomes, str):
                        try:
                            outcomes = _json.loads(outcomes)
                        except (ValueError, TypeError):
                            continue
                    if not outcomes or len(outcomes) < 2:
                        continue

                    outcomes_upper = [o.strip().upper() for o in outcomes]
                    if 'YES' not in outcomes_upper or 'NO' not in outcomes_upper:
                        continue

                    yes_idx = outcomes_upper.index('YES')
                    no_idx = outcomes_upper.index('NO')

                    token_ids_raw = m.get('clobTokenIds', '')
                    if isinstance(token_ids_raw, str):
                        try:
                            token_ids_raw = _json.loads(token_ids_raw)
                        except (ValueError, TypeError):
                            continue

                    all_markets.append({
                        'condition_id': m.get('conditionId', ''),
                        'question': m.get('question', ''),
                        'category': (m.get('category', '') or '').lower(),
                        'end_date': end_date,
                        'token_yes': token_ids_raw[yes_idx] if len(token_ids_raw) > yes_idx else '',
                        'token_no': token_ids_raw[no_idx] if len(token_ids_raw) > no_idx else '',
                        'price_yes': float(prices_raw[yes_idx]),
                        'price_no': float(prices_raw[no_idx]),
                        'volume': float(m.get('volume', 0) or 0),
                        'liquidity': float(m.get('liquidity', 0) or 0),
                    })
            except Exception as e:
                logger.debug(f'POLY FEED 15min: Parse error: {e}')

        # Ordenar por end_date ASC
        all_markets.sort(key=lambda m: m['end_date'])
        logger.debug(f'POLY FEED 15min: Found {len(all_markets)} markets closing in ≤15min')
        return all_markets
