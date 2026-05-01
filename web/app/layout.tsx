import type { Metadata } from 'next'
import './globals.css'
import Sidebar from '@/components/Sidebar'
import LiveTicker from '@/components/LiveTicker'

export const metadata: Metadata = {
  title: 'ARTHAS — Trading System',
  description: 'Multi-agent algorithmic trading dashboard — Crypto, Stocks, Polymarket, Options, BTC Direction',
  icons: { icon: '/favicon.ico' },
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body className="bg-bg text-white">
        <LiveTicker />
        <div className="flex">
          <Sidebar />
          <main className="ml-56 flex-1 min-h-screen p-6 mt-0">
            {children}
          </main>
        </div>
      </body>
    </html>
  )
}
