/**
 * Phase 28: API Security middleware — input validation, CSP, secure headers
 */

import { Request, Response, NextFunction } from 'express';

/**
 * Validate JSON payload size and structure before processing
 */
export function validatePayload(req: Request, res: Response, next: NextFunction): void {
  if (req.method === 'POST' || req.method === 'PATCH' || req.method === 'PUT') {
    const contentType = req.headers['content-type'] || '';
    if (!contentType.includes('application/json')) {
      res.status(400).json({ error: 'Content-Type must be application/json' });
      return;
    }

    const contentLength = parseInt(req.headers['content-length'] || '0', 10);
    const MAX_PAYLOAD_SIZE = 1048576; // 1MB
    
    if (contentLength > MAX_PAYLOAD_SIZE) {
      res.status(413).json({ error: 'Payload too large' });
      return;
    }
  }

  next();
}

/**
 * Sanitize and validate request query/body parameters
 */
export function sanitizeInput(req: Request, res: Response, next: NextFunction): void {
  // Basic SQLi/XSS check: reject if input contains suspicious patterns
  const suspicious = /('|"|-{2}|\/\*|\*\/|xp_|sp_|exec|script|<|>)/gi;

  const checkField = (val: any): boolean => {
    if (typeof val === 'string') return suspicious.test(val);
    if (typeof val === 'object' && val !== null) {
      return Object.values(val).some(checkField);
    }
    return false;
  };

  if (checkField(req.query) || checkField(req.body)) {
    const log = (req as any).log;
    log?.warn({ path: req.path, method: req.method }, 'security.suspicious_input');
    res.status(400).json({ error: 'Invalid input detected' });
    return;
  }

  next();
}

/**
 * Security headers: CSP, X-Frame-Options, X-Content-Type-Options, etc.
 */
export function securityHeaders(req: Request, res: Response, next: NextFunction): void {
  // Prevent clickjacking
  res.setHeader('X-Frame-Options', 'DENY');
  
  // Prevent MIME type sniffing
  res.setHeader('X-Content-Type-Options', 'nosniff');
  
  // Enable XSS protection (legacy header, mostly for older browsers)
  res.setHeader('X-XSS-Protection', '1; mode=block');
  
  // Referrer policy
  res.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin');
  
  // Permissions policy (formerly Feature-Policy)
  res.setHeader('Permissions-Policy', 'geolocation=(), microphone=(), camera=()');
  
  // Content Security Policy (basic; override per endpoint as needed)
  res.setHeader('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'");

  next();
}

/**
 * Prevent parameter pollution attacks
 */
export function preventParameterPollution(req: Request, res: Response, next: NextFunction): void {
  // Flag if query has duplicate keys (e.g., ?id=1&id=2)
  const queryString = req.url.split('?')[1] || '';
  const params = new URLSearchParams(queryString);
  const seen = new Set<string>();

  for (const [key] of params.entries()) {
    if (seen.has(key)) {
      const log = (req as any).log;
      log?.warn({ key, url: req.url }, 'security.duplicate_param');
      res.status(400).json({ error: 'Duplicate query parameters not allowed' });
      return;
    }
    seen.add(key);
  }

  next();
}
