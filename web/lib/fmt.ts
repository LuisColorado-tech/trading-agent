export function fmt(v: number | null | undefined, decimals = 2): string {
  if (v == null || isNaN(v)) return '—'
  return v.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
}

export function fmtPnl(v: number | null | undefined): string {
  if (v == null || isNaN(v)) return '—'
  const sign = v >= 0 ? '+' : ''
  return `${sign}$${fmt(v)}`
}

export function fmtPct(v: number | null | undefined): string {
  if (v == null || isNaN(v)) return '—'
  const sign = v >= 0 ? '+' : ''
  return `${sign}${fmt(v, 1)}%`
}

export function pnlClass(v: number | null | undefined): string {
  if (v == null) return 'neutral'
  return v > 0 ? 'pos' : v < 0 ? 'neg' : 'neutral'
}

export function timeAgo(ts: string | null): string {
  if (!ts) return '—'
  const diff = Date.now() - new Date(ts).getTime()
  const m = Math.floor(diff / 60000)
  if (m < 1) return 'ahora'
  if (m < 60) return `hace ${m}m`
  const h = Math.floor(m / 60)
  if (h < 24) return `hace ${h}h`
  return `hace ${Math.floor(h / 24)}d`
}
