# AI Autonomous Multi-Agent Trading & Research Platform

**Status:** Draft — Architecture & Implementation Specification  
**Version:** 1.0  
**Target:** Autonomous AI Trading & Research System  
**Primary Platform:** MetaTrader 5 (MT5)  
**Initial Model Strategy:** Free / low-cost models first, model escalation when required

---

## Overview

A multi-agent autonomous trading system designed with event-driven architecture where AI decides within boundaries, code enforces safety rules. The system combines deterministic trading engines with AI specialist agents to analyze market conditions, manage risk, and execute trades through MetaTrader 5.

### Core Principle

```text
AI decides within boundaries.
Code enforces boundaries.
```

This means trading follows a strict pipeline where AI provides trade proposals that must pass through deterministic validations and risk gates before execution.

---

## Architecture

### High-Level System Architecture

```
┌───────────────────────┐
│       WEB UI          │
│ React / Next.js       │
└───────────┬───────────┘
        │
         API / WebSocket
        │
┌───────────▼───────────┐
│     CONTROL PLANE      │
│ Node.js / TypeScript   │
└───────────┬───────────┘
        │
┌───────────▼───────────┐
│  SUPERVISOR AGENT     │
└──────┬───────────────┘
       │
  ┌────┴────┐
  │         │
  ▼         ▼
┌───┐     ┌───┐
│Technical│
│Analyst  │     Market Intelligence
└───┘     └───┘
  │
  ▼
┌─────────────────────────┐
│   DETERMINISTIC RISK    │
│      ENGINE             │
└──────┬──────────────────┘
       │
       ▼
┌───────────────────────┐
│    EXECUTION ENGINE    │
└──────┬──────────────────┘
       │
   MT5 API
```

---

## Key Features

### AI-Driven Trading

- **Multi-Agent System:** Supervisor orchestrates domain specialists (Technical, Market Structure, Momentum, Volatility, Risk, Research agents)
- **Event-Driven Architecture:** AI triggers only when meaningful market events occur
- **Model Routing:** Free models for initial phases, escalates to stronger models when confidence is low or conflicts detected
- **Token Budget Management:** Limits token usage per request by agent and event type

### Risk Management

- **Deterministic Risk Engine:** Hard-coded rules that cannot be bypassed by AI
- **Multiple Risk Gates:** Account, position, portfolio, and drawdown checks
- **Automated Kill Switch:** Emergency conditions trigger automatic system lockout
- **Permission System:** Admin, Operator, and Viewer roles with role-based access control

### Research & Backtesting

- **Backtest Engine:** Support for historical data, spread, slippage, commissions
- **Paper Trading Engine:** AI testing without real money
- **Walk Forward Analysis:** Progressive validation before live trading
- **Experiment Pipeline:** Hypothesis → Backtest → Validation → Approval → Production

### Observability & Control

- **Real-time Dashboard:** Live view of account state, market conditions, AI activity, and trade history
- **Audit Logs:** Complete traceability of all decisions and actions
- **Notification System:** Telegram, web notifications, and email alerts for critical events
- **Kill Switch Control:** Global emergency stop with existing position management options

---

## Tech Stack

- **Frontend:** React + Next.js
- **Backend:** Node.js / TypeScript
- **Database:** PostgreSQL (multi-tenant architecture)
- **AI Gateway:** 9Router abstraction layer with fallback support
- **Execution Platform:** MetaTrader 5
- **Agent Runtime:** Python and/or dedicated AI service
- **Containerization:** Docker for development and deployment

---

## Development Phases

### Phase 0 — Architecture Foundation
- Repository setup, environment management, TypeScript configuration
- Python service setup, database schema, logging configuration
- Docker/dev environments and health checks

### Phase 1 — MT5 Connector
- MT5 connection with bidirectional communication
- Account info, symbol info, tick data, OHLC data
- Position management and order execution

### Phase 2 — Deterministic Trading Engine
- Technical analysis indicators (EMA, SMA, RSI, MACD, ATR, ADX)
- Market structure identification
- Volatility and liquidity analysis

### Phase 3 — Multi-Agent System
- Supervisor Agent orchestration
- Market Department agents (Technical, Structure, Momentum, Volatility, News)
- Risk Department agents (Account, Position, Portfolio, Drawdown)
- Research Department agents (Strategy, Backtest, Performance, Experiment)

### Phase 4 — Risk & Execution
- Risk Gate implementation with hard limits
- Money Management engine for position sizing
- Execution Engine with MT5 connection
- Position Monitor with SL/TP management

### Phase 5 — UI & Dashboard
- React/Next.js dashboard components
- Real-time WebSocket updates
- Control panels and settings management
- Agent activity visualization

### Phase 6 — Research & Validation
- Backtest engine with realistic parameters
- Paper trading simulation
- Walk-forward analysis
- Production deployment

---

## Safety Mechanisms

- **OFFLINE mode:** No AI interaction
- **BACKTEST mode:** Historical simulation only
- **PAPER mode:** Demo account trading
- **DEMO mode:** Real broker demo account
- **LIVE mode:** Live trading with explicit enable
- **EMERGENCY_STOP mode:** Global system lockdown

### Automatic Kill Switch Triggers

- Drawdown exceeded
- MT5 connection unstable
- Unexpected order behavior
- Duplicate order detection
- Risk engine failure
- State corruption
- Price feed invalid
- Spread abnormal
- API failure
- LLM service failure

---

## License

**MIT License** — See [LICENCE](LICENSE) file for details

---

*Last Updated: September 2026*