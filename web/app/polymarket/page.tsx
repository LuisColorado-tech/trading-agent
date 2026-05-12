'use client'

import { api } from '@/lib/api'
import { fmt, fmtPnl, fmtPct, pnlClass } from '@/lib/fmt'
import { clsx } from 'clsx'
import { useEffect, useState } from 'react'

type Scope = 'session' | 'all'

export default function PolymarketPage() {
  const [scope, setScope] = useState<Scope>('session')
  const [session, setSession] = useState<any>({})
  const [positions, setPositions] = useState<{ session: any[]; all: any[] }>({ session: [], all: [] })
  const [stats, setStats] = useState<{ session: any; all: any }>({ session: {}, all: {} })
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    Promise.allSettled([
      api.polySession(),
      api.polyPositions('scope=session&limit=200'),
      api.polyPositions('scope=all&limit=200'),
      api.polyStats('session'),
      api.polyStats('all'),
    ]).then(([sessRes, posSessRes, posAllRes, statsSessRes, statsAllRes]) => {
      setSession(sessRes.status === 'fulfilled' ? sessRes.value : {})
      setPositions({
        session: posSessRes.status === 'fulfilled' ? posSessRes.value : [],
        all: posAllRes.status === 'fulfilled' ? posAllRes.value : [],
      })
      setStats({
        session: statsSessRes.status === 'fulfilled' ? statsSessRes.value : {},
        all: statsAllRes.status === 'fulfilled' ? statsAllRes.value : {},
      })
      setLoading(false)
    })
  }, [])

  const currentPositions = positions[scope]
  const currentStats = stats[scope]
  const open = currentPositions.filter((p: any) => p.status === 'OPEN')
  const closed = currentPositions.filter((p: any) => p.status !== 'OPEN')

  return (
    <div className="space-y-6 animate-[fadeIn_0.4s_ease-out]">
      <div>
        <h1 className="text-xl sm:text-2xl font-bold text-white tracking-tight">Polymarket — Prediction Markets</h1>
        <p className="text-sm text-muted mt-1">
          {session.session_name ?? '—'} · v3 edge fix · min=0.42
        </p>
      </div>

      {/* Scope Toggle */}
      <div className="flex gap-2">
        {([
          ['session', '📌 Sesión'],
          ['all', '📜 Histórico'],
        ] as const).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setScope(key)}
            className={clsx(
              'px-4 py-1.5 rounded-full text-xs font-medium transition-colors',
              scope === key
                ? 'bg-gold/20 text-gold border border-gold/40'
                : 'bg-surface text-muted border border-border hover:text-white hover:border-muted'
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-6 gap-3">
        {[
          ['Balance', `$${fmt(currentStats.balance ?? session.current_balance ?? session.initial_balance ?? 0, 0)}`, 'text-white'],
          ['P&L', fmtPnl(currentStats.total_pnl), pnlClass(currentStats.total_pnl)],
          ['Win Rate', fmtPct(currentStats.win_rate), 'text-white'],
          ['PF', fmt(currentStats.profit_factor), (currentStats.profit_factor ?? 0) >= 1.3 ? 'pos' : 'text-gold'],
          ['Trades', currentStats.total ?? 0, 'text-white'],
          ['Abiertos', open.length, open.length > 0 ? 'text-purple' : 'text-muted'],
        ].map(([label, value, cls]) => (
          <div key={label as string} className="card text-center">
            <div className="text-[10px] text-muted uppercase tracking-wider mb-1">{label as string}</div>
            <div className={clsx('text-base font-mono font-bold', cls as string)}>
              {loading ? '—' : value}
            </div>
          </div>
        ))}
      </div>

      {/* Open positions */}
      <div className="card">
        <div className="text-xs text-muted uppercase tracking-wider mb-3">
          Posiciones Abiertas
          {open.length > 0 && <span className="ml-2 badge badge-purple">{open.length}</span>}
        </div>
        {loading ? (
          <div className="text-sm text-muted text-center py-8">Cargando…</div>
        ) : open.length === 0 ? (
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
                    <td className="py-2 pr-4 font-mono text-white max-w-[200px] truncate">{p.question ?? p.event_title ?? p.slug ?? '—'}</td>
                    <td className="py-2 pr-4 font-mono text-muted">{p.outcome}</td>
                    <td className="py-2 pr-4">
                      <span className={`badge ${p.side === 'BUY' ? 'badge-green' : 'badge-red'}`}>
                        {p.side}
                      </span>
                    </td>
                    <td className="py-2 pr-4 font-mono text-muted">${fmt(p.entry_price)}</td>
                    <td className="py-2 pr-4 font-mono text-white">${fmt(p.shares ?? p.size ?? 0)}</td>
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
        {loading ? (
          <div className="text-sm text-muted text-center py-8">Cargando…</div>
        ) : closed.length === 0 ? (
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
                    <td className="py-2 pr-4 font-mono text-white max-w-[180px] truncate">{p.question ?? p.event_title ?? p.slug ?? '—'}</td>
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
