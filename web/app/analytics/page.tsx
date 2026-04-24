import { api } from '@/lib/api'
import { fmt, fmtPnl, pnlClass } from '@/lib/fmt'
import { clsx } from 'clsx'
import PnlCalendar from '@/components/PnlCalendar'

export const revalidate = 60

export default async function AnalyticsPage() {
  const [stocksDailyRes, cryptoDailyRes, cryptoStatsRes, stocksStratRes] = await Promise.allSettled([
    api.stocksDailyPnl(),
    api.cryptoDailyPnl(),
    api.cryptoStats(),
    api.stocksByStrategy(),
  ])

  const stocksDaily = stocksDailyRes.status === 'fulfilled' ? stocksDailyRes.value : []
  const cryptoDaily = cryptoDailyRes.status === 'fulfilled' ? cryptoDailyRes.value : []
  const cryptoStats = cryptoStatsRes.status === 'fulfilled' ? cryptoStatsRes.value : {}
  const stocksStrat = stocksStratRes.status === 'fulfilled' ? stocksStratRes.value : []

  return (
    <div className="space-y-8 animate-[fadeIn_0.4s_ease-out]">
      <div>
        <h1 className="text-2xl font-bold text-white">Analytics</h1>
        <p className="text-sm text-muted mt-1">P&L por día, distribución y atribución por agente</p>
      </div>

      {/* PnL calendars */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div className="card">
          <div className="text-sm font-semibold text-white mb-4">P&L Calendario — Stocks</div>
          <PnlCalendar data={stocksDaily} />
        </div>
        <div className="card">
          <div className="text-sm font-semibold text-white mb-4">P&L Calendario — Crypto</div>
          <PnlCalendar data={cryptoDaily} />
        </div>
      </div>

      {/* Crypto stats */}
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
        {[
          { label: 'Win Rate Crypto', value: `${fmt(cryptoStats.win_rate ?? 0, 1)}%`, cls: 'text-white' },
          { label: 'Profit Factor Crypto', value: fmt(cryptoStats.profit_factor ?? 0), cls: (cryptoStats.profit_factor ?? 0) >= 1.5 ? 'pos' : 'text-gold' },
          { label: 'P&L Total Crypto', value: fmtPnl(cryptoStats.total_pnl), cls: pnlClass(cryptoStats.total_pnl) },
          { label: 'Trades Crypto', value: String(cryptoStats.total_closed ?? 0), cls: 'text-white' },
        ].map(({ label, value, cls }) => (
          <div key={label} className="card">
            <div className="text-[10px] text-muted uppercase tracking-wider mb-1">{label}</div>
            <div className={clsx('text-xl font-mono font-bold', cls)}>{value}</div>
          </div>
        ))}
      </div>

      {/* Stocks by strategy */}
      {stocksStrat.length > 0 && (
        <div className="card">
          <div className="text-sm font-semibold text-white mb-4">Atribución por Estrategia — Stocks</div>
          <div className="space-y-3">
            {stocksStrat.map((r: any) => {
              const maxPnl = Math.max(...stocksStrat.map((x: any) => Math.abs(x.total_pnl || 0)), 1)
              const pct = Math.abs(r.total_pnl || 0) / maxPnl * 100
              return (
                <div key={r.strategy}>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="font-mono text-muted">{r.strategy ?? 'UNKNOWN'}</span>
                    <span className={clsx('font-mono font-semibold', pnlClass(r.total_pnl))}>
                      {fmtPnl(r.total_pnl)} · {r.trades} trades
                    </span>
                  </div>
                  <div className="h-1.5 bg-border rounded-full overflow-hidden">
                    <div
                      className={clsx('h-full rounded-full', (r.total_pnl ?? 0) >= 0 ? 'bg-green' : 'bg-red')}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
