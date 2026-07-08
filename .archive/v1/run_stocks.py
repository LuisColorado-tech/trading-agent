#!/usr/bin/env python3
"""
run_stocks.py — Entry point del stocks trading agent.

Uso:
  python3 scripts/run_stocks.py                # loop continuo
  python3 scripts/run_stocks.py --once         # un ciclo y salir
  python3 scripts/run_stocks.py --dry-run      # evalúa sin ejecutar órdenes
  python3 scripts/run_stocks.py --status       # muestra estado actual y sale
  python3 scripts/run_stocks.py --feed NVDA 15m 100   # descarga y muestra datos
"""
import sys
import os

sys.path.insert(0, '/opt/trading')

from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')

from loguru import logger

logger.remove()
logger.add(
    sys.stderr,
    format='<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}',
    level='INFO',
)
logger.add(
    '/opt/trading/logs/stocks_{time:YYYY-MM-DD}.log',
    rotation='1 day',
    retention='30 days',
    level='DEBUG',
)


def main():
    args = sys.argv[1:]

    # ── Modo feed: descarga datos de prueba ──────────────────────────────────
    if '--feed' in args:
        idx = args.index('--feed')
        sym = args[idx + 1] if idx + 1 < len(args) else 'NVDA'
        tf  = args[idx + 2] if idx + 2 < len(args) else '15m'
        n   = int(args[idx + 3]) if idx + 3 < len(args) else 100
        from data.stocks_feed import StocksFeed
        feed = StocksFeed()
        df = feed.get_latest(sym, tf, n)
        if df.empty:
            print(f"Sin datos para {sym}/{tf}")
            sys.exit(1)
        print(f"\n{sym}/{tf} — {len(df)} barras:")
        print(df.tail(10).to_string())
        print(f"\nMacro bias (SPY+QQQ): {feed.get_macro_bias()}")
        sys.exit(0)

    # ── Modo status ──────────────────────────────────────────────────────────
    if '--status' in args:
        from agents.stocks_agent import StocksAgent
        agent = StocksAgent(dry_run=True)
        status = agent.get_status()
        print(f"\n{'='*50}")
        print(f"  STOCKS AGENT STATUS")
        print(f"{'='*50}")
        print(f"  Sesión:       {status['session']}")
        print(f"  Balance:      ${status['balance']:.2f}")
        print(f"  Trades open:  {status['open_trades']}")
        print(f"  NYSE open:    {status['market_open']}")
        print(f"  Macro bias:   {status['macro_bias']}")
        if status['positions']:
            print(f"\n  Posiciones abiertas:")
            for p in status['positions']:
                arrow = '▲' if p['pnl'] >= 0 else '▼'
                print(f"    {p['symbol']} {p['direction']} entry=${p['entry']:.2f} "
                      f"now=${p['current']:.2f} pnl=${p['pnl']:+.2f} {arrow}")
        print(f"{'='*50}\n")
        sys.exit(0)

    # ── Modo normal: agente loop ─────────────────────────────────────────────
    once    = '--once' in args
    dry_run = '--dry-run' in args

    logger.info(f"Iniciando StocksAgent | once={once} | dry_run={dry_run}")

    from agents.stocks_agent import StocksAgent
    agent = StocksAgent(dry_run=dry_run)
    agent.run(once=once)


if __name__ == '__main__':
    main()
