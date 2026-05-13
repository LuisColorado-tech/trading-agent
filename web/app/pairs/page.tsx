import { api } from '@/lib/api'
import { fmt, fmtPnl, fmtPct, pnlClass } from '@/lib/fmt'
import { clsx } from 'clsx'

export const revalidate = 60

export default async function PairsPage() {
  let session: any = null
  try { session = await api.get<any>('/pairs/session') } catch {}

  // Backtest reference data
  const backtest = {
    'GLD-SLV': { trades: 7, wr: 42.9, pf: 0.82, pnl: -3.97, maxDD: 1.4 },
    'BTC-ETH': { trades: 0, wr: 0, pf: 0, pnl: 0, maxDD: 0 },
  }

  return (
    <div className="space-y-6 animate-[fadeIn_0.4s_ease-out]">
      <div>
        <h1 className="text-xl sm:text-2xl font-bold text-white tracking-tight">Pairs Trading</h1>
        <p className="text-xs sm:text-sm text-muted mt-1">
          Cointegración — z-score · GLD-SLV &amp; BTC-ETH · paper trading
        </p>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        {[
          { label: 'Trades', value: String(session?.total_trades ?? 0), cls: 'text-white' },
          { label: 'Win Rate', value: session ? `${fmt(session.win_rate, 1)}%` : '—', cls: 'text-white' },
          { label: 'Profit Factor', value: session ? fmt(session.profit_factor) : '—', cls: (session?.profit_factor ?? 0) >= 1.5 ? 'pos' : 'text-gold' },
          { label: 'P&L Total', value: session ? fmtPnl(session.total_pnl) : '—', cls: session ? pnlClass(session.total_pnl) : 'text-muted' },
          { label: 'Avg Win', value: session?.avg_win ? `$${fmt(session.avg_win)}` : '—', cls: 'pos' },
          { label: 'Avg Loss', value: session?.avg_loss ? `-$${fmt(Math.abs(session.avg_loss))}` : '—', cls: 'neg' },
        ].map(({ label, value, cls }) => (
          <div key={label} className="card">
            <div className="text-[9px] sm:text-[10px] text-muted uppercase tracking-wider mb-1">{label}</div>
            <div className={clsx('text-lg sm:text-xl font-mono font-bold', cls)}>{value}</div>
          </div>
        ))}
      </div>

      {/* Strategy info */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 sm:gap-4">
        <div className="card border-orange/15">
          <div className="flex items-center gap-2 mb-4">
            <span className="text-lg">🔗</span>
            <span className="font-semibold text-sm text-white">Estrategia</span>
          </div>
          <div className="space-y-2 text-xs sm:text-sm text-muted">
            <p>Market-neutral: long pierna A, short pierna B cuando el spread se desvía.</p>
            <ul className="list-disc list-inside space-y-1 text-xs">
              <li>Spread = log(A) - β · log(B) — β rodante 252d</li>
              <li>Z-score: (spread - μ) / σ — entrada cuando |z| &gt; 2.0</li>
              <li>Salida: z → 0, o SL en z=3.5, o max 60 días</li>
              <li>Half-life mínimo: 5 días (reversión rápida)</li>
            </ul>
          </div>
        </div>

        <div className="card border-border">
          <div className="flex items-center gap-2 mb-4">
            <span className="text-lg">📊</span>
            <span className="font-semibold text-sm text-white">Parámetros por Par</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="text-muted border-b border-border">
                  <th className="text-left py-2 pr-4">Par</th>
                  <th className="text-right py-2 pr-4">z Entry</th>
                  <th className="text-right py-2 pr-4">z Exit</th>
                  <th className="text-right py-2 pr-4">z SL</th>
                  <th className="text-right py-2">Max Days</th>
                </tr>
              </thead>
              <tbody>
                {[
                  { pair: 'GLD-SLV', zEntry: '±2.0', zExit: '0.0', zSL: '3.5', maxDays: 60, source: 'Alpaca' },
                  { pair: 'BTC-ETH', zEntry: '±2.5', zExit: '0.5', zSL: '4.0', maxDays: 30, source: 'Kraken' },
                ].map(p => (
                  <tr key={p.pair} className="border-b border-border/50 hover:bg-white/[0.02]">
                    <td className="py-2.5 pr-4">
                      <span className="text-white">{p.pair}</span>
                      <span className="text-muted ml-1.5 text-[10px]">{p.source}</span>
                    </td>
                    <td className="py-2.5 pr-4 text-right text-white">{p.zEntry}</td>
                    <td className="py-2.5 pr-4 text-right text-white">{p.zExit}</td>
                    <td className="py-2.5 pr-4 text-right text-red">{p.zSL}</td>
                    <td className="py-2.5 text-right text-muted">{p.maxDays}d</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Backtest results */}
      <div className="card border-border">
        <div className="flex items-center gap-2 mb-4">
          <span className="text-lg">⏪</span>
          <span className="font-semibold text-sm text-white">Backtest 5 Años</span>
          <span className="text-[10px] text-muted ml-auto">walk-forward · yfinance</span>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:gap-4">
          {Object.entries(backtest).map(([pair, bt]) => (
            <div key={pair} className="bg-surface/50 rounded-lg p-3 sm:p-4 border border-border/50">
              <div className="text-xs font-semibold text-white mb-3">{pair}</div>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div><span className="text-muted">Trades:</span>{' '}<span className="text-white font-mono">{bt.trades}</span></div>
                <div><span className="text-muted">WR:</span>{' '}<span className={clsx('font-mono', bt.wr >= 50 ? 'pos' : 'text-gold')}>{bt.wr}%</span></div>
                <div><span className="text-muted">PF:</span>{' '}<span className={clsx('font-mono', bt.pf >= 1.5 ? 'pos' : bt.pf >= 1 ? 'text-gold' : 'neg')}>{bt.pf === 0 ? '—' : fmt(bt.pf)}</span></div>
                <div><span className="text-muted">PnL:</span>{' '}<span className={clsx('font-mono', bt.pnl >= 0 ? 'pos' : 'neg')}>{bt.pnl >= 0 ? '+' : ''}${fmt(bt.pnl)}</span></div>
                <div><span className="text-muted">Max DD:</span>{' '}<span className={clsx('font-mono', bt.maxDD <= 5 ? 'pos' : 'neg')}>{bt.maxDD}%</span></div>
                <div><span className="text-muted">Status:</span>{' '}<span className={bt.trades > 0 ? 'text-gold' : 'text-muted'}>{bt.trades > 0 ? '🟡 DEV' : '⏳ Sin señales'}</span></div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Recent trades */}
      {session?.recent_trades?.length > 0 && (
        <div className="card border-border">
          <div className="flex items-center gap-2 mb-4">
            <span className="text-lg">📋</span>
            <span className="font-semibold text-sm text-white">Trades Recientes</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="text-muted border-b border-border">
                  <th className="text-left py-2 pr-4">Par</th>
                  <th className="text-left py-2 pr-4">Side</th>
                  <th className="text-right py-2 pr-4">Entry</th>
                  <th className="text-right py-2 pr-4">Exit</th>
                  <th className="text-right py-2 pr-4">PnL</th>
                  <th className="text-left py-2">Reason</th>
                </tr>
              </thead>
              <tbody>
                {session.recent_trades.map((t: any, i: number) => (
                  <tr key={i} className="border-b border-border/50 hover:bg-white/[0.02]">
                    <td className="py-2 pr-4 text-white">{t.asset}</td>
                    <td className="py-2 pr-4"><span className={clsx(pnlClass(t.pnl))}>{t.side}</span></td>
                    <td className="py-2 pr-4 text-right text-white">${fmt(t.entry_price, 4)}</td>
                    <td className="py-2 pr-4 text-right text-white">${fmt(t.exit_price, 4)}</td>
                    <td className={clsx('py-2 pr-4 text-right font-semibold', pnlClass(t.pnl))}>{fmtPnl(t.pnl)}</td>
                    <td className="py-2 text-muted text-[10px]">{t.close_reason}</td>
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
