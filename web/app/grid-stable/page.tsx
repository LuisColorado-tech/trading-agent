'use client'

import { useState, useEffect } from 'react'
import { api } from '@/lib/api'
import { fmt, fmtPnl, fmtPct, pnlClass } from '@/lib/fmt'
import { clsx } from 'clsx'

type Scope = 'recent' | 'all'

export default function GridStablePage() {
  const [scope, setScope] = useState<Scope>('recent')
  const [data, setData] = useState<Record<Scope, { stats: any; trades: any[] } | null>>({
    recent: null,
    all: null,
  })
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function fetchAll() {
      setLoading(true)
      try {
        const [recentStats, recentTrades, allStats, allTrades] = await Promise.all([
          api.gridStableStats('recent'),
          api.gridStableTrades('recent'),
          api.gridStableStats('all'),
          api.gridStableTrades('all'),
        ])
        setData({
          recent: { stats: recentStats, trades: recentTrades },
          all: { stats: allStats, trades: allTrades },
        })
      } catch (e) {
        console.error('Failed to fetch grid-stable data', e)
      }
      setLoading(false)
    }
    fetchAll()
  }, [])

  const current = data[scope]
  const st = current?.stats ?? {}
  const allTrades = current?.trades ?? []

  const closed = allTrades.filter((t: any) => t.status !== 'OPEN')
  const open = allTrades.filter((t: any) => t.status === 'OPEN')

  const pairs = st.by_pair ?? []
  const reasons = st.by_reason ?? []
  const tpCount = reasons.find((r: any) => r.close_reason === 'TAKE_PROFIT')?.count ?? 0
  const slCount = reasons.find((r: any) => r.close_reason === 'STOP_LOSS')?.count ?? 0

  return (
    <div className="space-y-6 animate-[fadeIn_0.4s_ease-out]">
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-white tracking-tight">Grid Stable — Pares Estables</h1>
          <p className="text-sm text-muted mt-1">
            ETH/BTC + LINK/BTC · cooldown post-SL · BUY+SELL · trailing break-even
          </p>
        </div>

        <div className="flex bg-white/5 rounded-lg p-0.5 gap-0.5">
          <button
            onClick={() => setScope('recent')}
            className={clsx(
              'px-3 py-1 text-xs font-medium rounded-md transition-colors',
              scope === 'recent'
                ? 'bg-blue-600 text-white shadow'
                : 'text-muted hover:text-white'
            )}
          >
            📌 30 Días
          </button>
          <button
            onClick={() => setScope('all')}
            className={clsx(
              'px-3 py-1 text-xs font-medium rounded-md transition-colors',
              scope === 'all'
                ? 'bg-blue-600 text-white shadow'
                : 'text-muted hover:text-white'
            )}
          >
            📜 Histórico
          </button>
        </div>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-12">
          <div className="animate-spin rounded-full h-8 w-8 border-2 border-blue-500 border-t-transparent" />
        </div>
      )}

      {!loading && (
        <>
          {/* KPIs */}
          <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3">
            {[
              ['P&L', fmtPnl(st.total_pnl ?? 0), pnlClass(st.total_pnl ?? 0)],
              ['Win Rate', fmtPct(st.win_rate ?? 0), 'text-white'],
              ['Profit Factor', fmt(st.profit_factor ?? 0), (st.profit_factor ?? 0) >= 1.5 ? 'pos' : 'text-gold'],
              ['Trades', st.total_trades ?? 0, 'text-white'],
              ['Abiertos', st.open_trades ?? 0, open.length > 0 ? 'text-blue' : 'text-muted'],
              ['Avg Win/Loss', `+$${fmt(st.avg_win ?? 0, 2)}/-$${fmt(Math.abs(st.avg_loss ?? 0), 2)}`, 'text-muted'],
            ].map(([label, value, cls]) => (
              <div key={label as string} className="card text-center">
                <div className="text-[10px] text-muted uppercase tracking-wider mb-1">{label as string}</div>
                <div className={clsx('text-base font-mono font-bold', cls as string)}>{value}</div>
              </div>
            ))}
          </div>

          {/* Por par + Cierres */}
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <div className="card">
              <div className="text-xs text-muted uppercase tracking-wider mb-3">Por Par</div>
              <div className="overflow-hidden">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-muted border-b border-white/5">
                      <th className="text-left py-1.5 font-medium">Par</th>
                      <th className="text-right py-1.5 font-medium">Trades</th>
                      <th className="text-right py-1.5 font-medium">WR</th>
                      <th className="text-right py-1.5 font-medium">PnL</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pairs.map((row: any) => (
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

            <div className="card">
              <div className="text-xs text-muted uppercase tracking-wider mb-3">Cierres por Motivo</div>
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <div className="flex-1">
                    <div className="flex justify-between text-sm mb-1">
                      <span className="pos">TAKE_PROFIT</span>
                      <span className="font-mono">{tpCount}</span>
                    </div>
                    <div className="h-2 bg-white/5 rounded-full overflow-hidden">
                      <div className="h-full bg-green-500/50 rounded-full" style={{ width: `${tpCount / Math.max(1, (st.total_trades ?? 1)) * 100}%`, minWidth: tpCount > 0 ? '4px' : '0' }} />
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <div className="flex-1">
                    <div className="flex justify-between text-sm mb-1">
                      <span className="neg">STOP_LOSS</span>
                      <span className="font-mono">{slCount}</span>
                    </div>
                    <div className="h-2 bg-white/5 rounded-full overflow-hidden">
                      <div className="h-full bg-red-500/50 rounded-full" style={{ width: `${slCount / Math.max(1, (st.total_trades ?? 1)) * 100}%`, minWidth: slCount > 0 ? '4px' : '0' }} />
                    </div>
                  </div>
                </div>
              </div>

              <div className="mt-4 pt-4 border-t border-white/5">
                <div className="text-[10px] text-muted uppercase tracking-wider mb-2">Parámetros</div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div className="flex justify-between">
                    <span className="text-muted">ETH/BTC SL</span>
                    <span className="font-mono">0.60× spacing</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted">ETH/BTC TP</span>
                    <span className="font-mono">1.80× spacing</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted">LINK/BTC SL</span>
                    <span className="font-mono">0.65× spacing</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted">LINK/BTC TP</span>
                    <span className="font-mono">1.95× spacing</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted">Cooldown SL</span>
                    <span className="font-mono">10 min</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted">Modo</span>
                    <span className="pos font-mono">BUY + SELL</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Últimos trades */}
          <div className="card">
            <div className="text-xs text-muted uppercase tracking-wider mb-3">
              Últimos {Math.min(closed.length, 25)} Trades Cerrados
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-muted border-b border-white/5">
                    <th className="text-left py-1.5 font-medium">Par</th>
                    <th className="text-left py-1.5 font-medium">Dir</th>
                    <th className="text-right py-1.5 font-medium">Entry</th>
                    <th className="text-right py-1.5 font-medium">Exit</th>
                    <th className="text-right py-1.5 font-medium">SL</th>
                    <th className="text-right py-1.5 font-medium">TP</th>
                    <th className="text-right py-1.5 font-medium">PnL</th>
                    <th className="text-center py-1.5 font-medium">Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {closed.slice(0, 25).map((t: any) => (
                    <tr key={t.id} className="border-b border-white/[0.02] hover:bg-white/[0.02]">
                      <td className="py-1.5 font-mono text-white">{t.asset}</td>
                      <td className={clsx('py-1.5 font-mono text-[10px]', t.side === 'BUY' ? 'pos' : 'neg')}>{t.side}</td>
                      <td className="py-1.5 text-right font-mono">{fmt(t.entry_price, 8)}</td>
                      <td className="py-1.5 text-right font-mono">{fmt(t.exit_price, 8)}</td>
                      <td className="py-1.5 text-right font-mono text-muted">{fmt(t.stop_loss, 8)}</td>
                      <td className="py-1.5 text-right font-mono text-muted">{fmt(t.take_profit, 8)}</td>
                      <td className={clsx('py-1.5 text-right font-mono', t.pnl > 0 ? 'pos' : 'neg')}>{fmtPnl(t.pnl)}</td>
                      <td className={clsx('py-1.5 text-center text-[10px] font-mono',
                        t.close_reason === 'TAKE_PROFIT' ? 'pos' : 'neg')}>
                        {t.close_reason?.replace('_', ' ')}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
