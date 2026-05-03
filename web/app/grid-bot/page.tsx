import { api } from '@/lib/api'
import { fmt, fmtPnl, fmtPct, pnlClass } from '@/lib/fmt'
import { clsx } from 'clsx'

export const revalidate = 30

export default async function GridBotPage() {
  const [statsRes, tradesRes, byAssetRes] = await Promise.allSettled([
    api.cryptoByStrategy(),
    api.cryptoStrategyTrades('GRID_BOT'),
    api.cryptoByAsset(),
  ])

  const allStats = statsRes.status === 'fulfilled' ? statsRes.value : {}
  const st = allStats['GRID_BOT'] ?? {}
  const trades = tradesRes.status === 'fulfilled' ? tradesRes.value : []
  const byAsset = byAssetRes.status === 'fulfilled' ? byAssetRes.value : []

  const gridAssets = byAsset.filter((r: any) => r.strategy === 'GRID_BOT')

  const closed = trades.filter((t: any) => t.status === 'CLOSED')
  const open = trades.filter((t: any) => t.status === 'OPEN')
  const tpCount = closed.filter((t: any) => t.close_reason === 'TAKE_PROFIT').length
  const slCount = closed.filter((t: any) => t.close_reason === 'STOP_LOSS').length
  const trCount = closed.filter((t: any) => t.close_reason === 'TRAILING_STOP').length

  return (
    <div className="space-y-6 animate-[fadeIn_0.4s_ease-out]">
      <div>
        <h1 className="text-2xl font-bold text-white tracking-tight">Grid Bot — Crypto Range</h1>
        <p className="text-sm text-muted mt-1">
          GRID_BOT · 7 activos · régimen RANGE/CHOPPY · cooldown post-SL · BUY+SELL
        </p>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3">
        {[
          ['P&L', fmtPnl(st.total_pnl ?? 0), pnlClass(st.total_pnl ?? 0)],
          ['Win Rate', fmtPct(st.win_rate ?? 0), 'text-white'],
          ['Profit Factor', fmt(st.profit_factor ?? 0), (st.profit_factor ?? 0) >= 1.3 ? 'pos' : 'text-gold'],
          ['Trades', st.total_trades ?? 0, 'text-white'],
          ['Abiertos', st.open_trades ?? 0, 'text-blue'],
          ['Avg Win/Loss', `+$${fmt(st.avg_win ?? 0, 0)}/-$${fmt(Math.abs(st.avg_loss ?? 0), 0)}`, 'text-muted'],
        ].map(([label, value, cls]) => (
          <div key={label as string} className="card text-center">
            <div className="text-[10px] text-muted uppercase tracking-wider mb-1">{label as string}</div>
            <div className={clsx('text-base font-mono font-bold', cls as string)}>{value}</div>
          </div>
        ))}
      </div>

      {/* Cierres por motivo */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div className="card">
          <div className="text-xs text-muted uppercase tracking-wider mb-3">Cierres por motivo</div>
          <div className="space-y-2">
            {[
              ['TAKE_PROFIT', tpCount, 'pos'],
              ['STOP_LOSS', slCount, 'neg'],
              ['TRAILING_STOP', trCount, 'text-gold'],
            ].map(([label, count, cls]) => (
              <div key={label} className="flex justify-between items-center">
                <span className="text-sm">{label}</span>
                <span className={clsx('text-sm font-mono font-bold', cls)}>{count}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Performance por asset */}
        <div className="card xl:col-span-2">
          <div className="text-xs text-muted uppercase tracking-wider mb-3">Performance por Asset (GRID_BOT)</div>
          <div className="overflow-hidden">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-muted border-b border-white/5">
                  <th className="text-left py-1.5 font-medium">Asset</th>
                  <th className="text-right py-1.5 font-medium">Trades</th>
                  <th className="text-right py-1.5 font-medium">WR</th>
                  <th className="text-right py-1.5 font-medium">PnL</th>
                </tr>
              </thead>
              <tbody>
                {gridAssets.map((row: any) => (
                  <tr key={row.asset} className="border-b border-white/[0.02]">
                    <td className="py-1.5 font-mono text-white">{row.asset}</td>
                    <td className="py-1.5 text-right font-mono">{row.trades}</td>
                    <td className={clsx('py-1.5 text-right font-mono', row.wr >= 50 ? 'pos' : 'neg')}>
                      {fmtPct(row.wr)}
                    </td>
                    <td className={clsx('py-1.5 text-right font-mono', row.total_pnl > 0 ? 'pos' : 'neg')}>
                      {fmtPnl(row.total_pnl)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Últimos trades */}
      <div className="card">
        <div className="text-xs text-muted uppercase tracking-wider mb-3">
          Últimos {Math.min(closed.length, 20)} Trades Cerrados
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-muted border-b border-white/5">
                <th className="text-left py-1.5 font-medium">Asset</th>
                <th className="text-left py-1.5 font-medium">Dir</th>
                <th className="text-right py-1.5 font-medium">Entry</th>
                <th className="text-right py-1.5 font-medium">Exit</th>
                <th className="text-right py-1.5 font-medium">PnL</th>
                <th className="text-center py-1.5 font-medium">Close</th>
                <th className="text-right py-1.5 font-medium">Cuando</th>
              </tr>
            </thead>
            <tbody>
              {closed.slice(0, 20).map((t: any) => (
                <tr key={t.id} className="border-b border-white/[0.02] hover:bg-white/[0.02]">
                  <td className="py-1.5 font-mono text-white">{t.asset}</td>
                  <td className={clsx('py-1.5 font-mono', t.side === 'BUY' ? 'pos' : 'neg')}>{t.side}</td>
                  <td className="py-1.5 text-right font-mono">{fmt(t.entry_price, 4)}</td>
                  <td className="py-1.5 text-right font-mono">{fmt(t.exit_price, 4)}</td>
                  <td className={clsx('py-1.5 text-right font-mono', t.pnl > 0 ? 'pos' : 'neg')}>{fmtPnl(t.pnl)}</td>
                  <td className={clsx('py-1.5 text-center text-[10px]',
                    t.close_reason === 'TAKE_PROFIT' ? 'pos' : t.close_reason === 'TRAILING_STOP' ? 'text-gold' : 'neg')}>
                    {t.close_reason?.replace('_', ' ')}
                  </td>
                  <td className="py-1.5 text-right text-muted font-mono text-[10px]">
                    {t.timestamp_close ? new Date(t.timestamp_close).toLocaleDateString('es-CO', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
