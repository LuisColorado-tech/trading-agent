"""
Daily Briefing — Genera resumen diario del mercado via Claude.
Se ejecuta via cron a las 07:00 UTC.
"""
import json
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text

sys.path.insert(0, '/opt/trading')
load_dotenv('/opt/trading/config/.env')

from agents.indicators import IndicatorEngine
from core.claude_bridge import ClaudeBridge
from data.market_feed import MarketFeed


def run_briefing():
    """Genera y guarda el daily briefing."""
    feed = MarketFeed()
    claude = ClaudeBridge()

    # Recopilar estado de todos los activos
    market_snapshot = {}
    for asset in ['BTC', 'ETH', 'SOL', 'XAU', 'XAG']:
        df = feed.get_latest(asset, '1h', n=24)
        if not df.empty:
            ind = IndicatorEngine.calculate(df, asset, '1h')
            if ind:
                first_close = df['close'].iloc[0]
                change_24h = ((ind.close / first_close) - 1) * 100 if first_close > 0 else 0
                market_snapshot[asset] = {
                    'price': ind.close,
                    'rsi': ind.rsi,
                    'trend': ind.trend_direction,
                    'vol_ratio': ind.vol_ratio,
                    'change_24h': round(change_24h, 2),
                }

    briefing = claude.call(
        task_type='daily_briefing',
        asset='ALL',
        data={
            'market_snapshot': market_snapshot,
            'date': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        },
    )

    # Guardar en DB
    db_url = (
        f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
        f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT', '5432')}"
        f"/{os.getenv('POSTGRES_DB')}"
    )
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO claude_explanations
                    (task_type, asset, input_payload, result,
                     confidence, reasoning, flags)
                VALUES
                    (:task_type, :asset, :input_payload, :result,
                     :confidence, :reasoning, :flags)
            """),
            {
                'task_type': 'daily_briefing',
                'asset': 'ALL',
                'input_payload': json.dumps(market_snapshot, default=str),
                'result': json.dumps(briefing, default=str),
                'confidence': briefing.get('confidence', 0),
                'reasoning': briefing.get('reasoning', ''),
                'flags': briefing.get('flags', []),
            },
        )

    logger.info(f'Daily briefing saved: {str(briefing.get("result", ""))[:100]}...')
    return briefing


if __name__ == '__main__':
    result = run_briefing()
    print(json.dumps(result, indent=2, default=str))
