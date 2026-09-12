-- =============================================================================
-- Project EA Bot — PostgreSQL Baseline Migration
-- =============================================================================
-- File: infrastructure/migrations/001_baseline.sql
--
-- Esta migrasi menciptakan skema database lengkap untuk EA Bot.
-- Ditujukan untuk environments tanpa Alembic / Prisma migrate.
-- Untuk production, gunakan Alembic (Python) atau Prisma Migrate (Node.js).
--
-- Cara menjalankan manual:
--   psql -U ea_bot -d ea_bot -h localhost -p 5432 -f 001_baseline.sql
-- atau:
--   cat 001_baseline.sql | psql -U ea_bot -d ea_bot
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. Enum types
-- ---------------------------------------------------------------------------
-- Catatan: di Prisma, enum dikelola otomatis. Di SQLAlchemy dengan
-- create_type=False, enum diwakili sebagai VARCHAR. Berikut definisi asli
-- untuk referensi / import manual ke PostgreSQL.

CREATE TYPE role_enum AS ENUM ('USER', 'ADMIN', 'OPERATOR');
CREATE TYPE side_enum AS ENUM ('BUY', 'SELL');
CREATE TYPE order_type_enum AS ENUM (
    'MARKET', 'LIMIT', 'STOP_MARKET', 'STOP_LIMIT',
    'TAKE_PROFIT', 'TAKE_PROFIT_MARKET', 'TRAILING_STOP'
);
CREATE TYPE order_status_enum AS ENUM (
    'NEW', 'PARTIALLY_FILLED', 'FILLED', 'CANCELED', 'REJECTED', 'EXPIRED'
);
CREATE TYPE position_status_enum AS ENUM ('OPEN', 'CLOSED', 'PARTIAL', 'LIQUIDATED');
CREATE TYPE strategy_type_enum AS ENUM (
    'TREND_FOLLOWING', 'MEAN_REVERSION', 'SCALPING', 'GRID',
    'ARBITRAGE', 'MARKET_MAKING', 'CUSTOM'
);
CREATE TYPE agent_run_status_enum AS ENUM (
    'RUNNING', 'COMPLETED', 'FAILED', 'STOPPED', 'PAUSED'
);
CREATE TYPE audit_severity_enum AS ENUM ('INFO', 'WARN', 'ERROR', 'CRITICAL');

