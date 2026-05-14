import { api } from '@/lib/api'
import { fmt, fmtPnl } from '@/lib/fmt'
import { clsx } from 'clsx'

export const revalidate = 60

export default async function KalshiArbPage() {
  let signals: any[] = []
  let stats: any = {}
  try {
    const [sr, st] = await Promise.allSettled([
      api.get<any[]>('/kalshi-arb/signals?limit=20'),
      api.get<any>('/kalshi-arb/stats'),
    ])
    signals = sr.status === 'fulfilled' ? sr.value : []
    stats = st.status === 'fulfilled' ? st.value : {}
  } catch {}

  return (
    <div className="space-y-6 animate-[fadeIn_0.4s_ease-out]">
      <div>
        <h1 className="text-xl sm:text-2xl font-bold text-white tracking-tight">Kalshi Arbitrage</h1>
        <p className="text-xs sm:text-sm text-muted mt-1">
          Polymarket ↔ Kalshi · BTC 1-Hour · arbitraje sin riesgo · paper trading
        </p>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          ['Señales 24h', String(stats.signals_24h ?? 0), 'text-white'],
          ['Profit Est.', fmtPnl(stats.profit_24h ?? 0), (stats.profit_24h ?? 0) >= 0 ? 'pos' : 'neg'],
          ['Avg Profit %', `${fmt(stats.avg_profit_pct ?? 0, 1)}%`, 'text-gold'],
          ['Capital', `$${fmt(stats.capital ?? 500, 0)}`, 'text-blue'],
        ].map(([label, value, cls]) => (
          <div key={label as string} className="card">
            <div className="text-[9px] sm:text-[10px] text-muted uppercase tracking-wider mb-1">{label as string}</div>
            <div className={clsx('text-lg sm:text-xl font-mono font-bold', cls as string)}>{value}</div>
          </div>
        ))}
      </div>

      <div className="card border-gold/15">
        <div className="flex items-center gap-2 mb-4">
          <span className="text-lg">💰</span>
          <span className="font-semibold text-sm text-white">Estrategia de Arbitraje</span>
        </div>
        <div className="space-y-2 text-xs sm:text-sm text-muted">
          <p><b>Arbitraje sin riesgo:</b> comprar posiciones opuestas en Polymarket y Kalshi cuando el costo total es menor a $1.00.</p>
          <ul className="list-disc list-inside space-y-1 text-xs">
            <li><b>Estrategia A:</b> Poly Down + Kalshi Yes. Si BTC {'>'} strike → Kalshi gana. Si BTC {'<='} strike → Poly gana.</li>
            <li><b>Estrategia B:</b> Poly Up + Kalshi No. Si BTC {'>'} strike → Poly gana. Si BTC {'<='} strike → Kalshi gana.</li>
            <li>Profit = $1.00 - costo_total. Garantizado si costo {'<'} $1.00.</li>
            <li>Entrada: costo total {'<'} $0.995 (0.5% profit mínimo).</li>
            <li>Capital requerido: ~$500-$1,000 entre ambas plataformas.</li>
          </ul>
        </div>
      </div>

      {signals.length > 0 && (
        <div className="card border-border">
          <div className="flex items-center gap-2 mb-4">
            <span className="text-lg">📋</span>
            <span className="font-semibold text-sm text-white">Últimas Señales</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="text-muted border-b border-border">
                  <th className="text-left py-2 pr-4">Estrategia</th>
                  <th className="text-right py-2 pr-4">Poly</th>
                  <th className="text-right py-2 pr-4">Kalshi</th>
                  <th className="text-right py-2 pr-4">Costo</th>
                  <th className="text-right py-2 pr-4">Profit</th>
                  <th className="text-right py-2">%</th>
                </tr>
              </thead>
              <tbody>
                {signals.map((s: any, i: number) => (
                  <tr key={i} className="border-b border-border/50 hover:bg-white/[0.02]">
                    <td className="py-2 pr-4 text-gold">{s.strategy}</td>
                    <td className="py-2 pr-4 text-right">${fmt(s.poly_price, 4)}</td>
                    <td className="py-2 pr-4 text-right">${fmt(s.kalshi_price, 4)}</td>
                    <td className="py-2 pr-4 text-right">${fmt(s.total_cost, 4)}</td>
                    <td className="py-2 pr-4 text-right pos">${fmt(s.profit_per_unit, 4)}</td>
                    <td className="py-2 text-right text-gold">{fmt(s.profit_pct, 1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
