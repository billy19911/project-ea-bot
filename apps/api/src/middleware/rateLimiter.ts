/**
 * Phase 28: Rate limiting middleware — protect against abuse and DDoS
 */

import rateLimit from 'express-rate-limit';
import { Request, Response } from 'express';
// Phase 28 / Run 15: plain-JS rate limit policy (unit-testable without a build step).
import { GENERAL_LIMIT_MAX, skipPollingRead } from './rateLimitPolicy.js';

/**
 * General API rate limiter: 600 requests per 15 minutes per IP.
 *
 * Run 15: raised from 100 → 600. The web dashboard polls read-only monitoring
 * endpoints every 10s (≈18 req/min, i.e. 270 req/15 min) purely from leaving a
 * tab open, so the old 100/15 min cap 429-ed the API's own UI. 600/15 min keeps
 * a real abuse guard (~40 req/min sustained) while clearing honest dashboard use.
 * In addition, idempotent read-only polling endpoints are skipped entirely via
 * `skip` (see `skipPollingRead`) so continuous monitoring never trips the limit;
 * mutations and every other route remain limited.
 */
export const generalLimiterOptions = {
  windowMs: 15 * 60 * 1000, // 15 minutes
  max: GENERAL_LIMIT_MAX,
  message: { error: 'Too many requests, please try again later' },
  standardHeaders: true,
  legacyHeaders: false,
  skip: skipPollingRead,
  keyGenerator: (req: Request) => {
    // Use X-Forwarded-For if behind proxy, else socket IP
    const forwarded = req.headers['x-forwarded-for'];
    if (typeof forwarded === 'string') {
      return forwarded.split(',')[0].trim();
    }
    return req.socket.remoteAddress || 'unknown';
  },
  handler: (req: Request, res: Response) => {
    const log = (req as any).log;
    log?.warn({ ip: req.ip, path: req.path }, 'rate_limit.exceeded');
    res.status(429).json({ error: 'Too many requests, please try again later' });
  },
};

// express-rate-limit v7 does not expose the raw config on the returned middleware,
// so the exact options object is exported above for tests/inspection.
export const generalLimiter = rateLimit(generalLimiterOptions);

/**
 * Strict rate limiter for sensitive endpoints (e.g., /auth/login): 5 per 15 minutes
 */
export const authLimiterOptions = {
  windowMs: 15 * 60 * 1000,
  max: 5,
  message: { error: 'Too many authentication attempts, please try again later' },
  standardHeaders: true,
  legacyHeaders: false,
  skipSuccessfulRequests: false,
  keyGenerator: (req: Request) => {
    const forwarded = req.headers['x-forwarded-for'];
    if (typeof forwarded === 'string') {
      return forwarded.split(',')[0].trim();
    }
    return req.socket.remoteAddress || 'unknown';
  },
  handler: (req: Request, res: Response) => {
    const log = (req as any).log;
    log?.warn({ ip: req.ip, path: req.path }, 'rate_limit.auth_exceeded');
    res.status(429).json({ error: 'Too many authentication attempts' });
  },
};

export const authLimiter = rateLimit(authLimiterOptions);

/**
 * WebSocket rate limiter (per-connection tracking in-memory)
 */
const wsConnectionCounts = new Map<string, number>();
const WS_MAX_CONNECTIONS_PER_IP = 3;

export function wsRateLimitCheck(ip: string): boolean {
  const count = wsConnectionCounts.get(ip) || 0;
  return count < WS_MAX_CONNECTIONS_PER_IP;
}

export function wsConnectionOpen(ip: string): void {
  wsConnectionCounts.set(ip, (wsConnectionCounts.get(ip) || 0) + 1);
}

export function wsConnectionClose(ip: string): void {
  const count = wsConnectionCounts.get(ip) || 0;
  if (count > 0) {
    wsConnectionCounts.set(ip, count - 1);
  }
}
