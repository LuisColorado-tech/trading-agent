import { clsx } from 'clsx'

interface Props {
  data: {
    sharpe: number
    sortino: number
    var_95: number
    max_drawdown: number
    max_drawdown_pct: number
    total_return: number
    mean_daily: number
    std_daily: number
    win_days: number
    loss_days: number
    wr_daily: number
    avg_win: number
    avg_loss: number
    days: number
  } | null
}

const kpiDefs = [
  { key: 'sharpe', label: 'Sharpe', fmt: (v: number) => v.toFixed(2), ok: (v: number) => v >= 0.5, warn: (v: number) => v >= 0 },
  { key: 'sortino', label: 'Sortino', fmt: (v: number) => v.toFixed(2), ok: (v: number) => v >= 0.7, warn: (v: number) => v >= 0 },
  { key: 'var_95', label: 'VaR 95%', fmt: (v: number) => `-$${Math.abs(v).toFixed(0)}`, ok: () => true, warn: () => false },
  { key: 'max_drawdown_pct', label: 'Max DD', fmt: (v: number) => `-${v.toFixed(1)}%`, ok: (v: number) => v < 5, warn: (v: number) => v < 10 },
  { key: 'total_return', label: 'Return', fmt: (v: number) => `$${v >= 0 ? '+' : ''}${v.toFixed(0)}`, ok: (v: number) => v >= 0, warn: () => false },
  { key: 'wr_daily', label: 'WR Daily', fmt: (v: number) => `${v.toFixed(1)}%`, ok: (v: number) => v >= 50, warn: () => false },
  { key: 'avg_win', label: 'Avg Win', fmt: (v: number) => `$${v >= 0 ? '+' : ''}${v.toFixed(2)}`, ok: () => true, warn: () => false },
  { key: 'avg_loss', label: 'Avg Loss', fmt: (v: number) => `-$${Math.abs(v).toFixed(2)}`, ok: () => false, warn: () => false },
] as const

export default function RiskPanel({ data }: Props) {
  if (!data || data.days < 30) {
    return (
      <div className="card border-border">
        <div className="text-sm text-muted">📊 Risk panel — {data ? `${data.days} días (<30)` : 'no data'}</div>
      </div>
    )
  }

  return (
    <div className="card border-red/10">
      <div className="flex items-center gap-2 mb-4">
        <span className="text-lg">⚠️</span>
        <span className="font-semibold text-sm text-white">Risk & Performance</span>
        <span className="text-[10px] text-muted ml-auto">{data.days} días</span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {kpiDefs.map(({ key, label, fmt, ok, warn }) => {
          const v = (data as any)[key] as number
          const color = ok(v) ? 'text-green' : warn(v) ? 'text-gold' : 'text-red'
          return (
            <div key={key}>
              <div className="text-[9px] sm:text-[10px] text-muted uppercase tracking-wider mb-1">{label}</div>
              <div className={clsx('text-sm sm:text-base font-mono font-bold', key === 'avg_loss' ? 'text-red' : color)}>
                {fmt(v)}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
