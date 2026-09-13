/**
 * Phase 28: Authentication middleware — JWT token validation
 * No live trading enablement. Mock auth for development.
 */

import { Request, Response, NextFunction } from 'express';
import jwt from 'jsonwebtoken';

const JWT_SECRET = process.env.JWT_SECRET || 'dev-secret-change-in-production';
const JWT_EXPIRY = process.env.JWT_EXPIRY || '24h';

export interface AuthPayload {
  userId: string;
  role: 'admin' | 'user' | 'readonly';
  iat?: number;
  exp?: number;
}

export interface AuthRequest extends Request {
  user?: AuthPayload;
}

/**
 * Middleware: verify JWT from Authorization header
 */
export function authenticate(req: Request, res: Response, next: NextFunction): void {
  const authHeader = req.headers.authorization;
  
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    res.status(401).json({ error: 'Unauthorized: Missing or invalid token' });
    return;
  }

  const token = authHeader.substring(7);

  try {
    const decoded = jwt.verify(token, JWT_SECRET) as AuthPayload;
    (req as AuthRequest).user = decoded;
    next();
  } catch (err: any) {
    const log = (req as any).log;
    log?.warn({ err: err.message }, 'auth.token_invalid');
    res.status(401).json({ error: 'Unauthorized: Invalid or expired token' });
  }
}

/**
 * Generate JWT token for a user (login endpoint helper)
 */
export function generateToken(userId: string, role: AuthPayload['role']): string {
  return jwt.sign({ userId, role } as any, JWT_SECRET as any, { expiresIn: JWT_EXPIRY as any });
}

/**
 * Role-based authorization middleware factory
 */
export function authorize(...allowedRoles: AuthPayload['role'][]) {
  return (req: Request, res: Response, next: NextFunction): void => {
    const user = (req as AuthRequest).user;
    
    if (!user) {
      res.status(401).json({ error: 'Unauthorized: No user context' });
      return;
    }

    if (!allowedRoles.includes(user.role)) {
      const log = (req as any).log;
      log?.warn({ userId: user.userId, role: user.role, allowedRoles }, 'auth.forbidden');
      res.status(403).json({ error: 'Forbidden: Insufficient permissions' });
      return;
    }

    next();
  };
}
