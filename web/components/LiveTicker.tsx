'use client'
import { useEffect, useState } from 'react'
import { api } from '@/lib/api'
import { fmt, fmtPct, pnlClass } from '@/lib/fmt'

const TICKERS = ['TSLA', 'AAPL', 'AMZN', 'NVDA', 'META', 'QQQ', 'GLD', 'EEM', 'FXI', 'EWJ']

export default function LiveTicker() {
  const [prices, setPrices] = useState<Record<string, any>>({})

  useEffect(() => {
    const load = () => api.prices().then(setPrices).catch(() => {})
    load()
    const id = setInterval(load, 30000)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="overflow-hidden bg-surface border-b border-border h-9 flex items-center">
      <div className="flex gap-0 animate-[scroll_40s_linear_infinite] whitespace-nowrap">
        {[...TICKERS, ...TICKERS].map((t, i) => {
          const p = prices[t]
          const chg = p?.change_pct ?? 0
          return (
            <span key={i} className="inline-flex items-center gap-1.5 px-4 text-xs font-mono">
              <span className="text-muted">{t}</span>
              <span className="text-white">{p ? `$${fmt(p.price, p.price > 100 ? 2 : 4)}` : '—'}</span>
              <span className={pnlClass(chg)}>{fmtPct(chg)}</span>
              <span className="text-border mx-1">|</span>
            </span>
          )
        })}
      </div>
      <style>{`
        @keyframes scroll {
          0% { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
      `}</style>
    </div>
  )
}
