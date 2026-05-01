import { api } from '@/lib/api'
import AgentCard from '@/components/AgentCard'
import MiniEquity from '@/components/MiniEquity'
import { fmtPnl } from '@/lib/fmt'
import { clsx } from 'clsx'

export const revalidate = 30

const cardColors: Record<string, 'green'|'blue'|'gold'|'purple'|'red'> = {
  stocks: 'green', crypto: 'blue', polymarket: 'purple', options: 'gold', btc_direction: 'red',
}

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

  // Consolidated P&L
  const consolidated = [s.total_pnl, c.total_pnl, p.total_pnl, o.total_pnl, b.total_pnl]
    .filter((v): v is number => v != null)
    .reduce((a, b) => a + b, 0)

  // Agent status counts
  const activeCount = [s.status, c.status, p.status, o.status].filter(v => v === 'ACTIVE').length

  return (
    <div className="space-y-6 animate-[fadeIn_0.4s_ease-out]">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">ARTHAS Trading System</h1>
          <p className="text-sm text-muted mt-1">
            {activeCount}/4 agentes activos · paper trading · v3
          </p>
        </div>
        <div className="text-right">
          <div className="text-[10px] text-muted uppercase tracking-wider mb-0.5">P&L Consolidado</div>
          <div className={clsx('text-xl font-mono font-bold', consolidated >= 0 ? 'pos' : 'neg')}>
            {fmtPnl(consolidated)}
          </div>
        </div>
      </div>

      {/* Agent cards */}
      <div className="grid grid-cols-2 xl:grid-cols-3 gap-4">
        <AgentCard
          title="Stocks — NYSE/NASDAQ"
          icon="📈"
          sessionName={s.session_name}
          balance={s.balance}
          pnl={s.total_pnl}
          winRate={s.win_rate}
          profitFactor={s.profit_factor}
          openTrades={s.open_trades}
          totalTrades={s.total_trades}
          drawdown={s.max_drawdown}
          status={s.status}
          color={cardColors.stocks}
          extra={[{ label: 'Universo', value: '10 activos', cls: 'text-blue' }]}
        />

        <AgentCard
          title="Crypto — Kraken v3"
          icon="₿"
          sessionName={c.session_name}
          balance={c.balance}
          pnl={c.total_pnl}
          winRate={c.win_rate}
          profitFactor={c.profit_factor}
          openTrades={c.open_trades}
          totalTrades={c.total_trades}
          drawdown={c.drawdown_pct ? c.drawdown_pct * 100 : 0}
          status={c.status}
          color={cardColors.crypto}
          extra={[{ label: 'v3', value: 'MIN_SCORE=75', cls: 'text-green' }]}
        />

        <AgentCard
          title="Polymarket v3"
          icon="🔮"
          sessionName={p.session_name}
          balance={p.balance}
          pnl={p.total_pnl}
          winRate={p.win_rate}
          profitFactor={p.profit_factor}
          openTrades={p.open_trades}
          totalTrades={p.total_trades}
          drawdown={p.max_drawdown}
          status={p.status}
          color={cardColors.polymarket}
          extra={[{ label: 'v3', value: 'edge fix · min=0.42', cls: 'text-purple' }]}
        />

        <AgentCard
          title="Options — Deribit"
          icon="📣"
          sessionName={o.session_name}
          balance={o.balance}
          pnl={o.total_pnl}
          winRate={o.win_rate}
          openTrades={o.open_trades}
          totalTrades={o.total_trades}
          status={o.status}
          color={cardColors.options}
          extra={o.total_premium ? [{ label: 'Primas', value: `$${o.total_premium}`, cls: 'text-gold' }] : []}
        />

        <AgentCard
          title="BTC Direction"
          icon="₿"
          balance={171}
          pnl={b.total_pnl}
          winRate={b.win_rate}
          profitFactor={b.profit_factor}
          openTrades={b.open_trades}
          totalTrades={b.total_trades}
          status={b.status}
          color={cardColors.btc_direction}
          extra={b.win_rate < 40 ? [{ label: '⚠', value: 'WR < 40% · bajo vigilancia', cls: 'text-red' }] : []}
        />

        <AgentCard
          title="Grid Stable — ETH/BTC"
          icon="📐"
          sessionName="GRID_STABLE"
          balance={500}
          pnl={0}
          winRate={36.8}
          profitFactor={1.84}
          openTrades={0}
          totalTrades={0}
          drawdown={0.3}
          status="ACTIVE"
          color="gold"
          extra={[
            { label: 'v1', value: 'PF=1.84 · DD=0.3%', cls: 'text-gold' },
            { label: 'Backtest', value: 'ETH/BTC 12m', cls: 'text-muted' },
          ]}
        />
      </div>

      {/* Equity charts */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div className="card">
          <div className="text-xs text-muted uppercase tracking-wider mb-3">Crypto Equity Curve</div>
          <MiniEquity data={history} dataKey="total_balance" color="#58A6FF" height={160} />
        </div>
        <div className="card">
          <div className="text-xs text-muted uppercase tracking-wider mb-3">Stocks Equity Curve</div>
          <MiniEquity data={seq} dataKey="balance" color="#00FF87" height={160} />
        </div>
      </div>

      {/* Footer info */}
      <div className="flex items-center gap-4 text-[10px] text-muted font-mono">
        <span>DB: PostgreSQL</span>
        <span>·</span>
        <span>API: FastAPI :8000</span>
        <span>·</span>
        <span>Frontend: Next.js 14</span>
        <span>·</span>
        <span className="text-green">Streamlit desactivado</span>
      </div>
    </div>
  )
}
