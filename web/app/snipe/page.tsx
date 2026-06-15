'use client'

import { useEffect, useState, useMemo } from 'react'
import { fmt, fmtPnl, fmtPct, pnlClass } from '@/lib/fmt'
import { clsx } from 'clsx'

const API = '/api'

type Scope = 'session' | 'all'

async function fetchJSON(url: string) {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`${url} -> ${res.status}`)
  return res.json()
}

export default function SnipePage() {
  const [scope, setScope] = useState<Scope>('session')
  const [data, setData] = useState<Record<Scope, { trades: any[]; stats: any }>>({
    session: { trades: [], stats: {} },
    all: { trades: [], stats: {} },
  })
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      try {
        const [sTrades, sStats, aTrades, aStats] = await Promise.allSettled([
          fetchJSON(`${API}/polymarket/snipe?scope=session&limit=200`),
          fetchJSON(`${API}/polymarket/snipe/stats?scope=session`),
          fetchJSON(`${API}/polymarket/snipe?scope=all&limit=200`),
          fetchJSON(`${API}/polymarket/snipe/stats?scope=all`),
        ])
        setData({
          session: {
            trades: sTrades.status === 'fulfilled' ? sTrades.value : [],
            stats: sStats.status === 'fulfilled' ? sStats.value : {},
          },
          all: {
            trades: aTrades.status === 'fulfilled' ? aTrades.value : [],
            stats: aStats.status === 'fulfilled' ? aStats.value : {},
          },
        })
      } catch {}
      setLoading(false)
    }
    load()
  }, [])

  const { trades, stats } = data[scope]

  const closed = useMemo(() => trades.filter((t: any) => t.status !== 'OPEN'), [trades])
  const open = useMemo(() => trades.filter((t: any) => t.status === 'OPEN'), [trades])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-muted text-sm animate-pulse">Cargando datos de snipe...</div>
      </div>
    )
  }

  return (
    <div className="space-y-6 animate-[fadeIn_0.4s_ease-out]">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-white tracking-tight">PolySnipe — SNIPE + ARB</h1>
          <p className="text-sm text-muted mt-1">
            DESACTIVADO — Council #7 (0-2-2) · May 29, 2026
          </p>
        </div>
        <span className="badge badge-red text-xs">🚫 DESACTIVADO</span>
      </div>

      <div className="card border border-red/30 bg-red/5">
        <div className="text-sm text-muted space-y-2">
          <p className="text-white font-semibold">📋 Veredicto del Trading Council (0-2-2)</p>
          <p>341 trades · 91.8% WR · PnL -$150.37 · Balance final $349.63</p>
          <p className="text-red">El edge es estructuralmente negativo: cada loss (-$13.58 avg) borra 15 wins (+$0.60 avg).</p>
          <p className="text-muted">La ventana oracle de 15 min de Polymarket no captura el movimiento de entrada. Sin trailing stop que arregle este defecto mecánico.</p>
          <p className="text-gold mt-2">Capital redistribuido a TM + GRID_STABLE (+$226 en 3 días).</p>
        </div>
      </div>

      {/* KPIs finales */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {[
          ['P&L Final', '-$150.37', 'neg'],
          ['Win Rate', '91.8%', 'pos'],
          ['Trades', '341', 'text-muted'],
          ['SOL DOWN', '-$160.57', 'neg'],
          ['XRP DOWN', '-$145.88', 'neg'],
          ['ETH UP', '+$12.04', 'pos'],
          ['BTC UP', '+$30.70', 'pos'],
        ].map(([label, value, cls]) => (
          <div key={label as string} className="card text-center">
            <div className="text-[10px] text-muted uppercase tracking-wider mb-1">{label as string}</div>
            <div className={clsx('text-base font-mono font-bold', cls as string)}>{value}</div>
          </div>
        ))}
      </div>

      {/* Historial final */}
      {!loading && closed.length > 0 && (
        <div className="card">
          <div className="text-xs text-muted uppercase tracking-wider mb-3">
            🔒 Historial Final <span className="ml-2 badge badge-muted">{closed.length}</span>
          </div>
          <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-muted text-left border-b border-border sticky top-0 bg-surface">
                  <th className="pb-2 pr-4 font-normal">Asset</th>
                  <th className="pb-2 pr-4 font-normal">Dir</th>
                  <th className="pb-2 pr-4 font-normal">Entrada</th>
                  <th className="pb-2 pr-4 font-normal">Outcome</th>
                  <th className="pb-2 pr-4 font-normal">P&L</th>
                  <th className="pb-2 pr-4 font-normal">Move %</th>
                  <th className="pb-2 font-normal">Cerrado</th>
                </tr>
              </thead>
              <tbody>
                {closed.slice(0, 200).map((t: any, i: number) => (
                  <tr key={i} className="border-b border-border/30 hover:bg-white/2">
                    <td className="py-2 pr-4 font-mono text-white">{t.asset}</td>
                    <td className="py-2 pr-4">
                      <span className={clsx('badge', t.direction === 'UP' ? 'badge-green' : t.direction === 'BOTH' ? 'badge-gold' : 'badge-red')}>
                        {t.direction}
                      </span>
                    </td>
                    <td className="py-2 pr-4 font-mono text-muted">${fmt(t.entry_price, 4)}</td>
                    <td className="py-2 pr-4">
                      <span className={`badge ${t.outcome === 'WIN' ? 'badge-green' : 'badge-red'}`}>
                        {t.outcome}
                      </span>
                    </td>
                    <td className={clsx('py-2 pr-4 font-mono font-semibold', pnlClass(t.pnl_usdc))}>
                      {fmtPnl(t.pnl_usdc)}
                    </td>
                    <td className={clsx('py-2 pr-4 font-mono', Number(t.move_pct) >= 0 ? 'pos' : 'neg')}>
                      {t.move_pct ? `${Number(t.move_pct) >= 0 ? '+' : ''}${fmt(t.move_pct, 3)}%` : '—'}
                    </td>
                    <td className="py-2 font-mono text-muted text-[10px]">
                      {t.timestamp_close ? new Date(t.timestamp_close).toLocaleString('es') : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
