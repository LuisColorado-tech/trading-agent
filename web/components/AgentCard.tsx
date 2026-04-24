import { fmt, fmtPnl, fmtPct, pnlClass } from '@/lib/fmt'
import { clsx } from 'clsx'

interface Props {
  title: string
  icon: string
  balance?: number
  pnl?: number
  winRate?: number
  profitFactor?: number
  openTrades?: number
  totalTrades?: number
  drawdown?: number
  extra?: { label: string; value: string; cls?: string }[]
  status?: string
  color?: 'green' | 'blue' | 'gold' | 'purple' | 'orange'
}

const colorMap: Record<string, string> = {
  green:  'border-green/20 hover:border-green/40',
  blue:   'border-blue/20 hover:border-blue/40',
  gold:   'border-gold/20 hover:border-gold/40',
  purple: 'border-purple/20 hover:border-purple/40',
  orange: 'border-orange/20 hover:border-orange/40',
}

const dotColorMap: Record<string, string> = {
  green: 'bg-green', blue: 'bg-blue', gold: 'bg-gold', purple: 'bg-purple', orange: 'bg-orange',
}

export default function AgentCard({
  title, icon, balance, pnl, winRate, profitFactor,
  openTrades, totalTrades, drawdown, extra = [],
  status = 'active', color = 'green',
}: Props) {
  const isActive = status === 'active'

  return (
    <div className={clsx(
      'card transition-all duration-200 cursor-default',
      colorMap[color] ?? colorMap.green
    )}>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <span className="text-xl">{icon}</span>
          <span className="font-semibold text-sm text-white">{title}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className={clsx(
            'w-1.5 h-1.5 rounded-full',
            isActive ? `${dotColorMap[color]} animate-pulse` : 'bg-muted'
          )} />
          <span className="text-[10px] font-mono text-muted uppercase tracking-wider">
            {isActive ? 'live' : 'offline'}
          </span>
        </div>
      </div>

      {/* Balance & PnL */}
      {balance != null && (
        <div className="mb-3">
          <div className="text-[10px] text-muted uppercase tracking-wider mb-0.5">Balance</div>
          <div className="text-2xl font-mono font-bold text-white">${fmt(balance, 0)}</div>
        </div>
      )}

      {pnl != null && (
        <div className={clsx('text-sm font-mono font-semibold mb-4', pnlClass(pnl))}>
          {fmtPnl(pnl)} total P&L
        </div>
      )}

      {/* KPI grid */}
      <div className="grid grid-cols-2 gap-3">
        {winRate != null && (
          <div>
            <div className="text-[10px] text-muted uppercase tracking-wider mb-0.5">Win Rate</div>
            <div className="text-lg font-mono font-semibold text-white">{fmtPct(winRate)}</div>
          </div>
        )}
        {profitFactor != null && (
          <div>
            <div className="text-[10px] text-muted uppercase tracking-wider mb-0.5">Profit Factor</div>
            <div className={clsx('text-lg font-mono font-semibold', profitFactor >= 1.5 ? 'pos' : profitFactor >= 1.0 ? 'text-gold' : 'neg')}>
              {fmt(profitFactor)}
            </div>
          </div>
        )}
        {totalTrades != null && (
          <div>
            <div className="text-[10px] text-muted uppercase tracking-wider mb-0.5">Trades</div>
            <div className="text-lg font-mono font-semibold text-white">{totalTrades}</div>
          </div>
        )}
        {openTrades != null && (
          <div>
            <div className="text-[10px] text-muted uppercase tracking-wider mb-0.5">Abiertos</div>
            <div className={clsx('text-lg font-mono font-semibold', openTrades > 0 ? 'pos' : 'neutral')}>
              {openTrades}
            </div>
          </div>
        )}
        {drawdown != null && (
          <div>
            <div className="text-[10px] text-muted uppercase tracking-wider mb-0.5">Drawdown</div>
            <div className={clsx('text-lg font-mono font-semibold', drawdown > 5 ? 'neg' : drawdown > 2 ? 'text-gold' : 'pos')}>
              -{fmtPct(drawdown)}
            </div>
          </div>
        )}
        {extra.map(({ label, value, cls }) => (
          <div key={label}>
            <div className="text-[10px] text-muted uppercase tracking-wider mb-0.5">{label}</div>
            <div className={clsx('text-lg font-mono font-semibold', cls ?? 'text-white')}>{value}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
