/**
 * Run 21: honest-overview mapping regression tests.
 *
 * Guards against fabricated data in the control-plane overview endpoints. Before
 * this change the Node API returned invented zeros and empty arrays while
 * labelling the payload `source: 'live'`:
 *
 *   1. `/trading/overview` hard-coded `trades/wins/losses/gross_*: 0` and
 *      `recent_trades: []`, and put *unrealized* PnL into `today.net_pnl`.
 *   2. `/market/overview` echoed raw Python symbols (`bid`/`ask`) that the UI
 *      read as `price`/`change_pct`/`volatility`, rendering `undefined`.
 *   3. `/ai/providers` invented `calls_today: 0` and a zero budget.
 *   4. `/system/overview` invented `mode: 'PAPER'`, `kpis: {}` and
 *      `agents_registered: 0`.
 *
 * The rule under test: a value with no real source is `null` (the UI renders an
 * em dash) — never `0`, `[]`, or a plausible-looking constant.
 *
 * Matches the existing test style: `node --test` over compiled `dist/` output
 * (no extra build step beyond the `npm run build` that `npm test` already runs).
 */

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  mapTradingOverview,
  mapMarketOverview,
  mapProvidersOverview,
  mapSystemOverview,
} = require('../dist/overviewMapping.js');

// ---------------------------------------------------------------------------
// /trading/overview
// ---------------------------------------------------------------------------

test('trading: unknown PnL/trade stats are null, never fabricated zeros', () => {
  const out = mapTradingOverview({}, { positions: [] }, {});
  assert.equal(out.today.trades, null);
  assert.equal(out.today.wins, null);
  assert.equal(out.today.losses, null);
  assert.equal(out.today.gross_profit, null);
  assert.equal(out.today.gross_loss, null);
  assert.equal(out.today.profit_factor, null);
  assert.equal(out.today.unrealized_pnl, null);
  assert.equal(out.today.executed_today, null);
});

test('trading: unrealized PnL comes from the account, not from a net_pnl field', () => {
  const out = mapTradingOverview(
    { total_unrealized_pnl: 14.25, account: 'ACC-1' },
    { positions: [] },
    {},
  );
  assert.equal(out.today.unrealized_pnl, 14.25);
  // The old bug put the same number into a misleading `net_pnl` field.
  assert.equal(out.today.net_pnl, undefined);
  assert.equal(out.account, 'ACC-1');
});

test('trading: executed_today is read from scheduler stats when present', () => {
  const out = mapTradingOverview({}, { positions: [] }, { stats: { trades_executed: 7 } });
  assert.equal(out.today.executed_today, 7);
});

test('trading: recent_trades maps open positions with the real side/quantity fields', () => {
  const out = mapTradingOverview(
    {},
    {
      positions: [
        { ticket: 11, symbol: 'EURUSD', side: 'BUY', quantity: 0.5, profit: 3.2 },
        { ticket: 12, symbol: 'XAUUSD', side: 'SELL', quantity: 1, profit: -1.1 },
      ],
    },
    {},
  );
  assert.equal(out.open_positions, 2);
  assert.equal(out.recent_trades.length, 2);
  assert.deepEqual(out.recent_trades[0], {
    id: 11,
    symbol: 'EURUSD',
    side: 'BUY',
    volume: 0.5,
    pnl: 3.2,
    status: 'OPEN',
  });
  // The old bug read `p.type` / `p.volume`, which are absent on the real payload.
  assert.equal(out.recent_trades[1].side, 'SELL');
  assert.equal(out.recent_trades[1].volume, 1);
});

test('trading: recent_trades is null (not []) when there are no positions', () => {
  assert.equal(mapTradingOverview({}, { positions: [] }, {}).recent_trades, null);
  assert.equal(mapTradingOverview({}, {}, {}).recent_trades, null);
});

test('trading: non-finite numbers from the account are rejected', () => {
  const out = mapTradingOverview(
    { total_unrealized_pnl: 'n/a' },
    { positions: [{ ticket: 1, symbol: 'EURUSD', side: 'BUY', quantity: 'x', profit: NaN }] },
    { stats: { trades_executed: Infinity } },
  );
  assert.equal(out.today.unrealized_pnl, null);
  assert.equal(out.today.executed_today, null);
  assert.equal(out.recent_trades[0].volume, null);
  assert.equal(out.recent_trades[0].pnl, null);
});

