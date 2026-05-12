import { api } from '@/lib/api'
import { fmt, fmtPnl, fmtPct, pnlClass, timeAgo } from '@/lib/fmt'
import { clsx } from 'clsx'

export const revalidate = 30

export default async function BtcDirectionPage() {
  const [tradesRes] = await Promise.allSettled([
    api.btcDirection(200),
  ])

  const trades = tradesRes.status === 'fulfilled' ? tradesRes.value : []

  const closed = trades.filter((t: any) => t.status === 'CLOSED')
  const open = trades.filter((t: any) => t.status === 'OPEN')
  const winners = closed.filter((t: any) => t.pnl_usdc > 0).length
  const totalPnl = closed.reduce((s: number, t: any) => s + (t.pnl_usdc || 0), 0)
  const gp = closed.filter((t: any) => t.pnl_usdc > 0).reduce((s: number, t: any) => s + t.pnl_usdc, 0)
  const gl = Math.abs(closed.filter((t: any) => t.pnl_usdc < 0).reduce((s: number, t: any) => s + t.pnl_usdc, 0))
  const wr = closed.length > 0 ? winners / closed.length * 100 : 0
  const pf = gl > 0 ? gp / gl : 0

  // Group by timeframe
  const tfMap: Record<string, { trades: number; winners: number; pnl: number }> = {}
  closed.forEach((t: any) => {
    const tf = t.timeframe ?? '?'
    if (!tfMap[tf]) tfMap[tf] = { trades: 0, winners: 0, pnl: 0 }
    tfMap[tf].trades++
    if (t.pnl_usdc > 0) tfMap[tf].winners++
    tfMap[tf].pnl += t.pnl_usdc || 0
  })

  return (
    <div className="space-y-6 animate-[fadeIn_0.4s_ease-out]">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-white tracking-tight">BTC Direction</h1>
          <p className="text-sm text-muted mt-1">
            Señales direccionales BTC · {wr < 40 ? '⚠ Bajo vigilancia' : 'Operativo normal'}
          </p>
        </div>
        {wr < 40 && (
          <span className="badge badge-red text-xs">⚠ WR &lt; 40% — bajo vigilancia</span>
        )}
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-6 gap-3">
        {[
          ['Balance', `$${fmt(171 + totalPnl, 0)}`, 'text-white'],
          ['P&L', fmtPnl(totalPnl), pnlClass(totalPnl)],
          ['Win Rate', fmtPct(wr), wr < 40 ? 'neg' : 'text-white'],
          ['PF', fmt(pf), pf >= 1.3 ? 'pos' : pf >= 1.0 ? 'text-gold' : 'neg'],
          ['Trades Cerrados', closed.length, 'text-white'],
          ['Abiertos', open.length, open.length > 0 ? 'text-blue' : 'text-muted'],
        ].map(([label, value, cls]) => (
          <div key={label as string} className="card text-center">
            <div className="text-[10px] text-muted uppercase tracking-wider mb-1">{label as string}</div>
            <div className={clsx('text-base font-mono font-bold', cls as string)}>{value}</div>
          </div>
        ))}
      </div>

      {/* Performance by timeframe */}
      {Object.keys(tfMap).length > 0 && (
        <div className="card">
          <div className="text-xs text-muted uppercase tracking-wider mb-3">WR por Timeframe</div>
          <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5 gap-3">
            {Object.entries(tfMap).map(([tf, data]) => {
              const tfwr = data.trades > 0 ? data.winners / data.trades * 100 : 0
              return (
                <div key={tf} className="text-center p-3 bg-bg rounded-lg border border-border">
                  <div className="text-xs font-mono text-white mb-1">{tf}</div>
                  <div className={clsx('text-lg font-mono font-bold', pnlClass(data.pnl))}>
                    {fmtPnl(data.pnl)}
                  </div>
                  <div className="text-[10px] text-muted mt-1">{fmtPct(tfwr)} WR · {data.trades} trades</div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Trades table */}
      <div className="card">
        <div className="text-xs text-muted uppercase tracking-wider mb-3">
          Historial de Trades
          <span className="ml-2 badge badge-muted">{trades.length}</span>
        </div>
        {trades.length === 0 ? (
          <div className="text-sm text-muted text-center py-8">Sin trades registrados</div>
        ) : (
          <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-muted text-left border-b border-border sticky top-0 bg-surface">
                  <th className="pb-2 pr-4 font-normal">Símbolo</th>
                  <th className="pb-2 pr-4 font-normal">TF</th>
                  <th className="pb-2 pr-4 font-normal">Dir</th>
                  <th className="pb-2 pr-4 font-normal">Entrada</th>
                  <th className="pb-2 pr-4 font-normal">Salida</th>
                  <th className="pb-2 pr-4 font-normal">Size</th>
                  <th className="pb-2 pr-4 font-normal">P&L</th>
                  <th className="pb-2 pr-4 font-normal">Estado</th>
                  <th className="pb-2 font-normal">Apertura</th>
                </tr>
              </thead>
              <tbody>
                {trades.slice(0, 200).map((t: any, i: number) => (
                  <tr key={i} className="border-b border-border/30 hover:bg-white/2">
                    <td className="py-2 pr-4 font-mono text-white">{t.symbol ?? 'BTC'}</td>
                    <td className="py-2 pr-4 font-mono text-muted">{t.timeframe ?? '—'}</td>
                    <td className="py-2 pr-4">
                      <span className={`badge ${t.direction === 'LONG' ? 'badge-green' : 'badge-red'}`}>
                        {t.direction ?? '—'}
                      </span>
                    </td>
                    <td className="py-2 pr-4 font-mono text-muted">${fmt(t.entry_price)}</td>
                    <td className="py-2 pr-4 font-mono text-muted">
                      {t.exit_price ? `$${fmt(t.exit_price)}` : '—'}
                    </td>
                    <td className="py-2 pr-4 font-mono text-muted">${fmt(t.size_usdc)}</td>
                    <td className={clsx('py-2 pr-4 font-mono font-semibold', pnlClass(t.pnl_usdc))}>
                      {fmtPnl(t.pnl_usdc)}
                    </td>
                    <td className="py-2 pr-4">
                      <span className={`badge ${t.status === 'OPEN' ? 'badge-gold' : 'badge-muted'}`}>
                        {t.status}
                      </span>
                    </td>
                    <td className="py-2 font-mono text-muted">
                      {t.timestamp_open ? new Date(t.timestamp_open).toLocaleDateString('es') : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
