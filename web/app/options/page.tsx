"use client"

import { useEffect, useState } from 'react'
import { api } from '@/lib/api'
import { fmt, fmtPnl, fmtPct, pnlClass } from '@/lib/fmt'
import { clsx } from 'clsx'

export default function OptionsPage() {
  const [scope, setScope] = useState<'session' | 'all'>('session')
  const [sess, setSess] = useState<any>({})
  const [sessionPos, setSessionPos] = useState<any[]>([])
  const [sessionStats, setSessionStats] = useState<any>({})
  const [allPos, setAllPos] = useState<any[]>([])
  const [allStats, setAllStats] = useState<any>({})

  useEffect(() => {
    let cancelled = false
    async function load() {
      const results = await Promise.allSettled([
        api.optionsSession(),
        api.optionsPositions(200, 'session'),
        api.optionsStats('session'),
        api.optionsPositions(200, 'all'),
        api.optionsStats('all'),
      ])
      if (cancelled) return
      const [sessRes, sPosRes, sStatsRes, aPosRes, aStatsRes] = results
      if (sessRes.status === 'fulfilled') setSess(sessRes.value)
      if (sPosRes.status === 'fulfilled') setSessionPos(sPosRes.value)
      if (sStatsRes.status === 'fulfilled') setSessionStats(sStatsRes.value)
      if (aPosRes.status === 'fulfilled') setAllPos(aPosRes.value)
      if (aStatsRes.status === 'fulfilled') setAllStats(aStatsRes.value)
    }
    load()
    const interval = setInterval(load, 30000)
    return () => { cancelled = true; clearInterval(interval) }
  }, [])

  const activePos = scope === 'session' ? sessionPos : allPos
  const open = activePos.filter((p: any) => p.status === 'OPEN')
  const closed = activePos.filter((p: any) => p.status !== 'OPEN')

  return (
    <div className="space-y-6 animate-[fadeIn_0.4s_ease-out]">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-white tracking-tight">Options — Deribit Theta Farming</h1>
          <p className="text-sm text-muted mt-1">
            {sess.session_name ?? 'Theta Farming'} · primas cobradas · IV rank · expiraciones
          </p>
        </div>

        <div className="flex rounded-lg border border-border overflow-hidden">
          <button
            onClick={() => setScope('session')}
            className={clsx(
              'px-4 py-1.5 text-xs font-mono font-semibold transition-colors',
              scope === 'session'
                ? 'bg-white/10 text-white'
                : 'text-muted hover:text-white'
            )}
          >
            Sesión Actual
          </button>
          <button
            onClick={() => setScope('all')}
            className={clsx(
              'px-4 py-1.5 text-xs font-mono font-semibold transition-colors',
              scope === 'all'
                ? 'bg-white/10 text-white'
                : 'text-muted hover:text-white'
            )}
          >
            Histórico
          </button>
        </div>
      </div>

      {/* KPI Row 1 — Sesión Actual */}
      <div>
        <h2 className={clsx(
          'text-xs font-semibold uppercase tracking-wider mb-3 transition-colors',
          scope === 'session' ? 'text-blue' : 'text-muted'
        )}>
          Sesión Actual
        </h2>
        <KpiRow sess={sess} pos={sessionPos} st={sessionStats} />
      </div>

      {/* KPI Row 2 — Histórico */}
      <div>
        <h2 className={clsx(
          'text-xs font-semibold uppercase tracking-wider mb-3 transition-colors',
          scope === 'all' ? 'text-blue' : 'text-muted'
        )}>
          Histórico
        </h2>
        <KpiRow sess={sess} pos={allPos} st={allStats} />
      </div>

      {/* Tables with tabs */}
      <div className="card">
        <div className="flex gap-1 mb-4 border-b border-border pb-3">
          <button
            onClick={() => setScope('session')}
            className={clsx(
              'px-4 py-1.5 text-xs font-mono font-semibold rounded-md transition-colors',
              scope === 'session'
                ? 'bg-white/10 text-white'
                : 'text-muted hover:text-white'
            )}
          >
            Sesión
          </button>
          <button
            onClick={() => setScope('all')}
            className={clsx(
              'px-4 py-1.5 text-xs font-mono font-semibold rounded-md transition-colors',
              scope === 'all'
                ? 'bg-white/10 text-white'
                : 'text-muted hover:text-white'
            )}
          >
            Histórico
          </button>
        </div>

        {/* Open positions */}
        <div className="mb-6">
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
        <div>
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
    </div>
  )
}

function KpiRow({ sess, pos, st }: { sess: any; pos: any[]; st: any }) {
  const open = pos.filter((p: any) => p.status === 'OPEN')
  const balance = sess.current_balance_usd ?? sess.initial_balance_usd ?? 2000
  const totalPremium = st.total_premium ?? 0
  const totalPnl = st.total_pnl ?? 0

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-7 gap-3">
      {([
        ['Balance', `$${fmt(balance, 0)}`, 'text-white'],
        ['Primas Totales', `$${fmt(totalPremium, 0)}`, 'text-gold'],
        ['P&L', fmtPnl(totalPnl), pnlClass(totalPnl)],
        ['Win Rate', fmtPct(st.win_rate), 'text-white'],
        ['Trades', st.total ?? 0, 'text-white'],
        ['Abiertos', open.length, open.length > 0 ? 'text-gold' : 'text-muted'],
        ['Sesión', sess.session_name ?? '—', 'text-blue'],
      ] as [string, any, string][]).map(([label, value, cls]) => (
        <div key={label} className="card text-center">
          <div className="text-[10px] text-muted uppercase tracking-wider mb-1">{label}</div>
          <div className={clsx('text-base font-mono font-bold', cls)}>{value}</div>
        </div>
      ))}
    </div>
  )
}
