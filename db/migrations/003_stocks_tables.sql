-- Migration 003: Stocks trading tables
-- stocks_sessions: sesiones paper/live del stocks agent
-- stocks_trades: trades individuales de acciones

CREATE TABLE IF NOT EXISTS stocks_sessions (
    id              TEXT PRIMARY KEY,
    session_name    TEXT NOT NULL UNIQUE,
    initial_balance NUMERIC(12, 4) NOT NULL,
    current_balance NUMERIC(12, 4),
    final_balance   NUMERIC(12, 4),
    total_trades    INTEGER NOT NULL DEFAULT 0,
    winning_trades  INTEGER NOT NULL DEFAULT 0,
    profit_factor   NUMERIC(8, 4),
    max_drawdown    NUMERIC(8, 4),
    status          TEXT NOT NULL DEFAULT 'ACTIVE',  -- ACTIVE | CLOSED | PAUSED
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at        TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS stocks_trades (
    id                  TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL REFERENCES stocks_sessions(id),
    symbol              TEXT NOT NULL,
    direction           TEXT NOT NULL,   -- BUY | SELL
    entry_price         NUMERIC(14, 6) NOT NULL,
    qty                 NUMERIC(12, 6) NOT NULL,
    notional            NUMERIC(12, 4),  -- USD invertido
    stop_loss           NUMERIC(14, 6),
    take_profit         NUMERIC(14, 6),
    exit_price          NUMERIC(14, 6),
    pnl                 NUMERIC(12, 4),
    strategy            TEXT,
    alpaca_order_id     TEXT,            -- order_id de Alpaca para tracking
    xsignal_boost       NUMERIC(5, 2) DEFAULT 0,  -- boost score de xsignals
    exit_reason         TEXT,            -- SL | TP | MANUAL | TRAILING | TIMEOUT
    status              TEXT NOT NULL DEFAULT 'OPEN',  -- OPEN | CLOSED | CANCELLED
    opened_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at           TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_stocks_trades_session ON stocks_trades(session_id);
CREATE INDEX IF NOT EXISTS idx_stocks_trades_symbol  ON stocks_trades(symbol);
CREATE INDEX IF NOT EXISTS idx_stocks_trades_status  ON stocks_trades(status);
CREATE INDEX IF NOT EXISTS idx_stocks_trades_opened  ON stocks_trades(opened_at DESC);
