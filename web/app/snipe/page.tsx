import { api } from '@/lib/api'
import { fmt, fmtPnl, fmtPct, pnlClass } from '@/lib/fmt'
import { clsx } from 'clsx'

export const revalidate = 30

export default async function SnipePage() {
  const [tradesRes, statsRes] = await Promise.allSettled([
    api.snipe(200),
    api.snipeStats(),
  ])

  const trades = tradesRes.status === 'fulfilled' ? tradesRes.value : []
  const stats = statsRes.status === 'fulfilled' ? statsRes.value : {}

  const closed = trades.filter((t: any) => t.status === 'CLOSED')
  const open = trades.filter((t: any) => t.status === 'OPEN')
  const winners = closed.filter((t: any) => t.outcome === 'WIN').length
  const totalPnl = closed.reduce((s: number, t: any) => s + (t.pnl_usdc || 0), 0)
  const wr = closed.length > 0 ? winners / closed.length * 100 : 0
  const snipeTrades = trades.filter((t: any) => t.strategy === 'SNIPE').length
  const arbTrades = trades.filter((t: any) => t.strategy === 'ARB').length

  return (
    <div className="space-y-6 animate-[fadeIn_0.4s_ease-out]">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">PolySnipe — SNIPE + ARB</h1>
          <p className="text-sm text-muted mt-1">
            Late-entry Up/Down 15m · WR documentado 94% · Reemplaza BTC Direction
          </p>
        </div>
        <span className="badge badge-green text-xs">🎯 v1 — PAPER</span>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3">
        {[
          ['Balance', `$${fmt(stats.balance ?? 500, 0)}`, 'text-white'],
          ['P&L', fmtPnl(totalPnl), pnlClass(totalPnl)],
          ['Win Rate', fmtPct(wr), wr >= 80 ? 'pos' : wr >= 50 ? 'text-gold' : 'neg'],
          ['SNIPE Trades', snipeTrades, 'text-blue'],
          ['ARB Trades', arbTrades, 'text-purple'],
          ['Abiertos', open.length, open.length > 0 ? 'text-gold' : 'text-muted'],
        ].map(([label, value, cls]) => (
          <div key={label as string} className="card text-center">
            <div className="text-[10px] text-muted uppercase tracking-wider mb-1">{label as string}</div>
            <div className={clsx('text-base font-mono font-bold', cls as string)}>{value}</div>
          </div>
        ))}
      </div>

      {/* Open positions */}
      {open.length > 0 && (
        <div className="card">
          <div className="text-xs text-muted uppercase tracking-wider mb-3">
            🔓 Posiciones Abiertas <span className="ml-2 badge badge-gold">{open.length}</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-muted text-left border-b border-border">
                  <th className="pb-2 pr-4 font-normal">Asset</th>
                  <th className="pb-2 pr-4 font-normal">Estrategia</th>
                  <th className="pb-2 pr-4 font-normal">Dir</th>
                  <th className="pb-2 pr-4 font-normal">Entrada</th>
                  <th className="pb-2 pr-4 font-normal">Shares</th>
                  <th className="pb-2 pr-4 font-normal">Costo</th>
                  <th className="pb-2 pr-4 font-normal">Move %</th>
                  <th className="pb-2 font-normal">Apertura</th>
                </tr>
              </thead>
              <tbody>
                {open.map((t: any, i: number) => (
                  <tr key={i} className="border-b border-border/30 hover:bg-white/2">
                    <td className="py-2 pr-4 font-mono text-white">{t.asset}</td>
                    <td className="py-2 pr-4">
                      <span className={`badge ${t.strategy === 'SNIPE' ? 'badge-blue' : 'badge-purple'}`}>
                        {t.strategy}
                      </span>
                    </td>
                    <td className="py-2 pr-4">
                      <span className={clsx('badge', t.direction === 'UP' ? 'badge-green' : 'badge-red')}>
                        {t.direction}
                      </span>
                    </td>
                    <td className="py-2 pr-4 font-mono text-muted">${fmt(t.entry_price, 4)}</td>
                    <td className="py-2 pr-4 font-mono text-muted">{t.shares}</td>
                    <td className="py-2 pr-4 font-mono text-muted">${fmt(t.cost_usdc)}</td>
                    <td className={clsx('py-2 pr-4 font-mono', Number(t.move_pct) >= 0 ? 'pos' : 'neg')}>
                      {t.move_pct ? `${Number(t.move_pct) >= 0 ? '+' : ''}${fmt(t.move_pct, 3)}%` : '—'}
                    </td>
                    <td className="py-2 font-mono text-muted text-[10px]">
                      {t.timestamp_open ? new Date(t.timestamp_open).toLocaleString('es') : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Historial */}
      <div className="card">
        <div className="text-xs text-muted uppercase tracking-wider mb-3">
          🔒 Historial de Trades <span className="ml-2 badge badge-muted">{closed.length}</span>
        </div>
        {closed.length === 0 ? (
          <div className="text-sm text-muted text-center py-8">
            Sin trades cerrados aún — esperando ventanas min 13-14.5
          </div>
        ) : (
          <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-muted text-left border-b border-border sticky top-0 bg-surface">
                  <th className="pb-2 pr-4 font-normal">Asset</th>
                  <th className="pb-2 pr-4 font-normal">Estrategia</th>
                  <th className="pb-2 pr-4 font-normal">Dir</th>
                  <th className="pb-2 pr-4 font-normal">Entrada</th>
                  <th className="pb-2 pr-4 font-normal">Outcome</th>
                  <th className="pb-2 pr-4 font-normal">P&L</th>
                  <th className="pb-2 pr-4 font-normal">Move %</th>
                  <th className="pb-2 font-normal">Cerrado</th>
                </tr>
              </thead>
              <tbody>
                {closed.slice(0, 200).map((t: any, i: number) => (
                  <tr key={i} className="border-b border-border/30 hover:bg-white/2">
                    <td className="py-2 pr-4 font-mono text-white">{t.asset}</td>
                    <td className="py-2 pr-4">
                      <span className={`badge ${t.strategy === 'SNIPE' ? 'badge-blue' : 'badge-purple'}`}>
                        {t.strategy}
                      </span>
                    </td>
                    <td className="py-2 pr-4">
                      <span className={clsx('badge', t.direction === 'UP' ? 'badge-green' : t.direction === 'BOTH' ? 'badge-gold' : 'badge-red')}>
                        {t.direction}
                      </span>
                    </td>
                    <td className="py-2 pr-4 font-mono text-muted">${fmt(t.entry_price, 4)}</td>
                    <td className="py-2 pr-4">
                      <span className={`badge ${t.outcome === 'WIN' ? 'badge-green' : 'badge-red'}`}>
                        {t.outcome}
                      </span>
                    </td>
                    <td className={clsx('py-2 pr-4 font-mono font-semibold', pnlClass(t.pnl_usdc))}>
                      {fmtPnl(t.pnl_usdc)}
                    </td>
                    <td className={clsx('py-2 pr-4 font-mono', Number(t.move_pct) >= 0 ? 'pos' : 'neg')}>
                      {t.move_pct ? `${Number(t.move_pct) >= 0 ? '+' : ''}${fmt(t.move_pct, 3)}%` : '—'}
                    </td>
                    <td className="py-2 font-mono text-muted text-[10px]">
                      {t.timestamp_close ? new Date(t.timestamp_close).toLocaleString('es') : '—'}
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
