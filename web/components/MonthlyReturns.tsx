'use client'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'

interface Props {
  data: { month: string; pnl: number }[] | null
}

export default function MonthlyReturns({ data }: Props) {
  if (!data || data.length === 0) {
    return (
      <div className="card border-border h-full flex items-center justify-center">
        <span className="text-sm text-muted">No monthly data</span>
      </div>
    )
  }

  return (
    <div className="card border-border h-full">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-sm font-semibold text-white">Returns Mensuales</span>
      </div>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} margin={{ top: 0, right: 0, left: -10, bottom: 0 }}>
          <XAxis
            dataKey="month"
            tick={{ fill: '#8B949E', fontSize: 10, fontFamily: 'JetBrains Mono' }}
            axisLine={{ stroke: '#30363D' }}
            tickLine={false}
          />
          <YAxis hide />
          <Tooltip
            contentStyle={{
              background: '#161B22', border: '1px solid #30363D',
              borderRadius: 8, fontSize: 12,
            }}
            labelStyle={{ color: '#8B949E' }}
            formatter={(v: any) => [`$${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(2)}`, 'P&L']}
          />
          <Bar dataKey="pnl" radius={[3, 3, 0, 0]} maxBarSize={32}>
            {data.map((entry, i) => (
              <Cell key={i} fill={entry.pnl >= 0 ? '#00FF87' : '#FF3864'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
