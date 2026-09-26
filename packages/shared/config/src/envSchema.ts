import { z } from "zod";

// ============================================================================
// Environment variable schema — shared by ALL services in the monorepo
// Every service validates against this schema at startup.
// Add new variables here; all existing .env files must be updated.
// ============================================================================

export const envSchema = z.object({
  // ------------------------------------------------------------------
  // Node.js / API service
  // ------------------------------------------------------------------
  NODE_ENV: z
    .enum(["development", "production", "test", "staging"])
    .default("development"),
  PORT: z
    .string()
    .refine((val) => !isNaN(Number(val)) && Number(val) > 0 && Number(val) < 65536, {
      message: "PORT must be a number between 1 and 65535",
    })
    .default("3789"),

  // ------------------------------------------------------------------
  // Logging (shared across all services)
  // ------------------------------------------------------------------
  LOG_LEVEL: z
    .enum(["trace", "debug", "info", "warn", "error", "fatal"])
    .default("info"),
  SERVICE_NAME: z
    .string()
    .min(1, "SERVICE_NAME is required")
    .default("api"),

  // ------------------------------------------------------------------
  // Database — PostgreSQL (shared)
  // ------------------------------------------------------------------
  DB_HOST: z.string().min(1, "DB_HOST is required"),
  DB_PORT: z
    .string()
    .refine((val) => !isNaN(Number(val)) && Number(val) > 0, {
      message: "DB_PORT must be a positive number",
    })
    .default("5432"),
  DB_NAME: z.string().min(1, "DB_NAME is required"),
  DB_USER: z.string().min(1, "DB_USER is required"),
  DB_PASSWORD: z.string().min(1, "DB_PASSWORD is required"),
  DB_POOL_MIN: z
    .string()
    .refine((val) => !isNaN(Number(val)) && Number(val) >= 0, {
      message: "DB_POOL_MIN must be a non-negative integer",
    })
    .default("2"),
  DB_POOL_MAX: z
    .string()
    .refine((val) => !isNaN(Number(val)) && Number(val) > 0, {
      message: "DB_POOL_MAX must be a positive integer",
    })
    .default("10"),

  // ------------------------------------------------------------------
  // Redis (shared — used by API, Python service, queues)
  // ------------------------------------------------------------------
  REDIS_URL: z
    .string()
    .url("REDIS_URL must be a valid URL")
    .default("redis://localhost:6379"),

  // ------------------------------------------------------------------
  // Application secrets / keys (set in production)
  // ------------------------------------------------------------------
  JWT_SECRET: z.string().min(1, "JWT_SECRET is required"),
  JWT_EXPIRY: z.string().default("24h"),

  // ------------------------------------------------------------------
  // External API keys (optional — fill when integrating)
  // ------------------------------------------------------------------
  EXTERNAL_API_KEY: z.string().optional().default(""),
  EXTERNAL_API_BASE_URL: z.string().url().optional().default(""),

  // ------------------------------------------------------------------
  // Feature flags / runtime toggles
  // ------------------------------------------------------------------
  ENABLE_TRACING: z
    .string()
    .transform((val) => val === "true" || val === "1")
    .default("false"),

  // ------------------------------------------------------------------
  // Python service specific (validated by Python; kept for reference)
  // ------------------------------------------------------------------
  PYTHON_SERVICE_HOST: z
    .string()
    .default("0.0.0.0"),
  PYTHON_SERVICE_PORT: z
    .string()
    .refine((val) => !isNaN(Number(val)) && Number(val) > 0, {
      message: "PYTHON_SERVICE_PORT must be a positive number",
    })
    .default("8787"),
});

// Infer the TypeScript type from the schema
export type Environment = z.infer<typeof envSchema>;

// Singleton validated config — parsed once at startup
let _config: Environment | null = null;

/**
 * Validate and return the full environment object.
 * Calls process.env through Zod so every variable is coerced/validated.
 * Throws ZodError with a clear message if anything is missing or invalid.
 */
export function validateConfig(): Environment {
  if (_config) return _config;

  _config = envSchema.parse(process.env);
  return _config;
}

/**
 * Get a previously validated config, or validate now if not done.
 */
export function getConfig(): Environment {
  return validateConfig();
}

/**
 * Reset the cached config (useful in tests).
 */
export function resetConfig(): void {
  _config = null;
}
