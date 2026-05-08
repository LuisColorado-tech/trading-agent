import { api } from '@/lib/api'
import { fmt, fmtPnl, fmtPct, pnlClass } from '@/lib/fmt'
import { clsx } from 'clsx'

export const revalidate = 30

export default async function PolymarketPage() {
  const [sessionRes, posRes, statsRes] = await Promise.allSettled([
    api.polySession(),
    api.polyPositions('limit=200'),
    api.polyStats(),
  ])

  const sess = sessionRes.status === 'fulfilled' ? sessionRes.value : {}
  const pos = posRes.status === 'fulfilled' ? posRes.value : []
  const st = statsRes.status === 'fulfilled' ? statsRes.value : {}

  const open = pos.filter((p: any) => p.status === 'OPEN')
  const closed = pos.filter((p: any) => p.status === 'CLOSED')

  return (
    <div className="space-y-6 animate-[fadeIn_0.4s_ease-out]">
      <div>
        <h1 className="text-2xl font-bold text-white tracking-tight">Polymarket — Prediction Markets</h1>
        <p className="text-sm text-muted mt-1">
          {sess.session_name ?? '—'} · v3 edge fix · min=0.42
        </p>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-6 gap-3">
        {[
          ['Balance', `$${fmt(st.balance ?? sess.current_balance ?? sess.initial_balance ?? 0, 0)}`, 'text-white'],
          ['P&L', fmtPnl(st.total_pnl), pnlClass(st.total_pnl)],
          ['Win Rate', fmtPct(st.win_rate), 'text-white'],
          ['PF', fmt(st.profit_factor), (st.profit_factor ?? 0) >= 1.3 ? 'pos' : 'text-gold'],
          ['Trades', st.total ?? 0, 'text-white'],
          ['Abiertos', open.length, open.length > 0 ? 'text-purple' : 'text-muted'],
        ].map(([label, value, cls]) => (
          <div key={label as string} className="card text-center">
            <div className="text-[10px] text-muted uppercase tracking-wider mb-1">{label as string}</div>
            <div className={clsx('text-base font-mono font-bold', cls as string)}>{value}</div>
          </div>
        ))}
      </div>

      {/* Open positions */}
      <div className="card">
        <div className="text-xs text-muted uppercase tracking-wider mb-3">
          Posiciones Abiertas
          {open.length > 0 && <span className="ml-2 badge badge-purple">{open.length}</span>}
        </div>
        {open.length === 0 ? (
          <div className="text-sm text-muted text-center py-8">Sin posiciones abiertas</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-muted text-left border-b border-border">
                  <th className="pb-2 pr-4 font-normal">Evento</th>
                  <th className="pb-2 pr-4 font-normal">Outcome</th>
                  <th className="pb-2 pr-4 font-normal">Side</th>
                  <th className="pb-2 pr-4 font-normal">Entrada</th>
                  <th className="pb-2 pr-4 font-normal">Size</th>
                  <th className="pb-2 pr-4 font-normal">Apertura</th>
                </tr>
              </thead>
              <tbody>
                {open.map((p: any, i: number) => (
                  <tr key={i} className="border-b border-border/30 hover:bg-white/2">
                    <td className="py-2 pr-4 font-mono text-white max-w-[200px] truncate">{p.event_title ?? p.slug}</td>
                    <td className="py-2 pr-4 font-mono text-muted">{p.outcome}</td>
                    <td className="py-2 pr-4">
                      <span className={`badge ${p.side === 'BUY' ? 'badge-green' : 'badge-red'}`}>
                        {p.side}
                      </span>
                    </td>
                    <td className="py-2 pr-4 font-mono text-muted">${fmt(p.entry_price)}</td>
                    <td className="py-2 pr-4 font-mono text-white">${fmt(p.size)}</td>
                    <td className="py-2 font-mono text-muted">
                      {p.timestamp_open ? new Date(p.timestamp_open).toLocaleDateString('es') : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Closed trades */}
      <div className="card">
        <div className="text-xs text-muted uppercase tracking-wider mb-3">
          Historial de Trades
          <span className="ml-2 badge badge-muted">{closed.length}</span>
        </div>
        {closed.length === 0 ? (
          <div className="text-sm text-muted text-center py-8">Sin trades cerrados</div>
        ) : (
          <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-muted text-left border-b border-border sticky top-0 bg-surface">
                  <th className="pb-2 pr-4 font-normal">Evento</th>
                  <th className="pb-2 pr-4 font-normal">Outcome</th>
                  <th className="pb-2 pr-4 font-normal">Side</th>
                  <th className="pb-2 pr-4 font-normal">Entrada</th>
                  <th className="pb-2 pr-4 font-normal">Salida</th>
                  <th className="pb-2 pr-4 font-normal">P&L</th>
                  <th className="pb-2 pr-4 font-normal">Razón</th>
                  <th className="pb-2 font-normal">Fecha</th>
                </tr>
              </thead>
              <tbody>
                {closed.slice(0, 100).map((p: any, i: number) => (
                  <tr key={i} className="border-b border-border/30 hover:bg-white/2">
                    <td className="py-2 pr-4 font-mono text-white max-w-[180px] truncate">{p.event_title ?? p.slug}</td>
                    <td className="py-2 pr-4 font-mono text-muted">{p.outcome}</td>
                    <td className="py-2 pr-4">
                      <span className={`badge ${p.side === 'BUY' ? 'badge-green' : 'badge-red'}`}>
                        {p.side}
                      </span>
                    </td>
                    <td className="py-2 pr-4 font-mono text-muted">${fmt(p.entry_price)}</td>
                    <td className="py-2 pr-4 font-mono text-muted">
                      {p.close_price != null ? `$${fmt(p.close_price)}` : '—'}
                    </td>
                    <td className={clsx('py-2 pr-4 font-mono font-semibold', pnlClass(p.pnl))}>
                      {fmtPnl(p.pnl)}
                    </td>
                    <td className="py-2 pr-4 text-muted">{p.close_reason ?? '—'}</td>
                    <td className="py-2 text-muted font-mono">
                      {p.timestamp_close ? new Date(p.timestamp_close).toLocaleDateString('es') : '—'}
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
