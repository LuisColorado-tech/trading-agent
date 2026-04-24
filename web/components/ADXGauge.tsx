'use client'

interface Props {
  value: number | null
  size?: number
}

export default function ADXGauge({ value, size = 64 }: Props) {
  const v = value ?? 0
  // Arco semicircular: 0-100 mapeado a 180°
  const angle = Math.min(v / 100, 1) * 180
  const r = size * 0.38
  const cx = size / 2
  const cy = size / 2 + size * 0.08
  const startX = cx - r
  const startY = cy
  // Punto en el arco
  const rad = ((180 - angle) * Math.PI) / 180
  const endX = cx + r * Math.cos(rad)
  const endY = cy - r * Math.sin(rad)
  const largeArc = angle > 180 ? 1 : 0

  const color = v < 20 ? '#8B949E' : v < 25 ? '#FFD700' : '#00FF87'
  const label = v < 20 ? 'RANGE' : v < 25 ? 'WEAK' : 'TREND'

  return (
    <div className="flex flex-col items-center">
      <svg width={size} height={size * 0.62} viewBox={`0 0 ${size} ${size * 0.62}`}>
        {/* Track */}
        <path
          d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`}
          fill="none" stroke="#30363D" strokeWidth={size * 0.08} strokeLinecap="round"
        />
        {/* Value arc */}
        {v > 0 && (
          <path
            d={`M ${cx - r} ${cy} A ${r} ${r} 0 ${largeArc} 1 ${endX} ${endY}`}
            fill="none" stroke={color} strokeWidth={size * 0.08} strokeLinecap="round"
          />
        )}
        {/* Value text */}
        <text x={cx} y={cy} textAnchor="middle" dominantBaseline="middle"
          fill="white" fontSize={size * 0.22} fontFamily="JetBrains Mono, monospace" fontWeight="700">
          {Math.round(v)}
        </text>
      </svg>
      <span style={{ color, fontSize: 9, fontFamily: 'JetBrains Mono', fontWeight: 600, letterSpacing: '0.08em' }}>
        {label}
      </span>
    </div>
  )
}
