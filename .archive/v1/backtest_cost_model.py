#!/usr/bin/env python3
"""Quick backtest — all assets, 300 candles (~12d), OKX maker fees."""
import sys; sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv; load_dotenv('/opt/trading/config/.env')
from collections import defaultdict
import pandas as pd, numpy as np

from data.market_feed import MarketFeed, ASSET_MAP
from agents.indicators import IndicatorEngine
from agents.strategy_engine import StrategyEngine
from core.market_regime import classify_market_regime, strategy_allowed_in_regime
from core.asset_profiles import get_profile
from core.cost_model import round_trip_cost_pct, net_pnl, MIN_NET_RR_RATIO

feed = MarketFeed()
indicators = IndicatorEngine()
engine = StrategyEngine()
S = lambda: defaultdict(lambda: {'trades':0,'wins':0,'pnl_net':0,'pnl_gross':0,'fees':0,'signals':0,'rejected':0,'fills':0,'tos':0})
stats = S()
assets = [a for a in ASSET_MAP if a != 'POL']

for asset in assets:
    print('%s...' % asset, end=' ', flush=True)
    df = feed.fetch_ohlcv(asset, '1h', limit=300)
    if len(df) < 200:
        print('skip (%d candles)' % len(df))
        continue
    print('%d candles' % len(df), flush=True)

    profile = get_profile(asset)
    exchange = ASSET_MAP.get(asset, {}).get('exchange', 'okx')
    balance = 500.0; peak = 500.0
    open_trades = []; pending = {}
    warmup = 100

    for i in range(warmup, len(df)):
        bar = df.iloc[i]; price = float(bar['close'])
        bar_high = float(bar['high']); bar_low = float(bar['low'])

        # Fill pending maker orders
        for tid in list(pending):
            t = pending[tid]
            touched = (t['dir'] == 'BUY' and bar_low <= t['limit']) or (t['dir'] == 'SELL' and bar_high >= t['limit'])
            if touched:
                stats[(t['strategy'], asset)]['fills'] += 1
                open_trades.append({**t, 'entry_idx': i}); del pending[tid]
            elif i - t['idx'] >= 3:
                stats[(t['strategy'], asset)]['tos'] += 1; del pending[tid]

        # Check SL/TP on open trades
        for t in list(open_trades):
            if t['dir'] == 'BUY':
                hit = price <= t['sl'] or price >= t['tp']
            else:
                hit = price >= t['sl'] or price <= t['tp']
            if hit:
                if t['dir'] == 'BUY':
                    exit_px = t['sl'] if price <= t['sl'] else t['tp']
                    reason = 'SL' if price <= t['sl'] else 'TP'
                else:
                    exit_px = t['sl'] if price >= t['sl'] else t['tp']
                    reason = 'SL' if price >= t['sl'] else 'TP'
                gross = (exit_px - t['entry']) * t['size'] if t['dir']=='BUY' else (t['entry'] - exit_px) * t['size']
                eot = t.get('entry_ot', 'maker'); xot = 'maker' if reason == 'TP' else 'taker'
                net, fee = net_pnl(gross, t['entry'], exit_px, t['size'], exchange, entry_order_type=eot, exit_order_type=xot)
                balance += net; peak = max(peak, balance)
                k = (t['strategy'], asset)
                stats[k]['trades'] += 1; stats[k]['pnl_net'] += net
                stats[k]['pnl_gross'] += gross; stats[k]['fees'] += fee
                if net > 0: stats[k]['wins'] += 1
                open_trades.remove(t)

        # Halt check
        dd = (peak - balance) / peak if peak > 0 else 0
        if dd >= 0.10: continue

        # Generate signals
        window = df.iloc[max(0, i - 200):i + 1].copy()
        try:
            ind = indicators.calculate(window, asset, '1h')
        except: continue
        if ind is None: continue
        if ind.atr_pct < profile.min_atr_pct: continue
        regime = classify_market_regime(ind)
        if not (regime.allow_trend or regime.allow_breakout or regime.allow_grid): continue

        for s in engine.strategies:
            if not strategy_allowed_in_regime(s.NAME, regime): continue
            try: res = s.score(ind, window)
            except:
                try: res = s.score(ind)
                except: continue
            if res['direction'] == 'NEUTRAL': continue
            score = res.get('score', 0)
            stats[(s.NAME, asset)]['signals'] += 1
            if score < 70: stats[(s.NAME, asset)]['rejected'] += 1; continue

            sl_d = abs(price * ind.atr_pct * profile.sl_multiplier)
            tp_d = abs(price * ind.atr_pct * profile.tp_multiplier)
            sl, tp = (price - sl_d, price + tp_d) if res['direction']=='BUY' else (price + sl_d, price - tp_d)
            ru = abs(price - sl)
            if ru == 0: continue
            sz = (balance * 0.005) / ru
            if sz * price > balance * 0.50: sz = (balance * 0.50) / price
            gp = abs(tp - price) / price; rp = ru / price
            if rp == 0: continue
            if gp / rp < 1.5: stats[(s.NAME, asset)]['rejected'] += 1; continue
            cp = round_trip_cost_pct(exchange, 'maker', 'taker')
            if (gp - cp) / rp < MIN_NET_RR_RATIO: stats[(s.NAME, asset)]['rejected'] += 1; continue
            pending['%s-%d-%s'%(asset,i,s.NAME)] = {'strategy':s.NAME,'dir':res['direction'],'entry':price,'sl':sl,'tp':tp,'size':sz,'limit':price,'idx':i,'entry_ot':'maker'}

