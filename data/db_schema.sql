-- SMC/ICT Chart Analyzer — Database Schema (SQLite)
-- Stage 1: Data pipeline — OHLCV storage

-- ============================================================
-- 1. Instruments metadata
-- ============================================================
CREATE TABLE IF NOT EXISTS instruments (
    symbol         TEXT    NOT NULL,
    exchange       TEXT    NOT NULL DEFAULT 'bybit',
    base_asset     TEXT    NOT NULL,
    quote_asset    TEXT    NOT NULL,
    category       TEXT    NOT NULL DEFAULT 'crypto'
                        CHECK (category IN ('crypto', 'forex', 'commodity')),
    PRIMARY KEY (symbol, exchange)
);

-- ============================================================
-- 2. OHLCV candles
--
-- Primary key: (symbol, timeframe, open_at)
-- open_at — UNIX timestamp (ms) when the candle opened.
-- Using integer ms for efficient range queries and JOINs.
-- ============================================================
CREATE TABLE IF NOT EXISTS ohlcv (
    symbol         TEXT       NOT NULL,
    timeframe      TEXT       NOT NULL,
    open_at        INTEGER    NOT NULL,   -- ms since epoch
    "open"         REAL       NOT NULL,
    "high"         REAL       NOT NULL,
    "low"          REAL       NOT NULL,
    "close"        REAL       NOT NULL,
    volume         REAL       NOT NULL DEFAULT 0,

    PRIMARY KEY (symbol, timeframe, open_at),
    FOREIGN KEY (symbol) REFERENCES instruments(symbol)
        ON DELETE CASCADE
);

-- ============================================================
-- 3. Indexes
-- ============================================================

-- Fast lookup: symbol + timeframe, ordered by time
CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_tf_time
    ON ohlcv (symbol, timeframe, open_at);

-- Fast lookup: symbol only (for history summary)
CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol
    ON ohlcv (symbol);

-- ============================================================
-- 4. SMC / ICT patterns (Stage 3)
--
-- Stores algorithmically detected zones per symbol + timeframe.
-- ============================================================
CREATE TABLE IF NOT EXISTS smc_patterns (
    id             INTEGER    PRIMARY KEY AUTOINCREMENT,
    symbol         TEXT       NOT NULL,
    timeframe      TEXT       NOT NULL,
    pattern_type   TEXT       NOT NULL
                        CHECK (pattern_type IN (
                            'swing_high',
                            'swing_low',
                            'bos',
                            'choch',
                            'order_block_bullish',
                            'order_block_bearish',
                            'fvg_bullish',
                            'fvg_bearish',
                            'liquidity_sweep_high',
                            'liquidity_sweep_low',
                            'breakaway_index',
                            'continuation_index'
                        )),
    candle_open_at INTEGER    NOT NULL,   -- ms; which candle triggered this
    price_high     REAL       NOT NULL,   -- top of the zone / level
    price_low      REAL       NOT NULL,   -- bottom of the zone / level
    mid_price      REAL       NOT NULL,   -- (price_high + price_low) / 2
    is_valid       INTEGER    NOT NULL DEFAULT 1  -- 1 = valid, 0 = mitigated/broken
);

CREATE INDEX IF NOT EXISTS idx_smc_symbol_tf_type
    ON smc_patterns (symbol, timeframe, pattern_type);

CREATE INDEX IF NOT EXISTS idx_smc_symbol_valid
    ON smc_patterns (symbol, is_valid);

-- ============================================================
-- 5. Session analysis results (Stage 5)
-- ============================================================
CREATE TABLE IF NOT EXISTS session_results (
    id             INTEGER    PRIMARY KEY AUTOINCREMENT,
    symbol         TEXT       NOT NULL,
    date_utc       TEXT       NOT NULL,   -- YYYY-MM-DD
    session_name   TEXT       NOT NULL
                        CHECK (session_name IN (
                            'asian',
                            'london',
                            'ny',
                            'ny_extend'
                        )),
    session_type   TEXT       NOT NULL
                        CHECK (session_type IN ('range', 'sweep', 'expansion', 'mix')),
    high           REAL       NOT NULL,
    low            REAL       NOT NULL,
    body_high      REAL       NOT NULL,   -- high of candle body (excl. wick)
    body_low       REAL       NOT NULL,   -- low of candle body
    bullish        INTEGER    NOT NULL DEFAULT 0,
    bearish        INTEGER    NOT NULL DEFAULT 0,
    notes          TEXT               ,   -- free-text observer notes
    UNIQUE (symbol, date_utc, session_name)
);

CREATE INDEX IF NOT EXISTS idx_session_symbol_date
    ON session_results (symbol, date_utc);

-- ============================================================
-- 6. Analysis runs (orchestrator output, Stage 6-7)
-- ============================================================
CREATE TABLE IF NOT EXISTS analysis_runs (
    id              INTEGER    PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT       NOT NULL,
    timeframes_json TEXT       NOT NULL,   -- e.g. '["1D","4H","1H"]'
    run_at          TEXT       NOT NULL,   -- ISO 8601 UTC timestamp
    chart_path      TEXT               ,   -- local path or URL to chart PNG
    prompt_text     TEXT               ,   -- full prompt sent to VLM (for logging)
    response_json   TEXT               ,   -- raw VLM response (constrained JSON)
    bias            TEXT               ,   -- 'bullish' | 'bearish' | 'neutral'
    confidence      REAL               ,   -- 0.0 — 1.0
    narrative       TEXT               ,
    key_levels_json TEXT               ,   -- serialized key levels / POI
    user_feedback   TEXT               ,   -- 'upvote' | 'downvote' | NULL
    created_at      TEXT       NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_analysis_run_symbol_date
    ON analysis_runs (symbol, run_at);
