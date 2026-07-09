"""
run_btc_direction.py — Loop principal del agente BTC Direction (multi-timeframe).

Detecta automáticamente mercados activos BTC Up/Down en todos los timeframes:
  5m, 15m, 4H  → slug determinístico (sin paginación)
  1H, Daily    → scan paginado con cache de 5 minutos

Aplica señal de momentum BTC a cada mercado disponible y ejecuta en paper.

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

from btc_multifeed          import BtcMultiFeed
from btc_direction_strategy import BtcDirectionStrategy
from btc_direction_executor import BtcDirectionExecutor

LOOP_INTERVAL_SECS = 30


def run():
    logger.info('═' * 64)
    logger.info('BTC DIRECTION MULTI-TF — AGENTE INICIANDO')
    logger.info(f'Config:        {_CFG_PATH}')
    logger.info(f'Paper mode:    {_CFG.get("paper_trading", True)}')
    logger.info(f'Balance init:  ${_CFG.get("initial_paper_balance", 500.0):.2f} USDC')
    logger.info(f'Max trade:     ${_CFG.get("risk", {}).get("max_trade_usdc", 20.0):.2f} USDC')
    logger.info(f'Timeframes:    5m · 15m · 4H (determinístico) + 1H · Daily (scan)')
    logger.info('═' * 64)

    feed     = BtcMultiFeed(_CFG)
    strategy = BtcDirectionStrategy(_CFG)
    executor = BtcDirectionExecutor(_CFG)

    logger.info(f'Balance actual (desde DB): ${executor.paper_balance:.2f} USDC')

    cycle = 0

    while True:
        cycle += 1

        try:
            # ── 1. Cerrar posiciones de slots ya expirados ────────────────
            closed = executor.close_expired(feed)
            for c in closed:
                icon = '✓' if c['won'] else '✗'
                logger.info(
                    f'  {icon} CERRADO {c["direction"]}→{c["outcome"]} '
                    f'P&L=${c["pnl"]:+.2f} USDC'
                )

            # ── 2. Obtener todos los mercados activos (multi-TF) ──────────
            markets = feed.scan()
            if not markets:
                logger.debug(
                    f'[Ciclo {cycle}] Ningún mercado activo '
                    f'(próximo scan en {LOOP_INTERVAL_SECS}s)'
                )
                time.sleep(LOOP_INTERVAL_SECS)
                continue

            # ── 3. Procesar cada mercado disponible ───────────────────────
            for market in markets:
                tf  = market['timeframe']
                cid = market['condition_id']

                # Idempotencia: ¿ya operamos este mercado?
                if executor.already_traded(cid):
                    logger.debug(f'  {tf.upper()} {market["slug"][:40]} → ya operado')
                    continue

                # Evaluar señal para este mercado
                signal = strategy.evaluate(market)
                if signal['direction'] is None:
                    logger.debug(
                        f'  {tf.upper()} No signal → {signal.get("reasoning", "")}'
                    )
                    continue

                # Ejecutar paper trade
                result = executor.execute(signal, market)

                if result['executed']:
                    asset = market.get('asset', 'BTC')
                    logger.info(
                        f'  ▶ TRADE [{asset} {tf.upper()}] {signal["direction"]} | '
                        f'shares={result["shares"]:.2f} @ {result["entry_price"]:.3f} '
                        f'= ${result["cost_usdc"]:.2f} USDC | '
                        f'edge={signal["edge"]:.3f} conf={signal["confidence"]:.2f} | '
                        f'slug={market["slug"]}'
                    )
                else:
                    reason = result.get('reason', '')
                    if reason not in ('ALREADY_TRADED_SLOT', 'MAX_OPEN_POSITIONS'):
                        logger.debug(f'  {tf.upper()} No ejecutado: {reason}')

            # ── 4. Estadísticas periódicas (cada 20 ciclos) ───────────────
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
