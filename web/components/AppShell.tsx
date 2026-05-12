'use client'
import { useState, useEffect, useCallback } from 'react'
import { Menu, X } from 'lucide-react'
import Sidebar from '@/components/Sidebar'

export default function AppShell({ children }: { children: React.ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [isMobile, setIsMobile] = useState(false)

  const checkMobile = useCallback(() => {
    setIsMobile(window.innerWidth < 1024)
  }, [])

  useEffect(() => {
    checkMobile()
    window.addEventListener('resize', checkMobile)
    return () => window.removeEventListener('resize', checkMobile)
  }, [checkMobile])

  const closeSidebar = () => setSidebarOpen(false)
  const toggleSidebar = () => setSidebarOpen(prev => !prev)

  return (
    <div className="flex min-h-[calc(100vh-36px)]">
      {/* Mobile overlay backdrop */}
      {isMobile && sidebarOpen && (
        <div
          className="fixed inset-0 top-9 bg-black/60 z-40 lg:hidden"
          onClick={closeSidebar}
        />
      )}

      {/* Sidebar */}
      <Sidebar open={sidebarOpen} onClose={closeSidebar} isMobile={isMobile} />

      {/* Main content area */}
      <div className="flex-1 lg:ml-56">
        {/* Mobile header bar */}
        {isMobile && (
          <header className="sticky top-0 z-30 flex items-center gap-3 px-4 h-12 bg-surface/95 backdrop-blur border-b border-border lg:hidden">
            <button
              onClick={toggleSidebar}
              className="p-1.5 rounded-md text-muted hover:text-white hover:bg-white/[0.06] transition-colors"
              aria-label={sidebarOpen ? 'Cerrar menú' : 'Abrir menú'}
            >
              {sidebarOpen ? <X size={20} strokeWidth={1.5} /> : <Menu size={20} strokeWidth={1.5} />}
            </button>
            <div className="flex items-center gap-2">
              <span className="text-lg">⚡</span>
              <span className="text-sm font-semibold text-white tracking-tight">ARTHAS</span>
              <span className="text-[10px] text-muted font-mono tracking-widest uppercase ml-1">v3</span>
            </div>
          </header>
        )}

        <main className="p-3 sm:p-4 lg:p-6">
          {children}
        </main>
      </div>
    </div>
  )
}