-- ---------------------------------------------------------------------------
-- 2. Table: user
-- ---------------------------------------------------------------------------
CREATE TABLE "user" (
    id              VARCHAR(255) PRIMARY KEY,
    email           VARCHAR(255) NOT NULL UNIQUE,
    password_hash   VARCHAR(512) NOT NULL,
    full_name       VARCHAR(255),
    role            role_enum NOT NULL DEFAULT 'USER',
    is_verified     BOOLEAN NOT NULL DEFAULT FALSE,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at   TIMESTAMP,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_user_email ON "user"(email);
CREATE INDEX ix_user_created_at ON "user"(created_at);

-- ---------------------------------------------------------------------------
-- 3. Table: account
-- ---------------------------------------------------------------------------
CREATE TABLE account (
    id            VARCHAR(255) PRIMARY KEY,
    user_id       VARCHAR(255) NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    provider      VARCHAR(64) NOT NULL,
    account_name  VARCHAR(255) NOT NULL,
    api_key       VARCHAR(512) NOT NULL,
    api_secret    VARCHAR(512) NOT NULL,
    is_sandbox    BOOLEAN NOT NULL DEFAULT TRUE,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    balance       NUMERIC(20, 8),
    currency      VARCHAR(16) NOT NULL DEFAULT 'USDT',
    created_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_account_user_id ON account(user_id);
CREATE INDEX ix_account_user_provider ON account(user_id, provider);

-- ---------------------------------------------------------------------------
-- 4. Table: symbol
-- ---------------------------------------------------------------------------
CREATE TABLE symbol (
    id              VARCHAR(255) PRIMARY KEY,
    exchange        VARCHAR(64) NOT NULL,
    symbol          VARCHAR(64) NOT NULL,
    base_asset      VARCHAR(16) NOT NULL,
    quote_asset     VARCHAR(16) NOT NULL,
    price_precision INTEGER NOT NULL DEFAULT 8,
    qty_precision   INTEGER NOT NULL DEFAULT 8,
    min_notional    NUMERIC(20, 8),
    status          VARCHAR(32) NOT NULL DEFAULT 'TRADING',
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (exchange, symbol)
);

CREATE INDEX ix_symbol_exchange ON symbol(exchange);

-- ---------------------------------------------------------------------------
-- 5. Table: strategy
-- ---------------------------------------------------------------------------
CREATE TABLE strategy (
    id              VARCHAR(255) PRIMARY KEY,
    user_id         VARCHAR(255) NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    type            strategy_type_enum NOT NULL,
    config          TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    is_paper_trading BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, name)
);

CREATE INDEX ix_strategy_user_id ON strategy(user_id);
CREATE INDEX ix_strategy_user_name ON strategy(user_id, name);

-- ---------------------------------------------------------------------------
-- 6. Table: position
-- ---------------------------------------------------------------------------
CREATE TABLE position (
    id               VARCHAR(255) PRIMARY KEY,
    account_id       VARCHAR(255) NOT NULL REFERENCES account(id) ON DELETE CASCADE,
    symbol           VARCHAR(64) NOT NULL,
    side             side_enum NOT NULL,
    entry_price      NUMERIC(20, 8) NOT NULL,
    current_price    NUMERIC(20, 8) NOT NULL,
    quantity         NUMERIC(20, 8) NOT NULL,
    leverage         INTEGER NOT NULL DEFAULT 1,
    unrealized_pnl   NUMERIC(20, 8),
    realized_pnl     NUMERIC(20, 8),
    margin           NUMERIC(20, 8),
    status           position_status_enum NOT NULL DEFAULT 'OPEN',
    strategy_id      VARCHAR(255) REFERENCES strategy(id) ON DELETE SET NULL,
    agent_run_id     VARCHAR(255) REFERENCES agent_run(id) ON DELETE SET NULL,
    opened_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    closed_at        TIMESTAMP,
    updated_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (account_id, symbol, side)
);

CREATE INDEX ix_position_account_id ON position(account_id);
CREATE INDEX ix_position_status ON position(status);
CREATE INDEX ix_position_symbol ON position(symbol);

-- ---------------------------------------------------------------------------
-- 7. Table: agent_run
-- ---------------------------------------------------------------------------
CREATE TABLE agent_run (
    id              VARCHAR(255) PRIMARY KEY,
    strategy_id     VARCHAR(255) REFERENCES strategy(id) ON DELETE SET NULL,
    user_id         VARCHAR(255) NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    started_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMP,
    status          agent_run_status_enum NOT NULL DEFAULT 'RUNNING',
    input_params    TEXT,
    output_summary  TEXT,
    error_msg       TEXT
);

CREATE INDEX ix_agent_run_status ON agent_run(status);
CREATE INDEX ix_agent_run_started_at ON agent_run(started_at);
CREATE INDEX ix_agent_run_user_id ON agent_run(user_id);

-- ---------------------------------------------------------------------------
-- 8. Table: trade
-- ---------------------------------------------------------------------------
CREATE TABLE trade (
    id            VARCHAR(255) PRIMARY KEY,
    account_id    VARCHAR(255) NOT NULL REFERENCES account(id) ON DELETE CASCADE,
    symbol        VARCHAR(64) NOT NULL,
    side          side_enum NOT NULL,
    order_type    order_type_enum NOT NULL,
    price         NUMERIC(20, 8) NOT NULL,
    quantity      NUMERIC(20, 8) NOT NULL,
    fee           NUMERIC(20, 8),
    fee_asset     VARCHAR(16),
    trade_time    TIMESTAMP NOT NULL DEFAULT NOW(),
    position_id   VARCHAR(255) REFERENCES position(id) ON DELETE SET NULL,
    strategy_id   VARCHAR(255) REFERENCES strategy(id) ON DELETE SET NULL,
    agent_run_id  VARCHAR(255) REFERENCES agent_run(id) ON DELETE SET NULL,
    notes         TEXT,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_trade_account_id ON trade(account_id);
CREATE INDEX ix_trade_symbol ON trade(symbol);
CREATE INDEX ix_trade_trade_time ON trade(trade_time);
CREATE INDEX ix_trade_account_time ON trade(account_id, trade_time);
CREATE INDEX ix_trade_position_id ON trade(position_id);
CREATE INDEX ix_trade_strategy_id ON trade(strategy_id);
CREATE INDEX ix_trade_agent_run_id ON trade(agent_run_id);

-- ---------------------------------------------------------------------------
-- 9. Table: order
-- ---------------------------------------------------------------------------
CREATE TABLE "order" (
    id            VARCHAR(255) PRIMARY KEY,
    account_id    VARCHAR(255) NOT NULL REFERENCES account(id) ON DELETE CASCADE,
    symbol        VARCHAR(64) NOT NULL,
    side          side_enum NOT NULL,
    order_type    order_type_enum NOT NULL,
    price         NUMERIC(20, 8),
    stop_price    NUMERIC(20, 8),
    quantity      NUMERIC(20, 8) NOT NULL,
    filled_qty    NUMERIC(20, 8) NOT NULL DEFAULT 0,
    status        order_status_enum NOT NULL DEFAULT 'NEW',
    strategy_id   VARCHAR(255) REFERENCES strategy(id) ON DELETE SET NULL,
    agent_run_id  VARCHAR(255) REFERENCES agent_run(id) ON DELETE SET NULL,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_order_account_id ON "order"(account_id);
CREATE INDEX ix_order_symbol ON "order"(symbol);
CREATE INDEX ix_order_status ON "order"(status);
CREATE INDEX ix_order_account_symbol ON "order"(account_id, symbol);

-- ---------------------------------------------------------------------------
-- 10. Table: agent_output
-- ---------------------------------------------------------------------------
CREATE TABLE agent_output (
    id              VARCHAR(255) PRIMARY KEY,
    agent_run_id    VARCHAR(255) NOT NULL REFERENCES agent_run(id) ON DELETE CASCADE,
    step            INTEGER NOT NULL,
    timestamp       TIMESTAMP NOT NULL DEFAULT NOW(),
    action          VARCHAR(64) NOT NULL,
    rationale       TEXT,
    confidence      NUMERIC(5, 4),
    suggested_trade TEXT,
    metrics         TEXT
);

CREATE INDEX ix_agent_output_agent_run_id ON agent_output(agent_run_id);
CREATE INDEX ix_agent_output_timestamp ON agent_output(timestamp);
CREATE INDEX ix_agent_output_run_timestamp ON agent_output(agent_run_id, timestamp);

-- ---------------------------------------------------------------------------
-- 11. Table: audit_log
-- ---------------------------------------------------------------------------
CREATE TABLE audit_log (
    id            VARCHAR(255) PRIMARY KEY,
    user_id       VARCHAR(255) REFERENCES "user"(id) ON DELETE SET NULL,
    action        VARCHAR(128) NOT NULL,
    resource_type VARCHAR(64) NOT NULL,
    resource_id   VARCHAR(255),
    details       TEXT,
    ip_address    VARCHAR(45),
    user_agent    TEXT,
    severity      audit_severity_enum NOT NULL DEFAULT 'INFO',
    created_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_audit_log_user_id ON audit_log(user_id);
CREATE INDEX ix_audit_log_action ON audit_log(action);
CREATE INDEX ix_audit_log_created_at ON audit_log(created_at);
CREATE INDEX ix_audit_user_created ON audit_log(user_id, created_at);

-- ---------------------------------------------------------------------------
-- 12. Function: updated_at trigger (optional)
-- ---------------------------------------------------------------------------
-- Otomatisasi updated_at untuk tabel yang memilik kolom updated_at.
-- Bisa dilepas jika menggunakan ORM yang mengelola updated_at sendiri.

CREATE OR REPLACE FUNCTION trigger_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Contoh penerapan (jalankan terpisah jika diperlukan):
-- CREATE TRIGGER set_updated_at_user
--     BEFORE UPDATE ON "user"
--     FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();
--
-- CREATE TRIGGER set_updated_at_account
--     BEFORE UPDATE ON account
--     FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();
--
-- (dan seterusnya untuk tabel lain yang memiliki updated_at)

-- ---------------------------------------------------------------------------
-- 13. Initial data (opsional)
-- ---------------------------------------------------------------------------
-- INSERT INTO "user" (id, email, password_hash, role, is_verified, is_active)
-- VALUES ('cli_default', 'admin@localhost', '$2b$12$...', 'ADMIN', true, true);

-- =============================================================================
-- Selesai. Database siap digunakan dengan Prisma atau SQLAlchemy.
-- =============================================================================
