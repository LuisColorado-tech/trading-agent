'use client'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { LayoutDashboard, TrendingUp, Activity, BarChart2, PieChart, Bitcoin, Coins, Gem, Target, TrendingDown, Grid3X3, Layers } from 'lucide-react'
import { clsx } from 'clsx'

const NAV = [
  { href: '/',             label: 'Overview',         icon: LayoutDashboard },
  { href: '/stocks',       label: 'Stocks',           icon: TrendingUp },
  { href: '/crypto',       label: 'TrendMomentum',    icon: TrendingDown },
  { href: '/grid-bot',     label: 'Grid Bot',         icon: Grid3X3 },
  { href: '/grid-stable',  label: 'Grid Stable',      icon: Layers },
  { href: '/polymarket',   label: 'Polymarket',       icon: Coins },
  { href: '/options',      label: 'Options',          icon: Gem },
  { href: '/snipe',        label: 'PolySnipe',        icon: Target },
  { href: '/btc-direction',label: 'BTC Dir (old)',    icon: Bitcoin },
  { href: '/trades',       label: 'Trades',           icon: Activity },
  { href: '/signals',      label: 'Señales',          icon: BarChart2 },
  { href: '/analytics',    label: 'Analytics',        icon: PieChart },
]

export default function Sidebar() {
  const path = usePathname()

  return (
    <aside className="fixed left-0 top-9 bottom-0 w-56 bg-surface border-r border-border flex flex-col z-40">
      {/* Logo */}
      <div className="px-5 py-5 border-b border-border">
        <div className="flex items-center gap-2.5">
          <span className="text-xl">⚡</span>
          <div>
            <div className="text-sm font-semibold text-white tracking-tight">ARTHAS</div>
            <div className="text-[10px] text-muted font-mono tracking-widest uppercase">Trading v3</div>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = path === href || (href !== '/' && path.startsWith(href))
          return (
            <Link
              key={href}
              href={href}
              className={clsx(
                'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all duration-150',
                active
                  ? 'bg-green/10 text-green font-medium'
                  : 'text-muted hover:text-white hover:bg-white/[0.04]'
              )}
            >
              <Icon size={16} strokeWidth={1.5} />
              {label}
            </Link>
          )
        })}
      </nav>

      {/* Footer */}
      <div className="px-5 py-4 border-t border-border space-y-2">
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-green animate-pulse" />
          <span className="text-[11px] text-muted font-mono">PAPER TRADING</span>
        </div>
        <div className="flex flex-wrap gap-1">
          <span className="badge badge-green text-[9px]">v3</span>
          <span className="badge badge-blue text-[9px]">8 agents</span>
        </div>
      </div>
    </aside>
  )
}
