import { api } from '@/lib/api'
import { fmt, fmtPnl, timeAgo } from '@/lib/fmt'
import { clsx } from 'clsx'

export const revalidate = 20

export default async function SignalsPage() {
  const [sigRes, stocksRes] = await Promise.allSettled([
    api.cryptoSignals(),
    api.stocksTrades('limit=50&status=OPEN'),
  ])

  const signals = sigRes.status === 'fulfilled' ? sigRes.value : []
  const stockSigs = stocksRes.status === 'fulfilled' ? stocksRes.value : []

  return (
    <div className="space-y-6 animate-[fadeIn_0.4s_ease-out]">
      <div>
        <h1 className="text-2xl font-bold text-white">Feed de Señales</h1>
        <p className="text-sm text-muted mt-1">Señales técnicas en tiempo real — Crypto + Stocks</p>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        {/* Crypto signals */}
        <div className="card">
          <div className="text-sm font-semibold text-white mb-4">
            Señales Crypto
            <span className="ml-2 badge badge-blue">{signals.length}</span>
          </div>
          <div className="space-y-1.5 max-h-[520px] overflow-y-auto">
            {signals.slice(0, 60).map((s: any, i) => (
              <div key={i} className="flex items-center gap-3 px-3 py-2 rounded-lg bg-bg hover:bg-surface/60 transition-colors border border-transparent hover:border-border">
                <span className="w-16 text-xs font-mono font-bold text-white">{s.asset}</span>
                <span className={`badge ${s.direction === 'BUY' ? 'badge-green' : s.direction === 'SELL' ? 'badge-red' : 'badge-muted'}`}>
                  {s.direction ?? '?'}
                </span>
                <span className="text-xs text-muted flex-1 truncate">{s.signal_type}</span>
                {s.score != null && (
                  <span className={clsx('text-xs font-mono', s.score >= 70 ? 'pos' : s.score >= 50 ? 'text-gold' : 'neutral')}>
                    {s.score}
                  </span>
                )}
                <span className="text-[10px] text-muted/60">{timeAgo(s.timestamp)}</span>
              </div>
            ))}
            {signals.length === 0 && <div className="text-sm text-muted text-center py-8">Sin señales</div>}
          </div>
        </div>

        {/* Stocks open trades (= recent signals executed) */}
        <div className="card">
          <div className="text-sm font-semibold text-white mb-4">
            Trades Stocks Abiertos
            <span className="ml-2 badge badge-green">{stockSigs.length}</span>
          </div>
          <div className="space-y-1.5 max-h-[520px] overflow-y-auto">
            {stockSigs.slice(0, 60).map((t: any, i) => (
              <div key={i} className="flex items-center gap-3 px-3 py-2 rounded-lg bg-bg hover:bg-surface/60 transition-colors border border-transparent hover:border-border">
                <span className="w-12 text-xs font-mono font-bold text-white">{t.symbol}</span>
                <span className={`badge ${t.direction === 'BUY' ? 'badge-green' : 'badge-red'}`}>{t.direction}</span>
                <span className="text-xs font-mono text-muted">${fmt(t.entry_price)}</span>
                <span className="flex-1 text-[10px] text-muted truncate">{t.strategy}</span>
                <span className="text-[10px] text-muted/60">{timeAgo(t.opened_at)}</span>
              </div>
            ))}
            {stockSigs.length === 0 && <div className="text-sm text-muted text-center py-8">Sin trades abiertos</div>}
          </div>
        </div>
      </div>
    </div>
  )
}
