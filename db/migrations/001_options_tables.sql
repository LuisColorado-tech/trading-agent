-- ══════════════════════════════════════════════════════════════════════════════
-- 001_options_tables.sql
-- Tablas para el sistema de Theta Farming / Options Selling (Deribit)
-- Ejecutar: psql trading_agent < db/migrations/001_options_tables.sql
-- ══════════════════════════════════════════════════════════════════════════════

-- ── Sesiones de opciones (equivalente a poly_sessions / paper_sessions) ──────
CREATE TABLE IF NOT EXISTS options_sessions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_name        TEXT NOT NULL UNIQUE,          -- 'OPTIONS_SESSION_001'
    mode                TEXT NOT NULL DEFAULT 'paper', -- 'paper' | 'live'
    initial_balance_usd NUMERIC(12, 2) NOT NULL,       -- USD reservado como colateral
    current_balance_usd NUMERIC(12, 2) NOT NULL,       -- balance dinámico (incluye PnL paper)
    peak_balance_usd    NUMERIC(12, 2) NOT NULL,
    total_contracts     INTEGER NOT NULL DEFAULT 0,    -- contratos totales operados
    winning_contracts   INTEGER NOT NULL DEFAULT 0,
    total_pnl_usd       NUMERIC(12, 2) NOT NULL DEFAULT 0,
    total_premium_usd   NUMERIC(12, 2) NOT NULL DEFAULT 0,  -- primas cobradas acumuladas
    realized_losses_usd NUMERIC(12, 2) NOT NULL DEFAULT 0,
    max_drawdown_pct    NUMERIC(6, 3) NOT NULL DEFAULT 0,
    profit_factor       NUMERIC(8, 4),
    status              TEXT NOT NULL DEFAULT 'ACTIVE', -- 'ACTIVE' | 'CLOSED' | 'FAILED'
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at            TIMESTAMPTZ,
    notes               TEXT
);

-- ── Posiciones de opciones vendidas ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS options_positions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id          UUID NOT NULL REFERENCES options_sessions(id),
    session_name        TEXT NOT NULL,

    -- Instrumento
    instrument_name     TEXT NOT NULL,           -- 'BTC-18APR26-69000-P'
    underlying          TEXT NOT NULL DEFAULT 'BTC',
    option_type         TEXT NOT NULL DEFAULT 'PUT',  -- 'PUT' | 'CALL'
    strike              NUMERIC(12, 2) NOT NULL,
    expiration_date     DATE NOT NULL,
    dte_at_entry        INTEGER NOT NULL,         -- días hasta expiración al entrar

    -- Tamaño y precio
    contracts           NUMERIC(8, 4) NOT NULL,   -- tamaño en BTC (min 0.1)
    entry_premium_btc   NUMERIC(10, 6) NOT NULL,  -- prima cobrada al vender (en BTC)
    entry_premium_usd   NUMERIC(10, 2) NOT NULL,  -- prima en USD al momento de entrada
    btc_price_at_entry  NUMERIC(12, 2) NOT NULL,
    iv_at_entry         NUMERIC(6, 2),            -- IV% al entrar
    iv_rank_at_entry    NUMERIC(6, 2),            -- IV Rank% al entrar
    delta_at_entry      NUMERIC(8, 4),
    theta_at_entry      NUMERIC(10, 4),
    margin_required_usd NUMERIC(10, 2),           -- margen estimado en USD

    -- Estado
    status              TEXT NOT NULL DEFAULT 'OPEN',  -- 'OPEN' | 'EXPIRED_PROFIT' | 'CLOSED_STOP' | 'ASSIGNED' | 'CLOSED_MANUAL'
    exit_premium_btc    NUMERIC(10, 6),           -- prima pagada al cerrar (si se cierra antes)
    exit_premium_usd    NUMERIC(10, 2),
    btc_price_at_exit   NUMERIC(12, 2),
    pnl_usd             NUMERIC(10, 2),           -- PnL neto (prima cobrada - prima pagada)
    pnl_pct             NUMERIC(8, 4),            -- PnL% sobre margen requerido
    exit_reason         TEXT,                      -- 'EXPIRED' | 'STOP_LOSS_2X' | 'MANUAL' | 'ASSIGNED'

    -- Razonamiento
    strategy_reasoning  TEXT,
    iv_rank_signal      TEXT,                      -- 'HIGH' | 'MEDIUM' | 'LOW'
    market_conditions   TEXT,                      -- JSON con regime, btc_direction, etc.

    -- Timestamps
    opened_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at          TIMESTAMPTZ NOT NULL,
    closed_at           TIMESTAMPTZ
);

-- ── Snapshots de IV y markt data para backtesting ────────────────────────────
CREATE TABLE IF NOT EXISTS options_market_data (
    id              BIGSERIAL PRIMARY KEY,
    instrument_name TEXT NOT NULL,
    underlying      TEXT NOT NULL DEFAULT 'BTC',
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Spot price
    btc_price       NUMERIC(12, 2) NOT NULL,

    -- Option data
    strike          NUMERIC(12, 2),
    expiration_date DATE,
    dte             INTEGER,
    option_type     TEXT,           -- 'PUT' | 'CALL'

    -- Market
    bid_btc         NUMERIC(10, 6),
    ask_btc         NUMERIC(10, 6),
    mark_btc        NUMERIC(10, 6),
    iv_pct          NUMERIC(6, 2),  -- IV implícita del instrumento
    delta           NUMERIC(8, 4),
    gamma           NUMERIC(10, 8),
    theta           NUMERIC(10, 4),
    vega            NUMERIC(10, 4),

    -- Índice de volatilidad
    dvol_current    NUMERIC(6, 2),  -- DVOL (indice IV de Deribit)
    dvol_rank_30d   NUMERIC(6, 2)   -- IV Rank calculado sobre 30 días
);

-- Índices para queries frecuentes
CREATE INDEX IF NOT EXISTS idx_opt_positions_session ON options_positions(session_name, status);
CREATE INDEX IF NOT EXISTS idx_opt_positions_expires ON options_positions(expires_at) WHERE status = 'OPEN';
CREATE INDEX IF NOT EXISTS idx_opt_market_data_ts ON options_market_data(timestamp, underlying);
CREATE INDEX IF NOT EXISTS idx_opt_market_data_inst ON options_market_data(instrument_name, timestamp);
