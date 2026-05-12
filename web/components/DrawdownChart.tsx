'use client'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'

interface Props {
  data: { date: string; equity: number; drawdown: number }[] | null
}

export default function DrawdownChart({ data }: Props) {
  if (!data || data.length < 2) {
    return (
      <div className="card border-border h-full flex items-center justify-center">
        <span className="text-sm text-muted">No drawdown data</span>
      </div>
    )
  }

  const maxEquity = Math.max(...data.map(d => d.equity))
  const yDomain = [maxEquity * 0.92, maxEquity * 1.02]

  return (
    <div className="card border-border h-full">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-sm font-semibold text-white">Drawdown</span>
      </div>
      <ResponsiveContainer width="100%" height={200}>
        <AreaChart data={data} margin={{ top: 0, right: 0, left: -10, bottom: 0 }}>
          <defs>
            <linearGradient id="ddFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#FF3864" stopOpacity={0.3} />
              <stop offset="100%" stopColor="#FF3864" stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis dataKey="date" hide />
          <YAxis domain={yDomain} hide />
          <Tooltip
            contentStyle={{
              background: '#161B22', border: '1px solid #30363D',
              borderRadius: 8, fontSize: 12,
            }}
            labelStyle={{ color: '#8B949E' }}
            formatter={(v: any) => [`$${Number(v).toFixed(2)}`, 'Equity']}
          />
          <Area type="monotone" dataKey="equity" stroke="#00FF87" strokeWidth={1.5}
                fill="url(#ddFill)" dot={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
