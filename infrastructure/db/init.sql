-- Create database
CREATE DATABASE eabot;
\c eabot

-- Users table
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Trading pairs table
CREATE TABLE trading_pairs (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) UNIQUE NOT NULL,
    base_asset VARCHAR(20) NOT NULL,
    quote_asset VARCHAR(20) NOT NULL,
    min_trade_size DECIMAL(20,8) DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Trade signals table
CREATE TABLE trade_signals (
    id SERIAL PRIMARY KEY,
    pair VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL CHECK (side IN ('buy', 'sell')),
    price DECIMAL(20,8) NOT NULL,
    reason TEXT,
    confidence DECIMAL(5,4) DEFAULT 0,
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'executed', 'cancelled')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    executed_at TIMESTAMP,
    user_id INTEGER REFERENCES users(id)
);

-- Bot configurations table
CREATE TABLE bot_configurations (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    config JSONB NOT NULL,
    is_active BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX idx_trade_signals_pair ON trade_signals(pair);
CREATE INDEX idx_trade_signals_created_at ON trade_signals(created_at);
CREATE INDEX idx_trade_signals_status ON trade_signals(status);

-- Insert sample data
INSERT INTO trading_pairs (symbol, base_asset, quote_asset, min_trade_size) VALUES
    ('BTC/USDT', 'BTC', 'USDT', 0.001),
    ('ETH/USDT', 'ETH', 'USDT', 0.01),
    ('SOL/USDT', 'SOL', 'USDT', 0.1);
