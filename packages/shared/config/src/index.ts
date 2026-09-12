/**
 * @project-ea-bot/shared-config — public API surface
 *
 * Re-export everything so consuming services import from one place.
 *
 * Usage in a Node.js service:
 *   import { validateConfig, type Environment } from "@project-ea-bot/shared-config";
 *   const cfg = validateConfig();
 */

export { envSchema, validateConfig, getConfig, resetConfig, type Environment } from "./envSchema";
