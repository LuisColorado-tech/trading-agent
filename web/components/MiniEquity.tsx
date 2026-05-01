'use client'
import { AreaChart, Area, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

interface Point { ts?: string | null; balance?: number; total_balance?: number; [key: string]: any }

export default function MiniEquity({ data, dataKey = 'balance', color = '#00FF87', height = 80 }: {
  data: Point[]
  dataKey?: string
  color?: string
  height?: number
}) {
  if (!data || data.length < 2) {
    return <div className="flex items-center justify-center text-xs text-muted" style={{ height }}>Sin datos</div>
  }

  const values = data.map(d => Number(d[dataKey])).filter(v => !isNaN(v))
  if (values.length < 2) {
    return <div className="flex items-center justify-center text-xs text-muted" style={{ height }}>Sin datos</div>
  }

  const min = Math.min(...values)
  const max = Math.max(...values)
  const first = values[0]
  const last = values[values.length - 1]
  const pct = first > 0 ? ((last - first) / first * 100) : 0

  return (
    <div>
      <div className={`text-xs font-mono mb-1 ${pct >= 0 ? 'pos' : 'neg'}`}>
        {pct >= 0 ? '+' : ''}{pct.toFixed(1)}% desde inicio
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={data} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id={`eq-${dataKey}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={color} stopOpacity={0.15} />
              <stop offset="95%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis dataKey="ts" hide />
          <YAxis domain={[min * 0.995, max * 1.005]} hide />
          <Tooltip
            contentStyle={{ background: '#111118', border: '1px solid #1e1e2a', borderRadius: 8, fontSize: 11 }}
            labelStyle={{ color: '#6b7280' }}
            formatter={(v: any) => [`$${Number(v).toFixed(2)}`, 'Balance']}
          />
          <Area type="monotone" dataKey={dataKey} stroke={color} strokeWidth={1.5} fill={`url(#eq-${dataKey})`} dot={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
