'use client'
import { useEffect, useRef, useState } from 'react'
import { AreaChart, Area, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

interface Point { ts: string | null; balance: number }

export default function MiniEquity({ data, color = '#00FF87' }: { data: Point[]; color?: string }) {
  if (!data || data.length < 2) {
    return <div className="h-16 flex items-center justify-center text-xs text-muted">Sin datos</div>
  }

  const min = Math.min(...data.map(d => d.balance))
  const max = Math.max(...data.map(d => d.balance))
  const pct = ((data[data.length - 1].balance - data[0].balance) / data[0].balance * 100)

  return (
    <div>
      <div className={`text-xs font-mono mb-1 ${pct >= 0 ? 'text-green' : 'text-red'}`}>
        {pct >= 0 ? '+' : ''}{pct.toFixed(1)}% desde inicio
      </div>
      <ResponsiveContainer width="100%" height={80}>
        <AreaChart data={data} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={color} stopOpacity={0.2} />
              <stop offset="95%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis dataKey="ts" hide />
          <YAxis domain={[min * 0.995, max * 1.005]} hide />
          <Tooltip
            contentStyle={{ background: '#161B22', border: '1px solid #30363D', borderRadius: 8, fontSize: 11 }}
            labelStyle={{ color: '#8B949E' }}
            formatter={(v: any) => [`$${Number(v).toFixed(2)}`, 'Balance']}
          />
          <Area type="monotone" dataKey="balance" stroke={color} strokeWidth={1.5} fill="url(#eq)" dot={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
