'use client'

import { useState, useEffect } from 'react'
import { api } from '@/lib/api'
import { fmt, fmtPnl, fmtPct, pnlClass } from '@/lib/fmt'
import MiniEquity from '@/components/MiniEquity'
import { clsx } from 'clsx'

type Scope = 'session' | 'all'

const STRATEGY_LABELS: Record<string, { label: string; cls: string }> = {
  'STOCKS_MOMENTUM':  { label: 'MOMENTUM',  cls: 'badge-green' },
  'STOCKS_TREND_ETF': { label: 'TREND ETF', cls: 'badge-blue' },
}

function stratBadge(s: string | null) {
  if (!s) return <span className="badge badge-muted">—</span>
  const m = STRATEGY_LABELS[s] ?? { label: s, cls: 'badge-muted' }
  return <span className={`badge ${m.cls}`}>{m.label}</span>
}

export default function StocksPage() {
  const [scope, setScope] = useState<Scope>('session')
  const [loading, setLoading] = useState(true)
  const [session, setSession] = useState<any>({})
  const [universe, setUniverse] = useState<any[]>([])
  const [open, setOpen] = useState<any[]>([])
  const [equity, setEquity] = useState<any[]>([])
  const [byStrat, setByStrat] = useState<any[]>([])

  useEffect(() => {
    setLoading(true)
    Promise.allSettled([
      api.stocksSession(scope),
      api.stocksUniverse(scope),
      api.stocksOpenTrades(),
      api.stocksEquity(scope),
      api.stocksByStrategy(scope),
    ]).then(([sessionRes, universeRes, openRes, equityRes, stratRes]) => {
      setSession(sessionRes.status === 'fulfilled' ? sessionRes.value : {})
      setUniverse(universeRes.status === 'fulfilled' ? universeRes.value : [])
      setOpen(openRes.status === 'fulfilled' ? openRes.value : [])
      setEquity(equityRes.status === 'fulfilled' ? equityRes.value : [])
      setByStrat(stratRes.status === 'fulfilled' ? stratRes.value : [])
      setLoading(false)
    })
  }, [scope])

  const balance = session.current_balance ?? session.initial_balance ?? 220
  const totalPnl = typeof session.total_pnl === 'number' ? session.total_pnl : 0
  const winRate = session.win_rate ?? 0
  const totalTrades = session.total_closed ?? session.total_trades ?? 0
  const openCount = session.open_count ?? 0

  return (
    <div className="space-y-8 animate-[fadeIn_0.4s_ease-out]">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-white">Stocks</h1>
          <p className="text-sm text-muted mt-1">NYSE/NASDAQ · Alpaca Paper Trading · 10 activos</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center bg-surface border border-border rounded-lg p-0.5">
            <button
              onClick={() => setScope('session')}
              className={clsx(
                'px-3 py-1.5 text-xs font-mono rounded-md transition-all',
                scope === 'session'
                  ? 'bg-green/10 text-green border border-green/20'
                  : 'text-muted hover:text-white'
              )}
            >
              📌 Sesión
            </button>
            <button
              onClick={() => setScope('all')}
              className={clsx(
                'px-3 py-1.5 text-xs font-mono rounded-md transition-all',
                scope === 'all'
                  ? 'bg-blue/10 text-blue border border-blue/20'
                  : 'text-muted hover:text-white'
              )}
            >
              📜 Histórico
            </button>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-green animate-pulse" />
            <span className="text-xs font-mono text-muted uppercase">live</span>
          </div>
        </div>
      </div>

      {loading && (
        <div className="text-center text-muted text-sm py-12">Cargando...</div>
      )}

      {!loading && (
        <>
          {/* KPI row */}
          <div className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-6 gap-3">
            {[
              { label: 'Balance', value: `$${fmt(balance, 0)}`, cls: 'text-white' },
              { label: 'P&L Total', value: fmtPnl(totalPnl), cls: pnlClass(totalPnl) },
              { label: 'Win Rate', value: fmtPct(winRate), cls: 'text-white' },
              { label: 'Profit Factor', value: fmt(session.profit_factor ?? 0), cls: (session.profit_factor ?? 0) >= 1 ? 'pos' : 'neg' },
              { label: 'Trades cerrados', value: String(totalTrades), cls: 'text-white' },
              { label: 'Abiertos', value: String(openCount), cls: openCount > 0 ? 'pos' : 'neutral' },
            ].map(({ label, value, cls }) => (
              <div key={label} className="card">
                <div className="text-[10px] text-muted uppercase tracking-wider mb-1">{label}</div>
                <div className={clsx('text-xl font-mono font-bold num', cls)}>{value}</div>
              </div>
            ))}
          </div>

          {/* Universe grid */}
          <div>
            <h2 className="text-base font-semibold text-white mb-3">Universo — 10 activos</h2>
            <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5 gap-3">
              {universe.map((asset: any) => {
                const pnl = asset.total_pnl ?? 0
                const tr = asset.trades ?? asset.total_trades ?? 0
                const wr = asset.wr ?? asset.win_rate
                const pf = asset.profit_factor
                return (
                  <div key={asset.symbol} className={clsx(
                    'card hover:border-green/30 transition-all duration-150',
                    open.some((t: any) => t.symbol === asset.symbol) && 'border-green/30 glow-green'
                  )}>
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-base font-mono font-bold text-white">{asset.symbol}</span>
                      {stratBadge(asset.strategy)}
                    </div>
                    <div className={clsx('text-sm font-mono font-semibold mb-1', pnlClass(pnl))}>
                      {fmtPnl(pnl)}
                    </div>
                    <div className="grid grid-cols-2 gap-1 text-[10px]">
                      <span className="text-muted">Trades:</span>
                      <span className="text-white font-mono">{tr}</span>
                      <span className="text-muted">WR:</span>
                      <span className="text-white font-mono">{wr != null ? fmtPct(wr) : '—'}</span>
                      <span className="text-muted">PF:</span>
                      <span className={clsx('font-mono', pf != null ? (pf >= 1.2 ? 'pos' : pf >= 1.0 ? 'text-gold' : 'neg') : 'neutral')}>
                        {pf != null ? fmt(pf) : '—'}
                      </span>
                      <span className="text-muted">Open:</span>
                      <span className={clsx('font-mono', (asset.open_positions ?? 0) > 0 ? 'pos' : 'neutral')}>
                        {asset.open_positions ?? 0}
                      </span>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          {/* Equity + open trades row */}
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            {/* Equity curve */}
            <div className="card">
              <div className="text-sm font-semibold text-white mb-4">Equity Curve — Stocks Session</div>
              <MiniEquity data={equity} color="#58A6FF" />
            </div>

            {/* Open trades */}
            <div className="card">
              <div className="text-sm font-semibold text-white mb-4">
                Trades Abiertos
                {open.length > 0 && <span className="ml-2 badge badge-green">{open.length}</span>}
              </div>
              {open.length === 0 ? (
                <div className="text-sm text-muted py-8 text-center">No hay trades abiertos</div>
              ) : (
                <div className="space-y-2 overflow-y-auto max-h-60">
                  {open.map((t: any) => (
                    <div key={t.id} className="flex items-center gap-3 py-2 border-b border-border last:border-0">
                      <span className="text-xs font-mono font-bold text-white w-12">{t.symbol}</span>
                      <span className={`badge ${t.direction === 'BUY' ? 'badge-green' : 'badge-red'}`}>{t.direction}</span>
                      <span className="text-xs font-mono text-white">${fmt(t.entry_price)}</span>
                      <div className="flex-1 mx-2">
                        <div className="flex gap-0.5 h-1.5 rounded-full overflow-hidden">
                          <div className="bg-red/60 rounded-full" style={{ width: '30%' }} />
                          <div className="bg-green/60 rounded-full" style={{ width: '70%' }} />
                        </div>
                        <div className="flex justify-between text-[9px] text-muted mt-0.5">
                          <span>SL ${fmt(t.stop_loss)}</span>
                          <span>TP ${fmt(t.take_profit)}</span>
                        </div>
                      </div>
                      {stratBadge(t.strategy)}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* By strategy */}
          {byStrat.length > 0 && (
            <div className="card">
              <div className="text-sm font-semibold text-white mb-4">Rendimiento por Estrategia</div>
              <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
                {byStrat.map((r: any) => (
                  <div key={r.strategy} className="text-center">
                    <div className="mb-1">{stratBadge(r.strategy)}</div>
                    <div className={clsx('text-lg font-mono font-bold', pnlClass(r.total_pnl))}>
                      {fmtPnl(r.total_pnl)}
                    </div>
                    <div className="text-xs text-muted">{(r.trades ?? r.total_trades ?? 0)} trades</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
