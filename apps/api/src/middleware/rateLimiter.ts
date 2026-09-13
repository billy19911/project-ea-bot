/**
 * Phase 28: Rate limiting middleware — protect against abuse and DDoS
 */

import rateLimit from 'express-rate-limit';
import { Request, Response } from 'express';

/**
 * General API rate limiter: 100 requests per 15 minutes per IP
 */
export const generalLimiter = rateLimit({
  windowMs: 15 * 60 * 1000, // 15 minutes
  max: 100,
  message: { error: 'Too many requests, please try again later' },
  standardHeaders: true,
  legacyHeaders: false,
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
});

/**
 * Strict rate limiter for sensitive endpoints (e.g., /auth/login): 5 per 15 minutes
 */
export const authLimiter = rateLimit({
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
});

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
