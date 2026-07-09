-- ══════════════════════════════════════════════════════════════════════════════
-- 002_xsignals_table.sql
-- Tabla para señales scrapeadas desde X/Twitter via xsignals_v2.py
-- Ejecutar: psql $DB_URL < db/migrations/002_xsignals_table.sql
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS xsignals_signals (
    id              TEXT PRIMARY KEY,                  -- sha256 hash del post (xsignals_v2 lo genera)
    profile         TEXT NOT NULL,                     -- usuario de X sin @ ej: 'aguti00'
    ticker          TEXT NOT NULL DEFAULT 'UNKNOWN',   -- ticker principal ej: 'NVDA'
    assets          TEXT[],                            -- todos los tickers/forex mencionados
    side            TEXT NOT NULL DEFAULT 'neutral',   -- 'long' | 'short' | 'neutral'
    market          TEXT NOT NULL DEFAULT 'stocks',    -- 'stocks' | 'crypto' | 'forex'
    confidence      INTEGER NOT NULL DEFAULT 35,       -- score 0-100
    signal_text     TEXT,                              -- texto del post (max 2000 chars)
    url             TEXT,                              -- URL del tweet
    published_hint  TEXT,                              -- timestamp aproximado del post en X
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW() -- cuando se guardó localmente
);

-- Índices para consultas frecuentes del stocks_agent
CREATE INDEX IF NOT EXISTS idx_xsignals_profile    ON xsignals_signals (profile);
CREATE INDEX IF NOT EXISTS idx_xsignals_ticker     ON xsignals_signals (ticker);
CREATE INDEX IF NOT EXISTS idx_xsignals_created_at ON xsignals_signals (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_xsignals_side       ON xsignals_signals (side);
