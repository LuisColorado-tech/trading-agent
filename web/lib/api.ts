const API = typeof window !== 'undefined'
  ? 'http://187.77.5.109:8000'      // browser → public IP
  : process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'  // server → localhost

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API}${path}`, { cache: 'no-store' })
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`)
  return res.json()
}

export const api = {
  overview:           () => get<any>('/overview/'),
  consortium:         () => get<any>('/overview/consortium'),
  dailyPnl:           () => get<any[]>('/overview/daily-pnl'),
  stocksSession:      (scope?: string) => get<any>(`/stocks/session?scope=${scope ?? 'session'}`),
  stocksUniverse:     (scope?: string) => get<any[]>(`/stocks/universe?scope=${scope ?? 'session'}`),
  stocksTrades:       (scope?: string, limit?: number) => get<any[]>(`/stocks/trades?scope=${scope ?? 'session'}&limit=${limit ?? 200}`),
  stocksOpenTrades:   () => get<any[]>('/stocks/trades/open'),
  stocksEquity:       (scope?: string) => get<any[]>(`/stocks/trades/equity?scope=${scope ?? 'session'}`),
  stocksDailyPnl:     () => get<any[]>('/stocks/stats/daily-pnl'),
  stocksByStrategy:   (scope?: string) => get<any[]>(`/stocks/stats/by-strategy?scope=${scope ?? 'session'}`),
  cryptoPortfolio:    (scope?: string) => get<any>(`/crypto/portfolio?scope=${scope ?? 'session'}`),
  cryptoHistory:      (scope?: string) => get<any[]>(`/crypto/portfolio/history?scope=${scope ?? 'session'}`),
  cryptoTrades:       (scope?: string, limit?: number) => get<any[]>(`/crypto/trades?scope=${scope ?? 'session'}&limit=${limit ?? 200}`),
  cryptoStats:        (scope?: string) => get<any>(`/crypto/trades/stats?scope=${scope ?? 'session'}`),
  cryptoSignals:      () => get<any[]>('/crypto/signals'),
  cryptoDailyPnl:     (scope?: string) => get<any[]>(`/crypto/stats/daily-pnl?scope=${scope ?? 'session'}`),
  cryptoByStrategy:   (scope?: string) => get<any>(`/crypto/stats/by-strategy?scope=${scope ?? 'session'}`),
  cryptoByAsset:      (scope?: string) => get<any[]>(`/crypto/stats/by-asset?scope=${scope ?? 'session'}`),
  cryptoStrategyTrades: (strategy: string) => get<any[]>(`/crypto/trades/by-strategy?strategy=${strategy}`),
  polySession:        () => get<any>('/polymarket/session'),
  polyPositions:      (params?: string) => get<any[]>(`/polymarket/positions${params ? '?' + params : ''}`),
  polyStats:          (scope?: string) => get<any>(`/polymarket/stats?scope=${scope ?? 'session'}`),
  optionsSession:     () => get<any>('/options/session'),
  optionsPositions:   (limit?: number, scope?: string) => get<any[]>(`/options/positions?limit=${limit ?? 200}${scope ? '&scope=' + scope : ''}`),
  optionsStats:       (scope?: string) => get<any>(`/options/stats${scope ? '?scope=' + scope : ''}`),
  btcDirection:       (limit?: number) => get<any[]>(`/polymarket/btc-direction?limit=${limit ?? 100}`),
  snipe:              (limit?: number, scope?: string) => get<any[]>(`/polymarket/snipe?scope=${scope ?? 'session'}&limit=${limit ?? 200}`),
  snipeStats:         (scope?: string) => get<any>(`/polymarket/snipe/stats?scope=${scope ?? 'session'}`),
  prices:             () => get<any>('/live/prices'),
  gridStableTrades: (scope?: string, limit?: number) => {
    const s = scope ?? 'recent'
    return get<any[]>(`/grid-stable/trades?scope=${s}${s === 'recent' ? '&days=30' : ''}&limit=${limit ?? 200}`)
  },
  gridStableStats: (scope?: string) => {
    const s = scope ?? 'recent'
    return get<any>(`/grid-stable/stats?scope=${s}${s === 'recent' ? '&days=30' : ''}`)
  },
  gridStableDaily:    () => get<any[]>('/grid-stable/stats/daily'),
  risk:               () => get<any>('/overview/risk'),
  pairsSession:       () => get<any>('/pairs/session'),
  get:                <T>(path: string) => get<T>(path),
}
