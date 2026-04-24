'use client'

interface DayData { day: string; pnl: number; trades: number }

interface Props {
  data: DayData[]
}

function intensity(pnl: number, maxAbs: number): string {
  if (maxAbs === 0) return 'rgba(139,148,158,0.1)'
  const t = Math.min(Math.abs(pnl) / maxAbs, 1)
  if (pnl > 0) return `rgba(0,255,135,${0.15 + t * 0.7})`
  if (pnl < 0) return `rgba(255,56,100,${0.15 + t * 0.7})`
  return 'rgba(139,148,158,0.1)'
}

export default function PnlCalendar({ data }: Props) {
  if (!data || data.length === 0) {
    return <div className="text-xs text-muted text-center py-8">Sin datos</div>
  }

  const map = Object.fromEntries(data.map(d => [d.day, d]))
  const maxAbs = Math.max(...data.map(d => Math.abs(d.pnl)), 0.01)

  // Generate last 13 weeks (91 days) grid
  const today = new Date()
  const cells: { date: string; pnl: number | null; trades: number }[] = []
  for (let i = 90; i >= 0; i--) {
    const d = new Date(today)
    d.setDate(d.getDate() - i)
    const key = d.toISOString().slice(0, 10)
    const rec = map[key]
    cells.push({ date: key, pnl: rec ? rec.pnl : null, trades: rec ? rec.trades : 0 })
  }

  const weeks: typeof cells[] = []
  let week: typeof cells = []
  cells.forEach((c, i) => {
    week.push(c)
    if (week.length === 7 || i === cells.length - 1) {
      weeks.push(week)
      week = []
    }
  })

  return (
    <div>
      <div className="flex gap-1 flex-wrap">
        {weeks.map((w, wi) => (
          <div key={wi} className="flex flex-col gap-1">
            {w.map((c, di) => (
              <div
                key={di}
                title={c.pnl != null ? `${c.date}: $${c.pnl.toFixed(2)} (${c.trades} trades)` : c.date}
                style={{ background: c.pnl != null ? intensity(c.pnl, maxAbs) : 'rgba(139,148,158,0.05)' }}
                className="w-3 h-3 rounded-sm border border-black/20 cursor-default transition-all hover:scale-125"
              />
            ))}
          </div>
        ))}
      </div>
      <div className="flex items-center gap-3 mt-3 text-[10px] text-muted">
        <span>Menos</span>
        {[-1, -0.5, 0, 0.5, 1].map(v => (
          <div key={v} className="w-3 h-3 rounded-sm" style={{ background: intensity(v * maxAbs, maxAbs) }} />
        ))}
        <span>Más</span>
        <span className="ml-auto">🟢 ganancia · 🔴 pérdida</span>
      </div>
    </div>
  )
}
