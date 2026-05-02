'use client'
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts'

const COLORS = ['#58A6FF', '#00FF87', '#BC8CFF', '#FFD700', '#F78166']

interface Props {
  data: { agent: string; balance: number }[]
}

export default function AllocationChart({ data }: Props) {
  if (!data || data.length === 0) {
    return <div className="h-48 flex items-center justify-center text-xs text-muted">Sin datos</div>
  }

  const total = data.reduce((s, d) => s + d.balance, 0)

  return (
    <div>
      <div className="text-xs text-muted uppercase tracking-wider mb-2">Distribución de Capital</div>
      <div className="flex items-center gap-4">
        <ResponsiveContainer width="55%" height={140}>
          <PieChart>
            <Pie
              data={data}
              cx="50%" cy="50%"
              innerRadius={35}
              outerRadius={55}
              paddingAngle={3}
              dataKey="balance"
              nameKey="agent"
            >
              {data.map((_, i) => (
                <Cell key={i} fill={COLORS[i % COLORS.length]} stroke="transparent" />
              ))}
            </Pie>
            <Tooltip
              contentStyle={{ background: '#111118', border: '1px solid #1e1e2a', borderRadius: 8, fontSize: 11 }}
              formatter={(v: any) => [`$${Number(v).toLocaleString()}`, 'Balance']}
            />
          </PieChart>
        </ResponsiveContainer>

        <div className="space-y-1.5 flex-1">
          {data.map((d, i) => (
            <div key={d.agent} className="flex items-center gap-2 text-xs">
              <span className="w-2 h-2 rounded-full" style={{ backgroundColor: COLORS[i % COLORS.length] }} />
              <span className="text-muted flex-1">{d.agent}</span>
              <span className="font-mono text-white">${d.balance.toLocaleString('en-US', { maximumFractionDigits: 0 })}</span>
              <span className="font-mono text-muted w-10 text-right">
                {total > 0 ? (d.balance / total * 100).toFixed(0) : 0}%
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
