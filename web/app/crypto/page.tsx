import { api } from '@/lib/api'
import MiniEquity from '@/components/MiniEquity'
import { fmt, fmtPnl, fmtPct } from '@/lib/fmt'
import { clsx } from 'clsx'

export const revalidate = 30

export default async function CryptoPage() {
  const [pf, stats, history, trades, signals] = await Promise.allSettled([
    api.cryptoPortfolio(),
    api.cryptoStats(),
    api.cryptoHistory(),
    api.cryptoTrades(),
    api.cryptoSignals(),
  ])

  const portfolio = pf.status === 'fulfilled' ? pf.value : {}
  const st = stats.status === 'fulfilled' ? stats.value : {}
  const hist = history.status === 'fulfilled' ? history.value : []
  const tr = trades.status === 'fulfilled' ? trades.value : []
  const sig = signals.status === 'fulfilled' ? signals.value : []

  const dd = (portfolio.drawdown_pct ?? 0) * 100

  return (
    <div className="space-y-6 animate-[fadeIn_0.4s_ease-out]">
      <div>
        <h1 className="text-2xl font-bold text-white tracking-tight">Crypto — Kraken v3</h1>
        <p className="text-sm text-muted mt-1">
          TREND_MOMENTUM SELL · MIN_SCORE=75 · MAX_CONC=2 · trailing 0.75R
        </p>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-4 xl:grid-cols-8 gap-3">
        {[
          ['Balance', `$${fmt(portfolio.total_balance, 0)}`, 'text-white'],
          ['P&L', fmtPnl(st.total_pnl), st.total_pnl >= 0 ? 'pos' : 'neg'],
          ['Win Rate', fmtPct(st.win_rate), 'text-white'],
          ['PF', fmt(st.profit_factor), st.profit_factor >= 1.3 ? 'pos' : 'text-gold'],
          ['DD', `-${fmtPct(dd)}`, dd > 5 ? 'neg' : 'pos'],
          ['Trades', st.total_trades ?? 0, 'text-white'],
          ['Abiertos', st.open_trades ?? 0, 'text-blue'],
          ['Exposición', `${fmt((portfolio.exposure_pct ?? 0) * 100, 1)}%`, 'text-muted'],
        ].map(([label, value, cls]) => (
          <div key={label as string} className="card text-center">
            <div className="text-[10px] text-muted uppercase tracking-wider mb-1">{label as string}</div>
            <div className={clsx('text-base font-mono font-bold', cls as string)}>{value}</div>
          </div>
        ))}
      </div>

      {/* Equity + Trades */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div className="card xl:col-span-2">
          <div className="text-xs text-muted uppercase tracking-wider mb-3">Equity Curve</div>
          <MiniEquity data={hist} dataKey="total_balance" color="#58A6FF" height={200} />
        </div>
        <div className="card">
          <div className="text-xs text-muted uppercase tracking-wider mb-3">Últimos Trades</div>
          <div className="space-y-1.5 max-h-[200px] overflow-y-auto">
            {tr.slice(0, 12).map((t: any, i: number) => (
              <div key={i} className="flex items-center justify-between text-xs py-0.5 border-b border-border/50 last:border-0">
                <span className="font-mono text-muted">{t.asset}</span>
                <span className={clsx('font-mono', t.pnl > 0 ? 'pos' : 'neg')}>
                  {fmtPnl(t.pnl)}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Señales recientes */}
      <div className="card">
        <div className="text-xs text-muted uppercase tracking-wider mb-3">Señales Recientes</div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-muted text-left">
                <th className="pb-2 font-normal">Asset</th>
                <th className="pb-2 font-normal">TF</th>
                <th className="pb-2 font-normal">Tipo</th>
                <th className="pb-2 font-normal">Dir</th>
                <th className="pb-2 font-normal">Score</th>
                <th className="pb-2 font-normal">Hora</th>
              </tr>
            </thead>
            <tbody>
              {sig.slice(0, 20).map((s: any, i: number) => (
                <tr key={i} className="border-t border-border/30">
                  <td className="py-1.5 font-mono text-white">{s.asset}</td>
                  <td className="py-1.5 font-mono text-muted">{s.timeframe}</td>
                  <td className="py-1.5 font-mono text-muted">{s.signal_type}</td>
                  <td className={clsx('py-1.5 font-mono', s.direction === 'SELL' ? 'neg' : 'pos')}>{s.direction}</td>
                  <td className="py-1.5 font-mono text-white">{fmt(s.score, 1)}</td>
                  <td className="py-1.5 font-mono text-muted">{new Date(s.timestamp).toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' })}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
