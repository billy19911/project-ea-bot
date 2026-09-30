# Phase 7 — Control Plane Architecture

## Read-model layer (`src/ops/`)

Observability only, zero trading authority:

| File | Responsibility |
|------|----------------|
| `readmodels.py` | overview, health, market, risk, execution, positions, models, budget, providers, research, strategy |
| `trace.py` | decision/trade trace, non-trade explanation, deterministic search |
| `alerts.py` | runtime alert evaluation (INFO/WARNING/HIGH/CRITICAL) |
| `secrets.py` | secret masking, UNKNOWN semantics, mutation audit log |
| `router.py` | FastAPI `/ops/*` — GET-only except audited alert-acknowledge |

## Endpoints (`/ops/*`, 21 routes)

overview, health, market, setups, decisions/{id}, setups/{id}/trace,
trades/{id}, explain, risk, executions, positions, models, budget, providers,
alerts (+acknowledge POST), audit, research, strategies, search, activity.

## Mount

`main.py` mounts `ops_router` at module level alongside the other routers
(inside the same block as mt5/trading/market/research).

## Authority rules

- The control plane NEVER computes risk, volume, triggers, or executions.
- Backend canonical state is the source of truth; read models only assemble.
- The only mutation is `alerts/{id}/acknowledge` (audited; changes no trading state).
- No endpoint submits MT5 orders, forces triggers, or activates strategies
  (verified: 404/405 on adversarial probes).
