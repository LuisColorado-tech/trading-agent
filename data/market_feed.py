"""
MarketFeed — Módulo de obtención de datos de mercado.
Descarga OHLCV de Kraken (primary) y OKX (secondary/metals),
persiste en PostgreSQL y sirve DataFrames al IndicatorEngine.
"""
import os

import ccxt
import pandas as pd
import yaml
from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text

load_dotenv('/opt/trading/config/.env')

# Cargar config de exchanges desde YAML
_CONFIG_PATH = '/opt/trading/config/exchange_config.yaml'
with open(_CONFIG_PATH) as f:
    _EXCHANGE_CFG = yaml.safe_load(f)

# Mapeo asset -> (exchange_id, pair, timeframes) desde la config
def _build_asset_map():
    """Construye mapeo de assets priorizando exchange primario."""
    asset_map = {}
    for exc_name, exc_cfg in _EXCHANGE_CFG['exchanges'].items():
        if not exc_cfg.get('enabled', False):
            continue
        role = exc_cfg.get('role', 'backup')
        for asset_key, asset_cfg in exc_cfg.get('assets', {}).items():
            # Primary siempre gana; secondary solo si no existe
            if asset_key not in asset_map or role == 'primary':
                asset_map[asset_key] = {
                    'exchange': exc_name,
                    'ccxt_id': exc_cfg['ccxt_id'],
                    'pair': asset_cfg['pair'],
                    'timeframes': asset_cfg['timeframes'],
                }
    # XAG solo disponible en OKX
    return asset_map

ASSET_MAP = _build_asset_map()
OHLCV_LIMIT = 500


class MarketFeed:
    """Descarga y persiste datos de mercado OHLCV."""

    def __init__(self):
        # Instanciar exchanges habilitados
        self._exchanges = {}
        for exc_name, exc_cfg in _EXCHANGE_CFG['exchanges'].items():
            if not exc_cfg.get('enabled', False):
                continue
            ccxt_id = exc_cfg['ccxt_id']
            cls = getattr(ccxt, ccxt_id)
            env_prefix = exc_name.upper()
            self._exchanges[exc_name] = cls({
                'apiKey': os.getenv(f'{env_prefix}_API_KEY', ''),
                'secret': os.getenv(f'{env_prefix}_SECRET', ''),
                'enableRateLimit': exc_cfg.get('rate_limit', True),
            })

        # Database
        db_url = (
            f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
            f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT', '5432')}"
            f"/{os.getenv('POSTGRES_DB')}"
        )
        self.engine = create_engine(db_url)

    def _get_exchange(self, asset: str):
        """Devuelve la instancia ccxt correcta para un asset."""
        info = ASSET_MAP.get(asset)
        if not info:
            raise ValueError(f'Asset {asset} no configurado en exchange_config.yaml')
        return self._exchanges[info['exchange']], info['pair'], info['exchange']

    def fetch_ohlcv(self, asset: str, timeframe: str,
                    limit: int = OHLCV_LIMIT) -> pd.DataFrame:
        """Descarga OHLCV fresco del exchange."""
        exc, symbol, exc_name = self._get_exchange(asset)
        try:
            raw = exc.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(raw, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume'
            ])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
            df['asset'] = asset
            df['timeframe'] = timeframe
            df['exchange'] = exc_name
            return df.set_index('timestamp')
        except Exception as e:
            logger.error(f'fetch_ohlcv {asset}/{timeframe} ({exc_name}): {e}')
            return pd.DataFrame()

    def save_ohlcv(self, df: pd.DataFrame):
        """Persiste OHLCV en PostgreSQL con upsert (ignora duplicados)."""
        if df.empty:
            return
        df_db = df.reset_index()
        # Insertar ignorando conflictos de unique constraint
        with self.engine.begin() as conn:
            for _, row in df_db.iterrows():
                conn.execute(
                    text("""
                        INSERT INTO market_data
                            (asset, timeframe, timestamp, open, high, low, close, volume, exchange)
                        VALUES
                            (:asset, :timeframe, :timestamp, :open, :high, :low, :close, :volume, :exchange)
                        ON CONFLICT (asset, timeframe, timestamp, exchange) DO NOTHING
                    """),
                    {
                        'asset': row['asset'],
                        'timeframe': row['timeframe'],
                        'timestamp': row['timestamp'],
                        'open': float(row['open']),
                        'high': float(row['high']),
                        'low': float(row['low']),
                        'close': float(row['close']),
                        'volume': float(row['volume']),
                        'exchange': row['exchange'],
                    }
                )
        logger.debug(f'Saved {len(df_db)} candles for {df_db["asset"].iloc[0]}')

    def get_latest(self, asset: str, timeframe: str, n: int = 100) -> pd.DataFrame:
        """Lee últimas n velas desde DB para evitar rate limits."""
        with self.engine.connect() as conn:
            df = pd.read_sql(
                text("""
                    SELECT timestamp, open, high, low, close, volume
                    FROM market_data
                    WHERE asset = :asset AND timeframe = :tf
                    ORDER BY timestamp DESC LIMIT :n
                """),
                conn,
                params={'asset': asset, 'tf': timeframe, 'n': n},
            )
        if df.empty:
            return df
        return df.sort_values('timestamp').set_index('timestamp')

    def refresh(self, asset: str, timeframe: str, limit: int = OHLCV_LIMIT) -> pd.DataFrame:
        """Fetch + save + return from DB."""
        df = self.fetch_ohlcv(asset, timeframe, limit)
        if not df.empty:
            self.save_ohlcv(df)
        return self.get_latest(asset, timeframe, n=limit)
