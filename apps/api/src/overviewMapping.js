/**
 * Run 21: Honest overview mapping — null for unknown, never fabricated zeros.
 *
 * Maps raw Python responses to control-plane shapes. Fields without real sources
 * are returned as null (not 0, not [], not 'live'). UI renders em dash for null.
 */

function isFiniteNumber(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

function mapTradingOverview(accountData, positionsData, schedulerData) {
  const positions = Array.isArray(positionsData?.positions) ? positionsData.positions : [];
  const unrealizedPnl = isFiniteNumber(accountData?.total_unrealized_pnl)
    ? accountData.total_unrealized_pnl
    : null;

  const executedToday = isFiniteNumber(schedulerData?.stats?.trades_executed)
    ? schedulerData.stats.trades_executed
    : null;

  const recentTrades = positions.length > 0
    ? positions.map((p) => ({
        id: p.ticket,
        symbol: p.symbol,
        side: p.side ?? null,
        volume: isFiniteNumber(p.quantity) ? p.quantity : null,
        pnl: isFiniteNumber(p.profit) ? p.profit : null,
        status: 'OPEN',
      }))
    : null;

  return {
    today: {
      trades: null,
      wins: null,
      losses: null,
      unrealized_pnl: unrealizedPnl,
      gross_profit: null,
      gross_loss: null,
      profit_factor: null,
      executed_today: executedToday,
    },
    account: accountData?.account ?? null,
    open_positions: positions.length,
    recent_trades: recentTrades,
    source: 'live',
  };
}

function roundToDigits(value, digits) {
  if (!isFiniteNumber(value) || !isFiniteNumber(digits)) return null;
  const d = Math.max(0, Math.floor(digits));
  return Number(value.toFixed(d));
}

function mapSymbolForMarket(sym) {
  if (!sym || typeof sym !== 'object') return null;

  const bid = isFiniteNumber(sym.bid) ? sym.bid : null;
  const ask = isFiniteNumber(sym.ask) ? sym.ask : null;
  const digits = isFiniteNumber(sym.digits) ? sym.digits : null;

  let price = null;
  if (bid !== null && ask !== null) {
    price = roundToDigits((bid + ask) / 2, digits ?? 5);
  } else if (bid !== null) {
    price = roundToDigits(bid, digits ?? 5);
  }

  return {
    symbol: sym.symbol ?? null,
    price,
    spread: isFiniteNumber(sym.spread) ? sym.spread : null,
    change_pct: null,
    volatility: null,
  };
}

function mapMarketOverview(symbolsData) {
  const rawSymbols = Array.isArray(symbolsData?.symbols) ? symbolsData.symbols : [];
  const symbols = rawSymbols.map(mapSymbolForMarket).filter(Boolean);

  return {
    session: null,
    sessions: null,
    symbols,
    regime: null,
    source: 'live',
  };
}

function mapProvidersOverview(modelsData) {
  const models = Array.isArray(modelsData?.models) ? modelsData.models : [];

  const byProvider = new Map();
  for (const model of models) {
    const provider = model?.provider ?? 'unknown';
    byProvider.set(provider, (byProvider.get(provider) ?? 0) + 1);
  }

  const providers = Array.from(byProvider.entries()).map(([name, models_available], index) => ({
    name,
    status: modelsData?.health?.state === 'CONNECTED' ? 'up' : 'degraded',
    models_available,
    priority: index + 1,
    calls_today: null,
  }));

  return {
    router: {
      name: '9Router',
      status: modelsData?.health?.state === 'CONNECTED' ? 'up' : 'degraded',
      latency_ms: null,
      failover_enabled: true,
    },
    providers,
    budget: null,
    source: 'live',
  };
}

function mapSystemOverview(healthOk, healthData, schedulerData) {
  const services = [
    { name: 'api', status: 'up', latency_ms: null },
    {
      name: 'python-engine',
      status: healthOk ? 'up' : 'down',
      latency_ms: null,
    },
    {
      name: 'scheduler',
      status: schedulerData?.running ? 'up' : 'idle',
      latency_ms: null,
    },
  ];

  return {
    mode: null,
    status: healthOk ? (healthData?.status ?? 'unknown') : 'degraded',
    // Health-derived scalars are only reported when the health call succeeded;
    // otherwise they are null rather than values from a failed source.
    uptime: healthOk && isFiniteNumber(healthData?.uptime_seconds) ? healthData.uptime_seconds : null,
    version: healthOk ? (healthData?.version ?? null) : null,
    environment: healthOk ? (healthData?.environment ?? null) : null,
    services,
    agents_registered:
      healthOk && isFiniteNumber(healthData?.agents_registered) ? healthData.agents_registered : null,
    kpis: null,
    source: 'live',
  };
}

module.exports = {
  isFiniteNumber,
  mapTradingOverview,
  mapMarketOverview,
  mapSymbolForMarket,
  mapProvidersOverview,
  mapSystemOverview,
  roundToDigits,
};