// ---------------------------------------------------------------------------
// /market/overview
// ---------------------------------------------------------------------------

test('market: price derives from real bid/ask mid, spread from the feed', () => {
  const out = mapMarketOverview({
    symbols: [{ symbol: 'EURUSD', bid: 1.1, ask: 1.1002, spread: 0.0002, digits: 5 }],
  });
  assert.equal(out.symbols.length, 1);
  assert.equal(out.symbols[0].symbol, 'EURUSD');
  assert.equal(out.symbols[0].price, 1.1001);
  assert.equal(out.symbols[0].spread, 0.0002);
  // No real source for these — must be null, not a guessed value.
  assert.equal(out.symbols[0].change_pct, null);
  assert.equal(out.symbols[0].volatility, null);
});

test('market: session/regime are null when no source exists', () => {
  const out = mapMarketOverview({ symbols: [] });
  assert.equal(out.session, null);
  assert.equal(out.sessions, null);
  assert.equal(out.regime, null);
  assert.deepEqual(out.symbols, []);
});

test('market: a symbol with only a bid still yields a price; no bid/ask yields null', () => {
  const out = mapMarketOverview({
    symbols: [
      { symbol: 'A', bid: 10, digits: 2 },
      { symbol: 'B', spread: 1 },
    ],
  });
  assert.equal(out.symbols[0].price, 10);
  assert.equal(out.symbols[1].price, null);
});

// ---------------------------------------------------------------------------
// /ai/providers
// ---------------------------------------------------------------------------

test('providers: calls_today and budget are null, never invented zeros', () => {
  const out = mapProvidersOverview({
    models: [
      { model: 'a', provider: 'combo' },
      { model: 'b', provider: 'combo' },
      { model: 'c', provider: 'gc' },
    ],
    health: { state: 'CONNECTED' },
  });
  assert.equal(out.router.status, 'up');
  assert.equal(out.router.latency_ms, null);
  assert.equal(out.budget, null);
  for (const p of out.providers) {
    assert.equal(p.calls_today, null);
  }
  const combo = out.providers.find((p) => p.name === 'combo');
  assert.equal(combo.models_available, 2);
  assert.equal(combo.priority, 1);
});

test('providers: status is degraded when the registry is not CONNECTED', () => {
  const out = mapProvidersOverview({ models: [], health: { state: 'DISCONNECTED' } });
  assert.equal(out.router.status, 'degraded');
  assert.deepEqual(out.providers, []);
});

// ---------------------------------------------------------------------------
// /system/overview
// ---------------------------------------------------------------------------

test('system: uptime/version/environment come from health, mode is null', () => {
  const out = mapSystemOverview(
    true,
    {
      status: 'ok',
      uptime_seconds: 99.5,
      version: '0.1.0',
      environment: 'development',
      agents_registered: 1,
    },
    { running: true },
  );
  assert.equal(out.uptime, 99.5);
  assert.equal(out.version, '0.1.0');
  assert.equal(out.environment, 'development');
  assert.equal(out.agents_registered, 1);
  // No runtime source for the operating mode → null, not a hard-coded 'PAPER'.
  assert.equal(out.mode, null);
  assert.equal(out.kpis, null);
});

test('system: agents_registered is null when the health payload lacks it', () => {
  assert.equal(mapSystemOverview(true, {}, {}).agents_registered, null);
  assert.equal(mapSystemOverview(false, {}, {}).agents_registered, null);
});

test('system: service rows reflect real health/scheduler state', () => {
  const up = mapSystemOverview(true, { status: 'ok' }, { running: true });
  assert.deepEqual(
    up.services.map((s) => s.status),
    ['up', 'up', 'up'],
  );

  const down = mapSystemOverview(false, {}, { running: false });
  assert.deepEqual(
    down.services.map((s) => s.status),
    ['up', 'down', 'idle'],
  );
  assert.equal(down.status, 'degraded');
});

test('system: uptime is null when health is down or uptime is non-finite', () => {
  assert.equal(mapSystemOverview(false, { uptime_seconds: 5 }, {}).uptime, null);
  assert.equal(mapSystemOverview(true, { uptime_seconds: 'live' }, {}).uptime, null);
});
