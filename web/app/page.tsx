import { api } from '@/lib/api'
import AgentCard from '@/components/AgentCard'
import MiniEquity from '@/components/MiniEquity'
import { fmtPnl } from '@/lib/fmt'

export const revalidate = 30

export default async function OverviewPage() {
  const [overview, cryptoHistory, stocksEquity] = await Promise.allSettled([
    api.overview(),
    api.cryptoHistory(),
    api.stocksEquity(),
  ])

  const ov = overview.status === 'fulfilled' ? overview.value : {}
  const history = cryptoHistory.status === 'fulfilled' ? cryptoHistory.value : []
  const seq = stocksEquity.status === 'fulfilled' ? stocksEquity.value : []

  const s = ov.stocks ?? {}
  const c = ov.crypto ?? {}
  const p = ov.polymarket ?? {}
  const o = ov.options ?? {}
  const b = ov.btc_direction ?? {}

  return (
    <div className="space-y-8 animate-[fadeIn_0.4s_ease-out]">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">Overview</h1>
        <p className="text-sm text-muted mt-1">Todos los agentes en tiempo real — paper trading</p>
      </div>

      {/* Agent cards */}
      <div className="grid grid-cols-2 xl:grid-cols-3 gap-4">
        <AgentCard
          title="Stocks — NYSE/NASDAQ"
          icon="📈"
          balance={s.balance}
          pnl={s.total_pnl}
          winRate={s.win_rate}
          profitFactor={s.profit_factor}
          openTrades={s.open_trades}
          totalTrades={s.total_trades}
          color="green"
          extra={[{ label: 'Universo', value: '10 activos', cls: 'text-blue' }]}
        />

        <AgentCard
          title="Crypto — Kraken"
          icon="₿"
          balance={c.balance}
          pnl={c.total_pnl}
          winRate={c.win_rate}
          profitFactor={c.profit_factor}
          openTrades={c.open_trades}
          totalTrades={c.total_trades}
          drawdown={c.drawdown_pct ? c.drawdown_pct * 100 : undefined}
          color="blue"
        />

        <AgentCard
          title="Polymarket"
          icon="🔮"
          balance={p.balance}
          pnl={p.total_pnl}
          winRate={p.win_rate}
          profitFactor={p.profit_factor}
          totalTrades={p.total_trades}
          color="purple"
        />

        <AgentCard
          title="Options — Deribit"
          icon="📣"
          balance={o.balance}
          pnl={o.total_pnl}
          winRate={o.win_rate}
          totalTrades={o.total_trades}
          extra={[{ label: 'Primas', value: o.total_premium ? `$${o.total_premium}` : '—', cls: 'text-gold' }]}
          color="gold"
        />

        <AgentCard
          title="BTC Direction"
          icon="🎯"
          pnl={b.total_pnl}
          winRate={b.win_rate}
          profitFactor={b.profit_factor}
          totalTrades={b.total_trades}
          color="orange"
        />
      </div>

      {/* Equity curves */}
      <div className="grid grid-cols-2 gap-4">
        <div className="card">
          <div className="text-sm font-semibold text-white mb-4">Equity Curve — Crypto</div>
          <MiniEquity data={history.map((r: any) => ({ ts: r.timestamp, balance: r.total_balance }))} />
        </div>
        <div className="card">
          <div className="text-sm font-semibold text-white mb-4">Equity Curve — Stocks</div>
          <MiniEquity data={seq} color="#58A6FF" />
        </div>
      </div>

      {/* Total P&L summary */}
      <div className="card">
        <div className="text-sm font-semibold text-white mb-4">P&L Consolidado</div>
        <div className="grid grid-cols-5 gap-4 text-center">
          {[
            { label: 'Stocks', val: s.total_pnl },
            { label: 'Crypto', val: c.total_pnl },
            { label: 'Polymarket', val: p.total_pnl },
            { label: 'Options', val: o.total_pnl },
            { label: 'BTC Dir.', val: b.total_pnl },
          ].map(({ label, val }) => (
            <div key={label}>
              <div className="text-xs text-muted mb-1">{label}</div>
              <div className={`text-base font-mono font-bold ${val > 0 ? 'pos' : val < 0 ? 'neg' : 'neutral'}`}>
                {fmtPnl(val)}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
