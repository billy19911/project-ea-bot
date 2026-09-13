/**
 * Phase 28: WebSocket security middleware — connection validation, auth, rate limiting
 * Secure real-time connections for live market data feeds
 */

import { Request } from 'express';
import { WebSocket, Server as WSServer } from 'ws';
import jwt from 'jsonwebtoken';
import { wsRateLimitCheck, wsConnectionOpen, wsConnectionClose } from './rateLimiter';
import { AuthPayload } from './auth';

const JWT_SECRET = process.env.JWT_SECRET || 'dev-secret-change-in-production';

export interface WSAuthContext {
  userId: string;
  role: 'admin' | 'user' | 'readonly';
  iat: number;
  exp: number;
}

export interface SecureWebSocket extends WebSocket {
  isAlive: boolean;
  auth?: WSAuthContext;
  ip?: string;
}

/**
 * Validate incoming WebSocket upgrade request
 */
export function wsAuthHandler(req: Request): boolean {
  const token = extractToken(req);
  if (!token) {
    return false;
  }

  try {
    const decoded = jwt.verify(token, JWT_SECRET) as AuthPayload;
    (req as any).wsAuth = decoded;
    return true;
  } catch {
    return false;
  }
}

/**
 * Extract Bearer token from query or headers
 */
function extractToken(req: Request): string | null {
  // Try Authorization header first
  const authHeader = req.headers.authorization;
  if (authHeader?.startsWith('Bearer ')) {
    return authHeader.substring(7);
  }

  // Fallback to query parameter (less secure but sometimes necessary)
  const token = (req.url.split('token=')[1] || '').split('&')[0];
  return token || null;
}

/**
 * Get client IP from WebSocket upgrade request
 */
export function getWSClientIp(req: Request): string {
  const forwarded = req.headers['x-forwarded-for'];
  if (typeof forwarded === 'string') {
    return forwarded.split(',')[0].trim();
  }
  return req.socket.remoteAddress || 'unknown';
}

/**
 * Setup WebSocket connection tracking and heartbeat
 */
export function setupWSConnection(ws: SecureWebSocket, req: Request): void {
  const ip = getWSClientIp(req);

  // Attach auth context
  ws.auth = (req as any).wsAuth;
  ws.ip = ip;
  ws.isAlive = true;

  // Rate limit tracking
  wsConnectionOpen(ip);

  // Heartbeat to detect stale connections
  ws.on('pong', () => {
    ws.isAlive = true;
  });

  // Cleanup on close
  ws.on('close', () => {
    wsConnectionClose(ip);
  });
}

/**
 * Heartbeat interval handler — ping all active connections
 */
export function setupWSHeartbeat(wss: WSServer): NodeJS.Timer {
  return setInterval(() => {
    wss.clients.forEach((ws) => {
      const sws = ws as SecureWebSocket;
      if (sws.isAlive === false) {
        sws.terminate();
        return;
      }
      sws.isAlive = false;
      sws.ping();
    });
  }, 30000); // 30 seconds
}

/**
 * Validate WebSocket message origin/structure
 */
export function validateWSMessage(msg: any): { valid: boolean; error?: string } {
  if (typeof msg !== 'object' || msg === null) {
    return { valid: false, error: 'Message must be JSON object' };
  }

  const { type, data } = msg;
  if (typeof type !== 'string' || type.length === 0) {
    return { valid: false, error: 'Missing or invalid message type' };
  }

  if (type.length > 64) {
    return { valid: false, error: 'Message type too long' };
  }

  // Prevent suspicious patterns
  if (/[<>"{};]/.test(type)) {
    return { valid: false, error: 'Message type contains suspicious characters' };
  }

  return { valid: true };
}

/**
 * Check if user role can access WebSocket
 */
export function canAccessWS(role: string): boolean {
  return ['admin', 'user', 'readonly'].includes(role);
}
