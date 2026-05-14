import { api } from '@/lib/api'
import AgentCard from '@/components/AgentCard'
import MiniEquity from '@/components/MiniEquity'
import ConsortiumWidget from '@/components/ConsortiumWidget'
import AllocationChart from '@/components/AllocationChart'
import { fmtPnl } from '@/lib/fmt'
import { clsx } from 'clsx'

export const revalidate = 30

const cardColors: Record<string, 'green'|'blue'|'gold'|'purple'|'red'> = {
  stocks: 'green', crypto: 'blue', polymarket: 'purple', options: 'gold', snipe: 'green', btc_direction: 'red',
}

export default async function OverviewPage() {
  const [overview, cryptoHistory, stocksEquity, consortiumRes, byStratRes, pairsRes] = await Promise.allSettled([
    api.overview(),
    api.cryptoHistory(),
    api.stocksEquity(),
    api.consortium(),
    api.cryptoByStrategy(),
    api.pairsSession(),
  ])

  const ov = overview.status === 'fulfilled' ? overview.value : {}
  const history = cryptoHistory.status === 'fulfilled' ? cryptoHistory.value : []
  const seq = stocksEquity.status === 'fulfilled' ? stocksEquity.value : []
  const consortium = consortiumRes.status === 'fulfilled' ? consortiumRes.value : null
  const csStats = byStratRes.status === 'fulfilled' ? byStratRes.value : {}
  const pairsData = pairsRes.status === 'fulfilled' ? pairsRes.value : null

  const s = ov.stocks ?? {}
  const c = ov.crypto ?? {}
  const p = ov.polymarket ?? {}
  const o = ov.options ?? {}
  const sp = ov.snipe ?? {}
  const b = ov.btc_direction ?? {}
  const gb = csStats['GRID_BOT'] ?? {}
  const tm = csStats['TREND_MOMENTUM'] ?? {}

  // Grid Stable real data from consortium
  const gsAlloc = consortium?.allocation?.find((a: any) => a.agent === 'Grid Stable')
  const gsBalance = gsAlloc?.balance ?? 500
  const gsSession = (gsAlloc?.balance ?? 0) > 500 ? 'GRID_STABLE (+)' : 'GRID_STABLE'

  // Consolidated P&L
  const consolidated = [s.total_pnl, c.total_pnl, p.total_pnl, o.total_pnl, sp.total_pnl]
    .filter((v): v is number => v != null)
    .reduce((a, b) => a + b, 0)

  // Agent status counts
  const activeCount = consortium?.active_agents ?? 0

  return (
    <div className="space-y-6 animate-[fadeIn_0.4s_ease-out]">
      {/* Header row */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 mb-4">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-white tracking-tight">ARTHAS Trading System</h1>
          <p className="text-xs sm:text-sm text-muted mt-1">
            {activeCount}/8 agentes activos · paper trading · v4
          </p>
        </div>
        <div className="sm:text-right">
          <div className="text-[9px] sm:text-[10px] text-muted uppercase tracking-wider mb-0.5">P&L Consolidado</div>
          <div className={clsx('text-lg sm:text-xl font-mono font-bold', consolidated >= 0 ? 'pos' : 'neg')}>
            {fmtPnl(consolidated)}
          </div>
        </div>
      </div>

      {/* Consortium widget */}
      <ConsortiumWidget />

      {/* Agent cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3 sm:gap-4">
        <AgentCard
          title="Stocks — NYSE/NASDAQ"
          icon="📈"
          href="/stocks"
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
          title="TrendMomentum — SELL v3"
          icon="₿"
          href="/crypto"
          sessionName={c.session_name}
          balance={c.balance}
          pnl={tm.total_pnl ?? 0}
          winRate={tm.win_rate ?? 0}
          profitFactor={tm.profit_factor ?? 0}
          openTrades={tm.open_trades ?? 0}
          totalTrades={tm.total_trades ?? 0}
          drawdown={c.drawdown_pct ? c.drawdown_pct * 100 : 0}
          status={c.status}
          color={cardColors.crypto}
          extra={[{ label: 'v3', value: 'MIN_SCORE=75·7 assets', cls: 'text-blue' }]}
        />

        <AgentCard
          title="Grid Bot — Range v4"
          icon="📊"
          href="/grid-bot"
          sessionName="GRID_BOT"
          balance={10000}
          pnl={gb.total_pnl ?? 0}
          winRate={gb.win_rate ?? 0}
          profitFactor={gb.profit_factor ?? 0}
          openTrades={gb.open_trades ?? 0}
          totalTrades={gb.total_trades ?? 0}
          drawdown={0}
          status="ACTIVE"
          color="blue"
          extra={[
            { label: 'v4', value: 'BUY+SELL·Cooldown', cls: 'text-blue' },
            { label: 'AvgW/L', value: `+$${gb.avg_win ?? 0}/-$${Math.abs(gb.avg_loss ?? 0)}`, cls: 'text-muted' },
          ]}
        />

        <AgentCard
          title="Polymarket v3"
          icon="🔮"
          href="/polymarket"
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
          href="/options"
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
          title="PolySnipe — SNIPE+ARB"
          icon="🎯"
          href="/snipe"
          sessionName={sp.session_name}
          balance={sp.balance}
          pnl={sp.total_pnl}
          winRate={sp.win_rate}
          openTrades={sp.open_trades}
          totalTrades={sp.total_trades}
          status={sp.status}
          color={cardColors.snipe}
          extra={[
            { label: 'v1', value: 'SNIPE + ARB 15m', cls: 'text-green' },
            { label: 'Ref', value: 'LuciferForge 94% WR', cls: 'text-muted' },
          ]}
        />

        <AgentCard
          title="BTC Direction (old)"
          icon="₿"
          href="/btc-direction"
          balance={171}
          pnl={b.total_pnl}
          winRate={b.win_rate}
          profitFactor={b.profit_factor}
          openTrades={b.open_trades}
          totalTrades={b.total_trades}
          status={b.status}
          color={cardColors.btc_direction}
          extra={[{ label: '⚠', value: 'Reemplazado por SNIPE', cls: 'text-red' }]}
        />

        <AgentCard
          title="Grid Stable — ETH/BTC"
          icon="📐"
          href="/grid-stable"
          sessionName={gsSession}
          balance={gsBalance}
          pnl={(gsBalance ?? 500) - 500}
          winRate={36.8}
          profitFactor={1.84}
          openTrades={0}
          totalTrades={0}
          drawdown={0.3}
          status="ACTIVE"
          color="gold"
          extra={[
            { label: 'v1', value: `PF=1.84 · $${(gsBalance ?? 500) - 500 > 0 ? '+' : ''}${((gsBalance ?? 500) - 500).toFixed(0)}`, cls: 'text-gold' },
            { label: 'Backtest', value: 'ETH/BTC 12m', cls: 'text-muted' },
          ]}
        />

        <AgentCard
          title="Basis Trade — Spot+Futures"
          icon="📊"
          href="/trades"
          sessionName="BASIS_TRADE"
          balance={500}
          pnl={0}
          winRate={0}
          profitFactor={0}
          openTrades={0}
          totalTrades={0}
          drawdown={0}
          status="DEV"
          color="blue"
          extra={[
            { label: '🟡 DEV', value: 'Funding 8%+ APY', cls: 'text-blue' },
            { label: 'Backtest', value: 'PF=∞ · WR=100%', cls: 'text-muted' },
          ]}
        />

        <AgentCard
          title="VIX Mean Reversion"
          icon="📉"
          href="/trades"
          sessionName="VOL_MEAN_REVERSION"
          balance={514.50}
          pnl={14.50}
          winRate={66.7}
          profitFactor={0.65}
          openTrades={0}
          totalTrades={18}
          drawdown={4.0}
          status="DEV"
          color="purple"
          extra={[
            { label: '🟡 DEV', value: 'VIX > p80 → Long SVXY', cls: 'text-purple' },
            { label: 'Backtest', value: '5Y real · PF=0.65 · WR=67%', cls: 'text-muted' },
          ]}
        />
        
        <AgentCard
          title="Pairs Trading"
          icon="🔗"
          href="/pairs"
          sessionName="PAIRS_TRADING"
          balance={pairsData ? 500 + (pairsData.total_pnl ?? 0) : 500}
          pnl={pairsData?.total_pnl ?? 0}
          winRate={pairsData?.total_trades > 0 ? pairsData.win_rate : 42.9}
          profitFactor={pairsData?.total_trades > 0 ? pairsData.profit_factor : 0.82}
          openTrades={pairsData?.open_trades ?? 0}
          totalTrades={pairsData?.total_trades ?? 0}
          drawdown={1.4}
          status={pairsData ? 'ACTIVE' : 'DEV'}
          color="orange"
          extra={[
            { label: 'pairs', value: 'GLD-SLV · BTC-ETH', cls: 'text-orange' },
            { label: 'Backtest', value: '5Y · PF=0.82', cls: 'text-muted' },
          ]}
        />
        
        <AgentCard
          title="Minervini SEPA"
          icon="🚀"
          href="/trades"
          sessionName="MINERVINI"
          balance={500}
          pnl={0}
          winRate={43.8}
          profitFactor={2.04}
          openTrades={4}
          totalTrades={116}
          drawdown={12.3}
          status="ACTIVE"
          color="green"
          extra={[
            { label: 'BUY-only', value: 'Daily momentum · 3Y BT', cls: 'text-green' },
            { label: 'BT 3Y', value: '116 trades · PF=2.04 · +40%', cls: 'text-muted' },
          ]}
        />
        
        <AgentCard
          title="Kalshi Arbitrage"
          icon="💰"
          href="/kalshi-arb"
          sessionName="KALSHI_ARB"
          balance={500}
          pnl={0}
          winRate={100}
          profitFactor={0}
          openTrades={0}
          totalTrades={0}
          drawdown={0}
          status="DEV"
          color="gold"
          extra={[
            { label: '🆕 NEW', value: 'Poly ↔ Kalshi risk-free', cls: 'text-gold' },
            { label: 'Math', value: 'cost < $1.00 = profit', cls: 'text-muted' },
          ]}
        />
      </div>

      {/* Allocation + Equity charts */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 sm:gap-4">
        <div className="card">
          <AllocationChart data={[
            { agent: 'Crypto', balance: c.balance ?? 0 },
            { agent: 'Stocks', balance: s.balance ?? 0 },
            { agent: 'Polymarket', balance: p.balance ?? 0 },
            { agent: 'Options', balance: o.balance ?? 0 },
            { agent: 'PolySnipe', balance: sp.balance ?? 0 },
            { agent: 'Grid Stable', balance: gsBalance },
          ]} />
        </div>
        <div className="card">
          <div className="text-xs text-muted uppercase tracking-wider mb-3">Crypto Equity Curve</div>
          <MiniEquity data={history} dataKey="total_balance" color="#58A6FF" height={140} />
        </div>
        <div className="card">
          <div className="text-xs text-muted uppercase tracking-wider mb-3">Stocks Equity Curve</div>
          <MiniEquity data={seq} dataKey="balance" color="#00FF87" height={140} />
        </div>
      </div>

      {/* Footer info */}
      <div className="flex items-center gap-4 text-[10px] text-muted font-mono">
        <span>DB: PostgreSQL</span>
        <span>·</span>
        <span>API: FastAPI :8000</span>
        <span>·</span>
        <span>Frontend: Next.js 14 · v4</span>
        <span>·</span>
        <span className="text-green">Streamlit desactivado</span>
      </div>
    </div>
  )
}
