"""
run_btc_direction.py — Loop principal del agente BTC Direction 15m.

Detecta automáticamente el mercado activo de cada slot de 15 minutos,
aplica señal combinada (momentum BTC + edge Polymarket) y ejecuta en paper.

Uso:
    python3 /opt/trading/btc_direction/run_btc_direction.py
"""
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────

sys.path.insert(0, '/opt/trading')
sys.path.insert(0, '/opt/trading/btc_direction')

from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')

import yaml
from loguru import logger

# ── Logging ──────────────────────────────────────────────────────────────────

_log_dir = Path('/opt/trading/logs')
_log_dir.mkdir(exist_ok=True)

logger.add(
    str(_log_dir / 'btc_direction_{time}.log'),
    rotation='1 day',
    retention='14 days',
    level='INFO',
    format='{time:YYYY-MM-DD HH:mm:ss} | {level:<7} | {message}',
)

# ── Config ───────────────────────────────────────────────────────────────────

_CFG_PATH = Path('/opt/trading/btc_direction/btc_direction_config.yaml')
with open(_CFG_PATH) as _f:
    _CFG = yaml.safe_load(_f).get('btc_direction', {})

# ── Importar módulos del agente ───────────────────────────────────────────────

from btc_direction_feed     import BtcDirectionFeed
from btc_direction_strategy import BtcDirectionStrategy
from btc_direction_executor import BtcDirectionExecutor

LOOP_INTERVAL_SECS = 30


def run():
    logger.info('═' * 64)
    logger.info('BTC DIRECTION 15m — AGENTE INICIANDO')
    logger.info(f'Config:        {_CFG_PATH}')
    logger.info(f'Paper mode:    {_CFG.get("paper_trading", True)}')
    logger.info(f'Balance init:  ${_CFG.get("initial_paper_balance", 500.0):.2f} USDC')
    logger.info(f'Max trade:     ${_CFG.get("risk", {}).get("max_trade_usdc", 20.0):.2f} USDC')
    logger.info('═' * 64)

    feed     = BtcDirectionFeed(_CFG)
    strategy = BtcDirectionStrategy(_CFG)
    executor = BtcDirectionExecutor(_CFG)

    logger.info(f'Balance actual (desde DB): ${executor.paper_balance:.2f} USDC')

    cycle           = 0
    last_slot_ts    = 0  # slot que ya logueamos

    while True:
        cycle += 1
        now     = time.time()
        slot_ts = int(now) // 900 * 900
        slot_dt = datetime.fromtimestamp(slot_ts, tz=timezone.utc)

        try:
            # ── 1. Cerrar posiciones de slots ya expirados ────────────────
            closed = executor.close_expired(feed)
            for c in closed:
                icon = '✓' if c['won'] else '✗'
                logger.info(
                    f'  {icon} CERRADO {c["direction"]}→{c["outcome"]} '
                    f'P&L=${c["pnl"]:+.2f} USDC'
                )

            # ── 2. Obtener mercado activo del slot actual ─────────────────
            market = feed.get_current_market()
            if market is None:
                if slot_ts != last_slot_ts:
                    logger.info(
                        f'[Ciclo {cycle}] Slot {slot_dt.strftime("%m/%d %H:%M")} UTC — '
                        'mercado no disponible (fuera de ventana de entrada)'
                    )
                    last_slot_ts = slot_ts
                time.sleep(LOOP_INTERVAL_SECS)
                continue

            # ── 3. Log de apertura del slot (solo una vez por slot) ───────
            if slot_ts != last_slot_ts:
                logger.info(
                    f'[Slot {slot_dt.strftime("%m/%d %H:%M")} UTC] '
                    f'slug={market["slug"]} | '
                    f'Up={market["price_up"]:.3f}  Down={market["price_down"]:.3f} | '
                    f'remaining={market["seconds_remaining"]:.0f}s | '
                    f'balance=${executor.paper_balance:.2f}'
                )
                last_slot_ts = slot_ts

            # ── 4. Idempotencia: ¿ya operamos este slot? ──────────────────
            if executor.already_traded_slot(slot_ts):
                time.sleep(LOOP_INTERVAL_SECS)
                continue

            # ── 5. Evaluar señal ──────────────────────────────────────────
            signal = strategy.evaluate(market)
            if signal['direction'] is None:
                logger.debug(f'  No signal → {signal["reasoning"]}')
                time.sleep(LOOP_INTERVAL_SECS)
                continue

            # ── 6. Ejecutar trade ─────────────────────────────────────────
            result = executor.execute(signal, market)

            if result['executed']:
                logger.info(
                    f'  ▶ TRADE {signal["direction"]} | '
                    f'shares={result["shares"]:.2f} @ {result["entry_price"]:.3f} = '
                    f'${result["cost_usdc"]:.2f} USDC | '
                    f'BTC_5m={signal["btc_5m_pct"]:+.3f}% edge={signal["edge"]:.3f} '
                    f'conf={signal["confidence"]:.2f}'
                )
            else:
                logger.debug(f'  No ejecutado: {result.get("reason")}')

            # ── 7. Estadísticas periódicas (cada 20 ciclos) ───────────────
            if cycle % 20 == 0:
                _log_stats(executor)

        except KeyboardInterrupt:
            logger.info('BTC DIRECTION: Detenido por usuario (Ctrl+C)')
            _log_stats(executor, final=True)
            break
        except Exception as e:
            logger.error(f'[Ciclo {cycle}] Error inesperado: {e}', exc_info=True)

        time.sleep(LOOP_INTERVAL_SECS)


def _log_stats(executor: BtcDirectionExecutor, final: bool = False):
    stats = executor.get_stats()
    header = 'RESUMEN FINAL' if final else 'STATS'
    if final:
        logger.info('═' * 64)
        logger.info(f'BTC DIRECTION — {header}')
    logger.info(
        f'{header}: trades={stats["total_trades"]} '
        f'open={stats["open"]} closed={stats["closed"]} '
        f'wins={stats["wins"]} ({stats["win_rate_pct"]:.1f}%) | '
        f'P&L=${stats["total_pnl"]:+.2f} balance=${stats["paper_balance"]:.2f}'
    )
    if final:
        logger.info('═' * 64)


if __name__ == '__main__':
    run()