# ─── Print results ─────────────────────────────────────────────────
print('\n' + '=' * 95)
print(' BACKTEST 12d (300 candles/asset) — OKX maker 0.10% + TP maker | Net RR min: 1.0')
print('=' * 95)

rows = []
for (strat, asset), s in stats.items():
    if s['trades'] == 0 and s['signals'] == 0: continue
    n = s['trades']; w = s['wins']
    rows.append({'strategy': strat, 'asset': asset, 'signals': s['signals'], 'rejected': s['rejected'],
                 'trades': n, 'wins': w, 'wr': w/n*100 if n else 0,
                 'gross': s['pnl_gross'], 'net': s['pnl_net'], 'fees': s['fees'],
                 'edge': s['pnl_net']/n if n else 0, 'fills': s['fills'], 'tos': s['tos']})

if not rows:
    print('\n  No trades generated.')
    sys.exit(0)

df = pd.DataFrame(rows)

print('\n  BY ASSET')
print('  ' + '-' * 88)
ba = df.groupby('asset').agg(s=('signals','sum'),t=('trades','sum'),w=('wins','sum'),g=('gross','sum'),n=('net','sum'),f=('fees','sum'),fi=('fills','sum'),to=('tos','sum')).sort_values('n')
for a, r in ba.iterrows():
    tn = int(r['t'])
    if tn == 0: continue
    tag = 'G' if r['n'] > 0 else 'R'
    print('  [%s] %-6s %3dt WR=%5.1f%% | Gross=$%+8.2f Fees=$%7.2f Net=$%+8.2f | fills=%d tos=%d' % (
        tag, a, tn, r['w']/tn*100, r['g'], r['f'], r['n'], int(r['fi']), int(r['to'])))

print('\n  BY STRATEGY')
print('  ' + '-' * 88)
bs = df.groupby('strategy').agg(s=('signals','sum'),t=('trades','sum'),w=('wins','sum'),g=('gross','sum'),n=('net','sum'),f=('fees','sum')).sort_values('n')
for s, r in bs.iterrows():
    tn = int(r['t'])
    if tn == 0: continue
    tag = 'G' if r['n'] > 0 else 'R'
    print('  [%s] %-25s sigs=%4d %3dt WR=%5.1f%% | Net=$%+8.2f | Edge=$%+.4f/trade' % (
        tag, s, int(r['s']), tn, r['w']/tn*100, r['n'], r['n']/tn))

t = int(df['trades'].sum()); n = df['net'].sum(); g = df['gross'].sum(); f = df['fees'].sum()
fi = int(df['fills'].sum()); to = int(df['tos'].sum()); sig = int(df['signals'].sum()); rej = int(df['rejected'].sum())
wins = int(df['wins'].sum())

print('\n  TOTALS')
print('  ' + '-' * 88)
print('  Signals: %d | Rejected: %d (%d%%)' % (sig, rej, rej*100//sig if sig else 0))
if fi + to > 0:
    print('  Maker: %d fills / %d timeouts (%.0f%% fill rate)' % (fi, to, fi*100/(fi+to) if fi+to else 0))
print('  Trades: %d | Win rate: %.1f%%' % (t, wins*100/t if t else 0))
print('  Gross PnL: $%+.2f | Fees: $%.2f | Net PnL: $%+.2f' % (g, f, n))
if t > 0:
    print('  Avg net/trade: $%+.4f | Return on $500: %+.1f%%' % (n/t, n/500*100))
print('=' * 95)
