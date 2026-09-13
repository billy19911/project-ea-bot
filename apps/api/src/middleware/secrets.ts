/**
 * Phase 28: Secret management utilities — safe config loading and redaction
 * Never logs raw secrets. Validates required vars in production.
 */

import dotenv from 'dotenv';
import { logger } from '../logger';

// Load .env only in non-production (production should inject env vars)
if (process.env.NODE_ENV !== 'production') {
  dotenv.config();
}

const SECRET_PATTERNS = [
  /password/i,
  /secret/i,
  /token/i,
  /key/i,
  /credential/i,
  /api[_-]?key/i,
];

export function isSecretKey(key: string): boolean {
  return SECRET_PATTERNS.some((pattern) => pattern.test(key));
}

export function redactValue(key: string, value: unknown): unknown {
  if (isSecretKey(key)) {
    return '[REDACTED]';
  }
  if (typeof value === 'object' && value !== null) {
    return redactSecrets(value as Record<string, unknown>);
  }
  return value;
}

export function redactSecrets(obj: Record<string, unknown>): Record<string, unknown> {
  const redacted: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(obj)) {
    redacted[key] = redactValue(key, value);
  }
  return redacted;
}

/**
 * Validate required production secrets
 */
export function validateSecrets(): void {
  const required = ['JWT_SECRET', 'AUDIT_SECRET'];
  const missing = required.filter((key) => !process.env[key]);

  if (process.env.NODE_ENV === 'production' && missing.length > 0) {
    logger.fatal({ missing }, 'secrets.missing_required');
    throw new Error(`Missing required secrets: ${missing.join(', ')}`);
  }

  if (process.env.NODE_ENV !== 'production' && missing.length > 0) {
    logger.warn({ missing }, 'secrets.using_dev_defaults');
  }

  // Never allow obvious default secret in production
  if (process.env.NODE_ENV === 'production' && process.env.JWT_SECRET === 'dev-secret-change-in-production') {
    logger.fatal('secrets.default_jwt_in_production');
    throw new Error('JWT_SECRET must be changed in production');
  }
}

export function getSecret(name: string, fallback?: string): string {
  const value = process.env[name] || fallback;
  if (!value) throw new Error(`Missing secret: ${name}`);
  return value;
}
