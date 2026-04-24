'use client'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { BarChart2, TrendingUp, Activity, PieChart, LayoutDashboard } from 'lucide-react'
import { clsx } from 'clsx'

const NAV = [
  { href: '/',          label: 'Overview',  icon: LayoutDashboard },
  { href: '/stocks',    label: 'Stocks',    icon: TrendingUp },
  { href: '/trades',    label: 'Trades',    icon: Activity },
  { href: '/signals',   label: 'Señales',   icon: BarChart2 },
  { href: '/analytics', label: 'Analytics', icon: PieChart },
]

export default function Sidebar() {
  const path = usePathname()

  return (
    <aside className="fixed left-0 top-9 bottom-0 w-56 bg-surface border-r border-border flex flex-col z-40">
      {/* Logo */}
      <div className="px-5 py-5 border-b border-border">
        <div className="flex items-center gap-2">
          <span className="text-xl">⚡</span>
          <div>
            <div className="text-sm font-semibold text-white">Arthas</div>
            <div className="text-[10px] text-muted font-mono tracking-widest uppercase">Trading Agent</div>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-1">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = path === href || (href !== '/' && path.startsWith(href))
          return (
            <Link
              key={href}
              href={href}
              className={clsx(
                'flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-all duration-150',
                active
                  ? 'bg-green/10 text-green border border-green/20'
                  : 'text-muted hover:text-white hover:bg-white/5'
              )}
            >
              <Icon size={16} strokeWidth={1.5} />
              {label}
            </Link>
          )
        })}
      </nav>

      {/* Footer */}
      <div className="px-5 py-4 border-t border-border">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-green animate-pulse-green" />
          <span className="text-xs text-muted font-mono">LIVE · paper</span>
        </div>
      </div>
    </aside>
  )
}
