import { api } from '@/lib/api'
import { fmt, fmtPnl, fmtPct, pnlClass, timeAgo } from '@/lib/fmt'
import { clsx } from 'clsx'

export const revalidate = 30

export default async function TradesPage() {
  const [stocksRes, cryptoRes, polyRes, btcRes] = await Promise.allSettled([
    api.stocksTrades('limit=100'),
    api.cryptoTrades(),
    api.polyPositions('limit=100&status=CLOSED'),
    api.btcDirection(100),
  ])

  const stocksTrades = stocksRes.status === 'fulfilled' ? stocksRes.value : []
  const cryptoTrades = cryptoRes.status === 'fulfilled' ? cryptoRes.value : []
  const polyTrades = polyRes.status === 'fulfilled' ? polyRes.value : []
  const btcTrades = btcRes.status === 'fulfilled' ? btcRes.value : []

  // Unified + sorted
  const all = [
    ...stocksTrades.map((t: any) => ({ ...t, _agent: 'stocks', ts: t.opened_at || t.closed_at, asset: t.symbol })),
    ...cryptoTrades.map((t: any) => ({ ...t, _agent: 'crypto', ts: t.timestamp_open || t.timestamp_close, asset: t.asset || t.pair })),
    ...polyTrades.map((t: any) => ({ ...t, _agent: 'polymarket', ts: t.timestamp_open || t.timestamp_close, asset: t.event_title || t.slug, pnl: t.pnl ?? 0 })),
    ...btcTrades.map((t: any) => ({ ...t, _agent: 'btc-direction', ts: t.timestamp_open || t.timestamp_close, asset: t.symbol ?? 'BTC', pnl: t.pnl_usdc ?? 0 })),
  ].sort((a, b) => new Date(b.ts).getTime() - new Date(a.ts).getTime())

  const agentBadge = (agent: string) => {
    const map: Record<string, { label: string; cls: string }> = {
      stocks:       { label: '📈 Stocks',      cls: 'badge-green' },
      crypto:       { label: '₿ Crypto',       cls: 'badge-blue' },
      polymarket:   { label: '🔮 Polymarket',  cls: 'badge-purple' },
      'btc-direction': { label: '₿ BTC Dir',   cls: 'badge-red' },
    }
    const m = map[agent] ?? { label: agent, cls: 'badge-muted' }
    return <span className={`badge ${m.cls}`}>{m.label}</span>
  }

  return (
    <div className="space-y-6 animate-[fadeIn_0.4s_ease-out]">
      <div>
        <h1 className="text-xl sm:text-2xl font-bold text-white">Diario de Trades</h1>
        <p className="text-sm text-muted mt-1">Historial unificado — Stocks · Crypto · Polymarket · BTC Direction · Options</p>
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
                    {agentBadge(t._agent)}
                  </td>
                  <td className="py-2 pr-4 font-mono font-bold text-white">{t.asset ?? t.symbol ?? t.pair ?? '—'}</td>
                  <td className="py-2 pr-4">
                    <span className={`badge ${t.direction === 'BUY' || t.direction === 'LONG' || t.side === 'BUY' ? 'badge-green' : 'badge-red'}`}>
                      {t.direction ?? t.side ?? '—'}
                    </span>
                  </td>
                  <td className="py-2 pr-4 font-mono text-muted">${fmt(t.entry_price)}</td>
                  <td className="py-2 pr-4 font-mono text-muted">{t.exit_price != null || t.close_price != null ? `$${fmt(t.exit_price ?? t.close_price)}` : '—'}</td>
                  <td className={clsx('py-2 pr-4 font-mono font-semibold', pnlClass(t.pnl ?? t.pnl_usdc))}>
                    {fmtPnl(t.pnl ?? t.pnl_usdc)}
                  </td>
                  <td className="py-2 pr-4 text-muted text-xs">{t.exit_reason ?? t.close_reason ?? '—'}</td>
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
