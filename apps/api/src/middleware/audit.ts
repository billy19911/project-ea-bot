/**
 * Phase 28: Audit logging middleware — request/response audit trail
 * Logs user, method, path, status, latency, IP (if available), traceId.
 */

import { Request, Response, NextFunction } from 'express';
import crypto from 'crypto';
import { logger } from '../logger';

export interface AuditEvent {
  timestamp: string;
  ip?: string;
  userId?: string;
  method: string;
  path: string;
  status: number;
  latencyMs: number;
  userAgent?: string;
  traceId?: string;
  sessionId?: string;
}

const auditLogBuffer: AuditEvent[] = [];
const MAX_AUDIT_LOGS = 1000;

/**
 * Get client IP (X-Forwarded-For normalized to first non-trusted)
 */
function getClientIp(req: Request): string {
  const forwarded = req.headers['x-forwarded-for'];
  if (typeof forwarded === 'string') {
    return forwarded.split(',')[0].trim();
  }
  return req.socket.remoteAddress || 'unknown';
}

/**
 * Generate session/token ID (mock for now; could derive from JWT sub)
 */
function getSessionId(req: Request): string {
  return (req.headers['x-session-id'] as string) || crypto.randomBytes(8).toString('hex');
}

/**
 * Middleware: log every request/response to audit buffer
 */
export function auditMiddleware(req: Request, res: Response, next: NextFunction): void {
  const start = Date.now();
  const { method, path, headers, query } = req;
  const traceId = (req.headers['x-trace-id'] as string) || '';
  const sessionId = getSessionId(req);
  const userAgent = headers['user-agent'];

  // Capture response normally
  res.on('finish', () => {
    const latencyMs = Date.now() - start;
    const status = res.statusCode;
    // Express 5 query objects have a null prototype: coerce safely via URLSearchParams
    const queryString = new URLSearchParams(query as Record<string, string>).toString();

    const auditEvent: AuditEvent = {
      timestamp: new Date().toISOString(),
      ip: getClientIp(req),
      userId: (req as any).user?.userId,
      method,
      path: queryString ? `${path}?${queryString}` : path,
      status,
      latencyMs,
      userAgent,
      traceId,
      sessionId,
    };

    auditLogBuffer.unshift(auditEvent);

    if (auditLogBuffer.length > MAX_AUDIT_LOGS) {
      auditLogBuffer.pop();
    }

    // Log to pino if attached (pino has no .audit method — log as info event)
    const log = (req as any).log || logger;
    log.info({ audit: auditEvent }, 'audit.event');
  });

  next();
}

/**
 * Simple in-memory audit log endpoint (development only — avoid in prod)
 * GET /audit-logs?limit=100
 */
export async function fetchAuditLogs(limit: number = 100): Promise<AuditEvent[]> {
  return auditLogBuffer.slice(0, limit);
}

export const AUDIT_SECRET = process.env.AUDIT_SECRET || 'dev-audit-secret';
export const AUDIT_KEY = process.env.AUDIT_KEY || 'ea-bot-audit-key';