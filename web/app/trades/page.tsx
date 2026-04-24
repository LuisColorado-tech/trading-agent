import { api } from '@/lib/api'
import { fmt, fmtPnl, fmtPct, pnlClass, timeAgo } from '@/lib/fmt'
import { clsx } from 'clsx'

export const revalidate = 30

export default async function TradesPage() {
  const [stocksRes, cryptoRes] = await Promise.allSettled([
    api.stocksTrades('limit=100'),
    api.cryptoTrades(),
  ])

  const stocksTrades = stocksRes.status === 'fulfilled' ? stocksRes.value : []
  const cryptoTrades = cryptoRes.status === 'fulfilled' ? cryptoRes.value : []

  // Unified + sorted
  const all = [
    ...stocksTrades.map((t: any) => ({ ...t, _agent: 'stocks', ts: t.opened_at, asset: t.symbol })),
    ...cryptoTrades.map((t: any) => ({ ...t, _agent: 'crypto', ts: t.timestamp_open })),
  ].sort((a, b) => new Date(b.ts).getTime() - new Date(a.ts).getTime())

  return (
    <div className="space-y-6 animate-[fadeIn_0.4s_ease-out]">
      <div>
        <h1 className="text-2xl font-bold text-white">Diario de Trades</h1>
        <p className="text-sm text-muted mt-1">Historial unificado — Stocks + Crypto</p>
      </div>

      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[10px] text-muted uppercase tracking-wider border-b border-border">
              <th className="pb-3 pr-4">Agente</th>
              <th className="pb-3 pr-4">Activo</th>
              <th className="pb-3 pr-4">Dir.</th>
              <th className="pb-3 pr-4">Entrada</th>
              <th className="pb-3 pr-4">Salida</th>
              <th className="pb-3 pr-4">P&L</th>
              <th className="pb-3 pr-4">Razón</th>
              <th className="pb-3 pr-4">Estado</th>
              <th className="pb-3">Hace</th>
            </tr>
          </thead>
          <tbody>
            {all.slice(0, 100).map((t: any, i) => {
              const pnl = t.pnl
              return (
                <tr key={i} className="border-b border-border/50 hover:bg-white/2 transition-colors">
                  <td className="py-2 pr-4">
                    <span className={`badge ${t._agent === 'stocks' ? 'badge-green' : 'badge-blue'}`}>
                      {t._agent === 'stocks' ? '📈 Stocks' : '₿ Crypto'}
                    </span>
                  </td>
                  <td className="py-2 pr-4 font-mono font-bold text-white">{t.asset ?? t.symbol ?? t.pair}</td>
                  <td className="py-2 pr-4">
                    <span className={`badge ${t.direction === 'BUY' ? 'badge-green' : 'badge-red'}`}>
                      {t.direction}
                    </span>
                  </td>
                  <td className="py-2 pr-4 font-mono text-muted">${fmt(t.entry_price)}</td>
                  <td className="py-2 pr-4 font-mono text-muted">{t.exit_price ? `$${fmt(t.exit_price)}` : '—'}</td>
                  <td className={clsx('py-2 pr-4 font-mono font-semibold', pnl != null ? pnlClass(pnl) : 'neutral')}>
                    {pnl != null ? fmtPnl(pnl) : '—'}
                  </td>
                  <td className="py-2 pr-4 text-muted text-xs">{t.exit_reason ?? '—'}</td>
                  <td className="py-2 pr-4">
                    <span className={`badge ${t.status === 'OPEN' ? 'badge-gold' : t.status === 'CLOSED' ? 'badge-muted' : 'badge-muted'}`}>
                      {t.status}
                    </span>
                  </td>
                  <td className="py-2 text-xs text-muted">{timeAgo(t.ts)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {all.length === 0 && (
          <div className="text-center text-muted text-sm py-12">No hay trades registrados</div>
        )}
      </div>
    </div>
  )
}
