# Phase 7 — UI Operations Guide

The frontend (`apps/web`, Next.js + Tailwind, control-plane pages) consumes
`/ops/*` as its operations data source. Principles (§22):

- Dense, grouped status cards + drill-down detail pages (no hero sections).
- Setup page: lifecycle (zone/trigger/mitigation/retest/TFs/expiry) + trace link.
- Trade page: execution → position → reconciliation → review → research lineage.
- Non-trade page (`/why-no-trade`, `GET /ops/explain`): state, blocking,
  missing, reason codes, evidence, risk result — WAIT is a first-class event.
- Model page: per-call provenance + aggregates; UNKNOWN cost renders UNKNOWN.
- Budget page: reserved/committed/refunded/remaining (informational).
- Alerts: severity-grouped; acknowledge is the only mutation (audited).
- Command palette: navigation by setup/trade/execution/position/alert/version
  IDs only — no chat UI, no decision authority.
- Safe controls only: alert-acknowledge, research retry/pause, provider-health
  refresh, reconciliation check. NEVER: execute order, change lot, bypass
  RiskGate, force trigger, activate strategy, enable live trading.
- Kill-switch/pause is NOT exposed (no safe backend mechanism exists) —
  documented as future work (§25).
- Untrusted content (model text, provider errors) renders as escaped text.
