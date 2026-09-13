# OpenCode Context for EA Bot Project

## Project Overview
- **Name**: EA Bot — AI Autonomous Multi-Agent Trading & Research Platform
- **Version**: 0.1.0
- **Status**: Phase 0 & 1 Complete, Starting Phase 2
- **Primary Platform**: MetaTrader 5 (MT5)
- **Primary Instrument**: XAUUSD / XAUUSDC

## Current Progress
### Phase 0: Architecture Foundation ✅
- Monorepo structure with TypeScript/Node.js and Python services
- Database layer (Prisma + SQLAlchemy models)
- Logging and configuration system
- Development documentation and CI/CD blueprint

### Phase 1: MT5 Connector ✅
- MT5 connection manager with live/simulation modes
- Market data retrieval (symbol info, tick, OHLC)
- Paper trading API endpoints (read-only)
- Position and order management
- Comprehensive test suite (24 tests passing)

## Technical Stack
- **Frontend**: React + Next.js (dashboard)
- **Backend API**: Node.js / TypeScript / Express
- **AI Service**: Python / FastAPI
- **Database**: PostgreSQL (Prisma + SQLAlchemy)
- **Execution**: MetaTrader 5
- **Container**: Docker (optional)

## Current File Structure
```
project-ea-bot/
├── apps/
│   ├── web/          # Next.js dashboard (to be built)
│   └── api/          # Node.js API (Express)
├── services/
│   └── python/       # FastAPI service (agents, MT5 connector, risk)
├── packages/
│   ├── eslint-config/ # Shared lint config
│   └── shared/       # TypeScript types & utilities
├── infrastructure/
│   ├── docker/       # Docker compose & Dockerfiles
│   └── db/          # PostgreSQL init, backup, restore
├── .github/
│   └── workflows/   # CI/CD
├── docs/
│   ├── logging.md    # Panduan structured logging
│   └── development-setup.md
├── scripts/
├── config-validate.js
├── .env.example
├── README.md
├── CHANGELOG.md
├── CONSTRAINTS.md
└── PRD_V1_Autonomous_Multi_Agent_Trading_Research_Platform.md
```

## MT5 Connector Details (Phase 1)
- Location: `services/python/src/mt5/`
- Key files:
  - `connector.py` - MT5 data access functions (simulation/live)
  - `_connector_base.py` - MT5Connector class with health check
  - `connection_manager.py` - Connection lifecycle management
  - `models.py` - Data models (Timeframe, SymbolInfo, Tick, OHLC)
  - `schemas.py` - Pydantic schemas for API responses
  - `retrieval.py` - Market data retrieval helpers
  - `endpoints.py` - FastAPI router for paper trading endpoints
  - `__init__.py` - Package exports
- Test file: `services/python/tests/test_mt5_connection.py` (15 tests)

## Current Goals for Phase 2
Based on the PRD, Phase 2 should implement the **Deterministic Trading Engine** which includes:
- Technical indicators (EMA, SMA, RSI, MACD, ATR, ADX, etc.)
- Trend detection algorithms
- Volatility calculations
- Position sizing logic
- Risk metrics calculation
- All deterministic (no LLM usage)

## Constraints
1. **Deterministic Engine**: No LLM usage - pure algorithmic calculations
2. **MT5 Integration**: Must work with existing MT5 connector layer
3. **Performance**: Efficient calculations suitable for real-time processing
4. **Accuracy**: Financial calculations must be precise
5. **Modularity**: Easy to extend with new indicators
6. **Testability**: Comprehensive unit tests required

## Environment
- Python 3.11+
- Dependencies: pandas, numpy, ta-lib (optional), or manual implementations
- Existing MT5 connector layer is functional
- MetaTrader5 Python package installed

## Output Expectations
- Implement indicator calculations as deterministic functions
- Create modular structure for easy extension
- Provide clean API for other components to consume
- Include comprehensive test suite
- Follow existing code style and patterns in the project