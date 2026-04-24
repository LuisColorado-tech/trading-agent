const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API}${path}`, { next: { revalidate: 30 } })
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`)
  return res.json()
}

export const api = {
  overview:           () => get<any>('/overview/'),
  stocksSession:      () => get<any>('/stocks/session'),
  stocksUniverse:     () => get<any[]>('/stocks/universe'),
  stocksTrades:       (params?: string) => get<any[]>(`/stocks/trades${params ? '?' + params : ''}`),
  stocksOpenTrades:   () => get<any[]>('/stocks/trades/open'),
  stocksEquity:       () => get<any[]>('/stocks/trades/equity'),
  stocksDailyPnl:     () => get<any[]>('/stocks/stats/daily-pnl'),
  stocksByStrategy:   () => get<any[]>('/stocks/stats/by-strategy'),
  cryptoPortfolio:    () => get<any>('/crypto/portfolio'),
  cryptoHistory:      () => get<any[]>('/crypto/portfolio/history'),
  cryptoTrades:       () => get<any[]>('/crypto/trades'),
  cryptoStats:        () => get<any>('/crypto/trades/stats'),
  cryptoSignals:      () => get<any[]>('/crypto/signals'),
  cryptoDailyPnl:     () => get<any[]>('/crypto/stats/daily-pnl'),
  polyStats:          () => get<any>('/polymarket/stats'),
  optionsStats:       () => get<any>('/options/stats'),
  prices:             () => get<any>('/live/prices'),
}
