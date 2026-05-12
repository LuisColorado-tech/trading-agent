import Link from 'next/link'
import { fmt, fmtPnl, fmtPct, pnlClass } from '@/lib/fmt'
import { clsx } from 'clsx'

interface Props {
  title: string
  icon: string
  href?: string
  sessionName?: string
  balance?: number
  pnl?: number
  winRate?: number
  profitFactor?: number
  openTrades?: number
  totalTrades?: number
  drawdown?: number
  extra?: { label: string; value: string; cls?: string }[]
  status?: string
  color?: 'green' | 'blue' | 'gold' | 'purple' | 'orange' | 'red'
}

const colorMap: Record<string, string> = {
  green:  'border-green/20 hover:border-green/40',
  blue:   'border-blue/20 hover:border-blue/40',
  gold:   'border-gold/20 hover:border-gold/40',
  purple: 'border-purple/20 hover:border-purple/40',
  orange: 'border-orange/20 hover:border-orange/40',
  red:    'border-red/20 hover:border-red/40',
}

const statusBadge: Record<string, { label: string; cls: string }> = {
  ACTIVE:  { label: 'LIVE', cls: 'badge-green' },
  FAILED:  { label: 'FAIL', cls: 'badge-red' },
  COMPLETED: { label: 'DONE', cls: 'badge-blue' },
  no_data: { label: 'OFF', cls: 'badge-muted' },
  error:   { label: 'ERR', cls: 'badge-red' },
}

export default function AgentCard({
  title, icon, href, sessionName, balance, pnl, winRate, profitFactor,
  openTrades, totalTrades, drawdown, extra = [],
  status = 'ACTIVE', color = 'green',
}: Props) {
  const isActive = status === 'ACTIVE'
  const badge = statusBadge[status] ?? { label: status, cls: 'badge-muted' }

  const card = (
    <div className={clsx(
      'card transition-all duration-200 group',
      href ? 'cursor-pointer hover:scale-[1.02]' : 'cursor-default',
      colorMap[color] ?? colorMap.green
    )}>
      {/* Header */}
      <div className="flex items-center justify-between mb-2.5 sm:mb-3">
        <div className="flex items-center gap-2 sm:gap-2.5 min-w-0">
          <span className="text-base sm:text-lg flex-shrink-0">{icon}</span>
          <div className="min-w-0">
            <span className="font-semibold text-xs sm:text-sm text-white truncate block">{title}</span>
            {sessionName && (
              <div className="text-[9px] sm:text-[10px] font-mono text-muted mt-0.5 truncate">{sessionName}</div>
            )}
          </div>
        </div>
        <span className={clsx('badge text-[9px] sm:text-[10px] flex-shrink-0', badge.cls)}>{badge.label}</span>
      </div>

      {/* Balance & PnL */}
      <div className="flex items-end justify-between mb-3 sm:mb-4">
        <div>
          <div className="text-[9px] sm:text-[10px] text-muted uppercase tracking-wider mb-1">Balance</div>
          <div className="text-lg sm:text-xl font-mono font-bold text-white">
            ${balance != null ? fmt(balance, 0) : '—'}
          </div>
        </div>
        {pnl != null && (
          <div className={clsx('text-right', pnlClass(pnl))}>
            <div className="text-[9px] sm:text-[10px] uppercase tracking-wider mb-1 opacity-70">P&L</div>
            <div className="text-xs sm:text-sm font-mono font-semibold">{fmtPnl(pnl)}</div>
          </div>
        )}
      </div>

      {/* KPI grid */}
      <div className="grid grid-cols-2 gap-x-3 sm:gap-x-4 gap-y-2.5 sm:gap-y-3">
        {winRate != null && (
          <div>
            <div className="text-[9px] sm:text-[10px] text-muted uppercase tracking-wider mb-0.5">Win Rate</div>
            <div className="text-xs sm:text-sm font-mono font-semibold text-white">{fmtPct(winRate)}</div>
          </div>
        )}
        {profitFactor != null && (
          <div>
            <div className="text-[9px] sm:text-[10px] text-muted uppercase tracking-wider mb-0.5">PF</div>
            <div className={clsx('text-xs sm:text-sm font-mono font-semibold',
              profitFactor >= 1.5 ? 'pos' : profitFactor >= 1.0 ? 'text-gold' : 'neg'
            )}>{fmt(profitFactor)}</div>
          </div>
        )}
        {totalTrades != null && (
          <div>
            <div className="text-[9px] sm:text-[10px] text-muted uppercase tracking-wider mb-0.5">Trades</div>
            <div className="text-xs sm:text-sm font-mono font-semibold text-white">{totalTrades}</div>
          </div>
        )}
        {openTrades != null && (
          <div>
            <div className="text-[9px] sm:text-[10px] text-muted uppercase tracking-wider mb-0.5">Abiertos</div>
            <div className={clsx('text-xs sm:text-sm font-mono font-semibold',
              openTrades > 0 ? 'text-blue' : 'text-muted'
            )}>{openTrades}</div>
          </div>
        )}
        {drawdown != null && (
          <div>
            <div className="text-[9px] sm:text-[10px] text-muted uppercase tracking-wider mb-0.5">Drawdown</div>
            <div className={clsx('text-xs sm:text-sm font-mono font-semibold',
              drawdown > 8 ? 'neg' : drawdown > 4 ? 'text-gold' : 'pos'
            )}>-{fmtPct(drawdown)}</div>
          </div>
        )}
        {extra.map(({ label, value, cls }) => (
          <div key={label}>
            <div className="text-[9px] sm:text-[10px] text-muted uppercase tracking-wider mb-0.5">{label}</div>
            <div className={clsx('text-xs sm:text-sm font-mono font-semibold', cls ?? 'text-white')}>{value}</div>
          </div>
        ))}
      </div>
    </div>
  )

  if (href) {
    return <Link href={href} className="block">{card}</Link>
  }
  return card
}
