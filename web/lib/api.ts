const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API}${path}`, { next: { revalidate: 30 } })
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`)
  return res.json()
}

export const api = {
  overview:           () => get<any>('/overview/'),
  consortium:         () => get<any>('/overview/consortium'),
  dailyPnl:           () => get<any[]>('/overview/daily-pnl'),
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
  cryptoByStrategy:   () => get<any>('/crypto/stats/by-strategy'),
  cryptoByAsset:      () => get<any[]>('/crypto/stats/by-asset'),
  cryptoStrategyTrades: (strategy: string) => get<any[]>(`/crypto/trades/by-strategy?strategy=${strategy}`),
  polySession:        () => get<any>('/polymarket/session'),
  polyPositions:      (params?: string) => get<any[]>(`/polymarket/positions${params ? '?' + params : ''}`),
  polyStats:          () => get<any>('/polymarket/stats'),
  optionsSession:     () => get<any>('/options/session'),
  optionsPositions:   (limit?: number) => get<any[]>(`/options/positions?limit=${limit ?? 200}`),
  optionsStats:       () => get<any>('/options/stats'),
  btcDirection:       (limit?: number) => get<any[]>(`/polymarket/btc-direction?limit=${limit ?? 100}`),
  snipe:              (limit?: number) => get<any[]>(`/polymarket/snipe?limit=${limit ?? 200}`),
  snipeStats:         () => get<any>('/polymarket/snipe/stats'),
  prices:             () => get<any>('/live/prices'),
  gridStableTrades:   (pair?: string) => get<any[]>(`/grid-stable/trades${pair ? '?pair=' + pair : ''}`),
  gridStableStats:    () => get<any>('/grid-stable/stats'),
  gridStableDaily:    () => get<any[]>('/grid-stable/stats/daily'),
}
