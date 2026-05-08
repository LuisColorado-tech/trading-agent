import { api } from '@/lib/api'
import { fmt, fmtPnl, fmtPct, pnlClass } from '@/lib/fmt'
import { clsx } from 'clsx'

export const revalidate = 30

export default async function OptionsPage() {
  const [sessionRes, posRes, statsRes] = await Promise.allSettled([
    api.optionsSession(),
    api.optionsPositions(),
    api.optionsStats(),
  ])

  const sess = sessionRes.status === 'fulfilled' ? sessionRes.value : {}
  const pos = posRes.status === 'fulfilled' ? posRes.value : []
  const st = statsRes.status === 'fulfilled' ? statsRes.value : {}

  const open = pos.filter((p: any) => p.status === 'OPEN')
  const closed = pos.filter((p: any) => p.status === 'CLOSED')

  const balance = sess.current_balance_usd ?? sess.initial_balance_usd ?? 2000
  const totalPremium = st.total_premium ?? 0
  const totalPnl = st.total_pnl ?? 0

  return (
    <div className="space-y-6 animate-[fadeIn_0.4s_ease-out]">
      <div>
        <h1 className="text-2xl font-bold text-white tracking-tight">Options — Deribit Theta Farming</h1>
        <p className="text-sm text-muted mt-1">
          {sess.session_name ?? 'Theta Farming'} · primas cobradas · IV rank · expiraciones
        </p>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-7 gap-3">
        {[
          ['Balance', `$${fmt(balance, 0)}`, 'text-white'],
          ['Primas', `$${fmt(totalPremium, 0)}`, 'text-gold'],
          ['P&L', fmtPnl(totalPnl), pnlClass(totalPnl)],
          ['Win Rate', fmtPct(st.win_rate), 'text-white'],
          ['Trades', st.total ?? 0, 'text-white'],
          ['Abiertos', open.length, open.length > 0 ? 'text-gold' : 'text-muted'],
          ['Sesión', sess.session_name ?? '—', 'text-blue'],
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
          {open.length > 0 && <span className="ml-2 badge badge-gold">{open.length}</span>}
        </div>
        {open.length === 0 ? (
          <div className="text-sm text-muted text-center py-8">Sin posiciones abiertas</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-muted text-left border-b border-border">
                  <th className="pb-2 pr-4 font-normal">Instrumento</th>
                  <th className="pb-2 pr-4 font-normal">Tipo</th>
                  <th className="pb-2 pr-4 font-normal">Strike</th>
                  <th className="pb-2 pr-4 font-normal">Expiración</th>
                  <th className="pb-2 pr-4 font-normal">Prima</th>
                  <th className="pb-2 pr-4 font-normal">Side</th>
                  <th className="pb-2 font-normal">Apertura</th>
                </tr>
              </thead>
              <tbody>
                {open.map((p: any, i: number) => (
                  <tr key={i} className="border-b border-border/30 hover:bg-white/2">
                    <td className="py-2 pr-4 font-mono text-white">{p.instrument_name ?? p.asset ?? '—'}</td>
                    <td className="py-2 pr-4 font-mono text-muted">{p.option_type ?? p.type ?? '—'}</td>
                    <td className="py-2 pr-4 font-mono text-white">${fmt(p.strike)}</td>
                    <td className="py-2 pr-4 font-mono text-muted">
                      {p.expiration_date ? new Date(p.expiration_date).toLocaleDateString('es') : '—'}
                    </td>
                    <td className="py-2 pr-4 font-mono text-gold">${fmt(p.entry_premium_usd)}</td>
                    <td className="py-2 pr-4">
                      <span className={`badge ${p.side === 'SELL' ? 'badge-red' : 'badge-green'}`}>
                        {p.side ?? '—'}
                      </span>
                    </td>
                    <td className="py-2 font-mono text-muted">
                      {p.opened_at ? new Date(p.opened_at).toLocaleDateString('es') : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Closed positions */}
      <div className="card">
        <div className="text-xs text-muted uppercase tracking-wider mb-3">
          Historial de Posiciones
          <span className="ml-2 badge badge-muted">{closed.length}</span>
        </div>
        {closed.length === 0 ? (
          <div className="text-sm text-muted text-center py-8">Sin posiciones cerradas</div>
        ) : (
          <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-muted text-left border-b border-border sticky top-0 bg-surface">
                  <th className="pb-2 pr-4 font-normal">Instrumento</th>
                  <th className="pb-2 pr-4 font-normal">Tipo</th>
                  <th className="pb-2 pr-4 font-normal">Strike</th>
                  <th className="pb-2 pr-4 font-normal">Prima</th>
                  <th className="pb-2 pr-4 font-normal">P&L</th>
                  <th className="pb-2 pr-4 font-normal">Expiración</th>
                  <th className="pb-2 font-normal">Cierre</th>
                </tr>
              </thead>
              <tbody>
                {closed.slice(0, 100).map((p: any, i: number) => (
                  <tr key={i} className="border-b border-border/30 hover:bg-white/2">
                    <td className="py-2 pr-4 font-mono text-white">{p.instrument_name ?? p.asset ?? '—'}</td>
                    <td className="py-2 pr-4 font-mono text-muted">{p.option_type ?? p.type ?? '—'}</td>
                    <td className="py-2 pr-4 font-mono text-white">${fmt(p.strike)}</td>
                    <td className="py-2 pr-4 font-mono text-gold">${fmt(p.entry_premium_usd)}</td>
                    <td className={clsx('py-2 pr-4 font-mono font-semibold', pnlClass(p.pnl_usd))}>
                      {fmtPnl(p.pnl_usd)}
                    </td>
                    <td className="py-2 pr-4 font-mono text-muted">
                      {p.expiration_date ? new Date(p.expiration_date).toLocaleDateString('es') : '—'}
                    </td>
                    <td className="py-2 font-mono text-muted">
                      {p.closed_at ? new Date(p.closed_at).toLocaleDateString('es') : '—'}
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
