/**
 * Structured JSON logger for Node.js services (apps/api).
 *
 * Setup:
 *   import { logger, createChild } from "./logger";
 *
 * Usage:
 *   logger.info({ userId }, "user.login.success");
 *   logger.error({ err, message: "something failed" }, "db.query.failed");
 *
 * Per-request child logger (with traceId):
 *   const reqLog = createChild({ traceId, path: req.url });
 *   reqLog.info("request.started");
 *
 * Environment variables:
 *   LOG_LEVEL   — trace|debug|info|warn|error|fatal (default: info)
 *   NODE_ENV    — jika "development" gunakan pretty-print via pino-pretty
 *   SERVICE_NAME — ditambahkan otomatis ke setiap log line
 */

import pino from "pino";

// ---------------------------------------------------------------------------
// Transport: pretty-print in development, JSON in production
// ---------------------------------------------------------------------------
function getTransport() {
  if (process.env.NODE_ENV === "development") {
    try {
      // pino-pretty harus terinstall sebagai devDependency
      const pretty = require("pino-pretty");
      return {
        target: "pino-pretty",
        options: {
          colorize: true,
          translateTime: "SYS:standard",
          ignore: "pid,hostname",
        },
      };
    } catch {
      // Fallback: jika pino-pretty tidak terinstall, log JSON biasa
      console.warn("pino-pretty not found — falling back to JSON output");
    }
  }
  return undefined; // default: JSON to stdout
}

// ---------------------------------------------------------------------------
// Base logger
// ---------------------------------------------------------------------------
export const logger = pino({
  transport: getTransport(),
  level: (process.env.LOG_LEVEL || "info").toLowerCase(),
  base: {
    service: process.env.SERVICE_NAME || "api",
  },
  // Semua log punya timestamp ISO-8601, level, service name, dan message
  formatters: {
    level: (label) => ({ level: label }),
  },
});

// ---------------------------------------------------------------------------
// Child logger factory — untuk request-scoped logging dengan traceId
// ---------------------------------------------------------------------------
/**
 * Buat child logger yang membawa traceId dan metadata tambahan.
 * Semua log dari child logger ini akan inherit field dari parent.
 */
export function createChild(
  bindings: Record<string, unknown>,
  childName?: string
): pino.Logger {
  const merged = childName ? { ...bindings, name: childName } : bindings;
  return logger.child(merged);
}

// ---------------------------------------------------------------------------
// Shortcuts — agar kodemu lebih readable
// ---------------------------------------------------------------------------
export const trace = logger.trace.bind(logger);
export const debug = logger.debug.bind(logger);
export const info  = logger.info.bind(logger);
export const warn  = logger.warn.bind(logger);
export const error = logger.error.bind(logger);
export const fatal = logger.fatal.bind(logger);
