import type { Metadata, Viewport } from 'next'
import './globals.css'
import AppShell from '@/components/AppShell'
import LiveTicker from '@/components/LiveTicker'

export const metadata: Metadata = {
  title: 'ARTHAS — Trading System',
  description: 'Multi-agent algorithmic trading dashboard — Crypto, Stocks, Polymarket, Options, BTC Direction',
  icons: { icon: '/favicon.ico' },
}

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  maximumScale: 1,
  themeColor: '#0D1117',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body className="bg-bg text-white overflow-x-hidden">
        <LiveTicker />
        <AppShell>{children}</AppShell>
      </body>
    </html>
  )
}
