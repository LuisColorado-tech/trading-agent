import { fmtPnl } from '@/lib/fmt'
import { clsx } from 'clsx'

const API = '/api'

async function getConsortium() {
  try {
    const res = await fetch(`${API}/overview/consortium`, { next: { revalidate: 30 } })
    if (!res.ok) return null
    return res.json()
  } catch {
    return null
  }
}

export default async function ConsortiumWidget() {
  const data = await getConsortium()

  if (!data || data.error) {
    return (
      <div className="card border-border">
        <div className="text-sm text-muted">🏦 Consorcio — API no disponible</div>
      </div>
    )
  }

  const dd = data.max_drawdown_pct ?? 0
  const ddColor = dd < 5 ? 'pos' : dd < 10 ? 'text-gold' : 'neg'
  const pnlColor = (data.daily_pnl ?? 0) >= 0 ? 'pos' : 'neg'
  const cap = data.capital_total ?? 0
  const dp = data.daily_pnl ?? 0
  const dpp = data.daily_pnl_pct ?? 0

  return (
    <div className="card border-green/15">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <span className="text-lg">🏦</span>
          <span className="font-semibold text-sm text-white tracking-tight">CONSORCIO ARTHAS</span>
        </div>
        <span className="badge badge-green text-[10px] self-start sm:self-auto">{data.active_agents ?? 0}/5 activos</span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 sm:gap-4">
        <div>
          <div className="text-[9px] sm:text-[10px] text-muted uppercase tracking-wider mb-1">Capital Total</div>
          <div className="text-lg sm:text-xl font-mono font-bold text-white">
            ${cap.toLocaleString('en-US', { maximumFractionDigits: 0 })}
          </div>
        </div>

        <div>
          <div className="text-[9px] sm:text-[10px] text-muted uppercase tracking-wider mb-1">P&L Hoy</div>
          <div className={clsx('text-lg sm:text-xl font-mono font-bold', pnlColor)}>
            {fmtPnl(dp)}
          </div>
          {dpp !== 0 && (
            <div className={clsx('text-[10px] sm:text-xs font-mono mt-0.5', pnlColor)}>
              {dpp >= 0 ? '+' : ''}{dpp}%
            </div>
          )}
        </div>

        <div>
          <div className="text-[9px] sm:text-[10px] text-muted uppercase tracking-wider mb-1">Drawdown</div>
          <div className={clsx('text-lg sm:text-xl font-mono font-bold', ddColor)}>
            -{dd.toFixed(1)}%
          </div>
        </div>

        <div>
          <div className="text-[9px] sm:text-[10px] text-muted uppercase tracking-wider mb-1">Agentes</div>
          <div className="text-lg sm:text-xl font-mono font-bold text-blue">
            {data.active_agents ?? 0}/5
          </div>
          <div className="text-[9px] sm:text-[10px] text-muted font-mono mt-0.5">live trading</div>
        </div>

        <div>
          <div className="text-[9px] sm:text-[10px] text-muted uppercase tracking-wider mb-1">Versión</div>
          <div className="text-lg sm:text-xl font-mono font-bold text-gold">v3</div>
          <div className="text-[9px] sm:text-[10px] text-muted font-mono mt-0.5">MIN_SCORE=75</div>
        </div>
      </div>
    </div>
  )
}
