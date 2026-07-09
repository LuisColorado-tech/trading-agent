-- Migration 004: GitHub repo strategies hunting
-- repo_strategies: repositorios encontrados y sus estrategias extraídas
-- repo_backtest_results: resultados de backtest por estrategia

CREATE TABLE IF NOT EXISTS repo_strategies (
    id                    SERIAL PRIMARY KEY,
    repo_name             VARCHAR(200) NOT NULL,
    repo_url              VARCHAR(500) NOT NULL,
    stars                 INTEGER DEFAULT 0,
    strategy_name         VARCHAR(150) NOT NULL,
    strategy_type         VARCHAR(50),   -- momentum | mean_reversion | breakout | arb | ml | composite | signal_based
    asset_class           VARCHAR(50),   -- crypto | polymarket | stocks | forex | options
    timeframe             VARCHAR(20),   -- 1m | 5m | 15m | 1h | 1d | event-based
    description           TEXT,
    entry_logic           TEXT,
    exit_logic            TEXT,
    indicators_used       TEXT,          -- comma-separated: RSI,MACD,VWAP,...
    position_sizing       TEXT,          -- kelly | fixed | risk_pct
    risk_params           JSONB,         -- {stop_loss, take_profit, max_pos, min_edge}
    implementation_notes  TEXT,
    source_files          TEXT,          -- archivos clave en el repo
    implementation_status VARCHAR(30) DEFAULT 'discovered',
    -- discovered | analyzed | adapted | backtested | deployed | rejected
    backtest_result       JSONB,
    -- {win_rate, profit_factor, max_dd, sharpe, total_trades, return_pct}
    priority              INTEGER DEFAULT 5,  -- 1=highest, 10=lowest
    notes                 TEXT,
    discovered_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_at            TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_repo_strategies_status ON repo_strategies(implementation_status);
CREATE INDEX IF NOT EXISTS idx_repo_strategies_type ON repo_strategies(strategy_type);
CREATE INDEX IF NOT EXISTS idx_repo_strategies_priority ON repo_strategies(priority);

-- Vista de estrategias priorizadas para backtesting
CREATE OR REPLACE VIEW v_strategies_to_backtest AS
SELECT
    id,
    repo_name,
    strategy_name,
    strategy_type,
    asset_class,
    timeframe,
    description,
    indicators_used,
    priority,
    stars,
    implementation_status
FROM repo_strategies
WHERE implementation_status IN ('discovered', 'analyzed', 'adapted')
ORDER BY priority ASC, stars DESC;
