import { api } from '@/lib/api'
import MiniEquity from '@/components/MiniEquity'
import { fmt, fmtPnl, fmtPct } from '@/lib/fmt'
import { clsx } from 'clsx'

export const revalidate = 30

export default async function CryptoPage() {
  const [pf, byStratRes, history, tradesRes, signals, byAssetRes] = await Promise.allSettled([
    api.cryptoPortfolio(),
    api.cryptoByStrategy(),
    api.cryptoHistory(),
    api.cryptoStrategyTrades('TREND_MOMENTUM'),
    api.cryptoSignals(),
    api.cryptoByAsset(),
  ])

  const portfolio = pf.status === 'fulfilled' ? pf.value : {}
  const allStats = byStratRes.status === 'fulfilled' ? byStratRes.value : {}
  const hist = history.status === 'fulfilled' ? history.value : []
  const tr = tradesRes.status === 'fulfilled' ? tradesRes.value : []
  const sig = signals.status === 'fulfilled' ? signals.value : []
  const byAsset = byAssetRes.status === 'fulfilled' ? byAssetRes.value : []

  const st = allStats['TREND_MOMENTUM'] ?? {}
  const tmAssets = byAsset.filter((r: any) => r.strategy === 'TREND_MOMENTUM')

  const dd = (portfolio.drawdown_pct ?? 0) * 100
  const closed = tr.filter((t: any) => t.status === 'CLOSED')

  return (
    <div className="space-y-6 animate-[fadeIn_0.4s_ease-out]">
      <div>
        <h1 className="text-2xl font-bold text-white tracking-tight">Crypto — TrendMomentum</h1>
        <p className="text-sm text-muted mt-1">
          TREND_MOMENTUM SELL · MIN_SCORE=75 · MAX_CONC=2 · trailing 0.75R · 7 activos
        </p>
      </div>

      {/* KPIs — TrendMomentum */}
      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3">
        {[
          ['Balance', `$${fmt(portfolio.total_balance, 0)}`, 'text-white'],
          ['P&L', fmtPnl(st.total_pnl ?? 0), (st.total_pnl ?? 0) >= 0 ? 'pos' : 'neg'],
          ['Win Rate', fmtPct(st.win_rate ?? 0), 'text-white'],
          ['PF', fmt(st.profit_factor ?? 0), (st.profit_factor ?? 0) >= 1.3 ? 'pos' : 'text-gold'],
          ['DD', `-${fmtPct(dd)}`, dd > 5 ? 'neg' : 'pos'],
          ['Trades', st.total_trades ?? 0, 'text-white'],
          ['Avg Win', `$${fmt(st.avg_win ?? 0, 0)}`, 'pos'],
          ['Avg Loss', `-$${fmt(Math.abs(st.avg_loss ?? 0), 0)}`, 'neg'],
        ].map(([label, value, cls]) => (
          <div key={label as string} className="card text-center">
            <div className="text-[10px] text-muted uppercase tracking-wider mb-1">{label as string}</div>
            <div className={clsx('text-base font-mono font-bold', cls as string)}>{value}</div>
          </div>
        ))}
      </div>

      {/* Equity + Performance por Asset */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div className="card xl:col-span-2">
          <div className="text-xs text-muted uppercase tracking-wider mb-3">Equity Curve (todo el portfolio)</div>
          <MiniEquity data={hist} dataKey="total_balance" color="#58A6FF" height={200} />
        </div>
        <div className="card">
          <div className="text-xs text-muted uppercase tracking-wider mb-3">Por Asset (TrendMomentum)</div>
          <div className="space-y-1 max-h-[200px] overflow-y-auto">
            {tmAssets.map((r: any) => (
              <div key={r.asset} className="flex justify-between items-center text-xs py-1 border-b border-white/5 last:border-0">
                <span className="font-mono text-white w-10">{r.asset}</span>
                <span className="font-mono text-muted w-8 text-right">{r.trades}</span>
                <span className={clsx('font-mono w-12 text-right', r.wr >= 50 ? 'pos' : 'neg')}>{fmtPct(r.wr)}</span>
                <span className={clsx('font-mono w-16 text-right', r.total_pnl > 0 ? 'pos' : 'neg')}>{fmtPnl(r.total_pnl)}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Últimos trades TrendMomentum */}
      <div className="card">
        <div className="text-xs text-muted uppercase tracking-wider mb-3">
          Últimos {Math.min(closed.length, 20)} Trades — TrendMomentum
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-muted border-b border-white/5">
                <th className="text-left py-1.5 font-medium">Asset</th>
                <th className="text-left py-1.5 font-medium">Dir</th>
                <th className="text-right py-1.5 font-medium">Entry</th>
                <th className="text-right py-1.5 font-medium">Exit</th>
                <th className="text-right py-1.5 font-medium">SL</th>
                <th className="text-right py-1.5 font-medium">TP</th>
                <th className="text-right py-1.5 font-medium">PnL</th>
                <th className="text-center py-1.5 font-medium">Reason</th>
              </tr>
            </thead>
            <tbody>
              {closed.slice(0, 20).map((t: any) => (
                <tr key={t.id} className="border-b border-white/[0.02] hover:bg-white/[0.02]">
                  <td className="py-1.5 font-mono text-white">{t.asset}</td>
                  <td className={clsx('py-1.5 font-mono text-[10px]', t.side === 'BUY' ? 'pos' : 'neg')}>{t.side}</td>
                  <td className="py-1.5 text-right font-mono">{fmt(t.entry_price, 2)}</td>
                  <td className="py-1.5 text-right font-mono">{fmt(t.exit_price, 2)}</td>
                  <td className="py-1.5 text-right font-mono text-muted">{fmt(t.stop_loss, 2)}</td>
                  <td className="py-1.5 text-right font-mono text-muted">{fmt(t.take_profit, 2)}</td>
                  <td className={clsx('py-1.5 text-right font-mono', t.pnl > 0 ? 'pos' : 'neg')}>{fmtPnl(t.pnl)}</td>
                  <td className={clsx('py-1.5 text-center text-[10px]',
                    t.close_reason === 'TAKE_PROFIT' ? 'pos' : t.close_reason === 'TRAILING_STOP' ? 'text-gold' : 'neg')}>
                    {t.close_reason?.replace('_', ' ')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Señales recientes */}
      <div className="card">
        <div className="text-xs text-muted uppercase tracking-wider mb-3">Señales Recientes</div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-muted text-left">
                <th className="pb-2 font-normal">Asset</th>
                <th className="pb-2 font-normal">TF</th>
                <th className="pb-2 font-normal">Tipo</th>
                <th className="pb-2 font-normal">Dir</th>
                <th className="pb-2 font-normal">Score</th>
                <th className="pb-2 font-normal">Hora</th>
              </tr>
            </thead>
            <tbody>
              {sig.slice(0, 20).map((s: any, i: number) => (
                <tr key={i} className="border-t border-border/30">
                  <td className="py-1.5 font-mono text-white">{s.asset}</td>
                  <td className="py-1.5 font-mono text-muted">{s.timeframe}</td>
                  <td className="py-1.5 font-mono text-muted">{s.signal_type}</td>
                  <td className={clsx('py-1.5 font-mono', s.direction === 'SELL' ? 'neg' : 'pos')}>{s.direction}</td>
                  <td className="py-1.5 font-mono text-white">{fmt(s.score, 1)}</td>
                  <td className="py-1.5 font-mono text-muted">{new Date(s.timestamp).toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' })}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
