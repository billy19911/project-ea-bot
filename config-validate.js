"use strict";

const path = require("path");
const fs = require("fs");

// ---- Load .env (fail-safe: env vars always win; missing file is a no-op) ----
try {
  require("dotenv").config({ path: path.resolve(__dirname, ".env"), quiet: true });
} catch {
  // dotenv unavailable — fall back to process.env only
}

// ---- Load Zod -----------------------------------------------------------
function loadZod() {
  const candidates = [
    path.resolve(__dirname, "node_modules", "zod"),
    path.resolve(__dirname, "..", "node_modules", "zod"),
    path.resolve(__dirname, "..", "packages", "shared", "config", "node_modules", "zod"),
  ];
  for (const candidate of candidates) {
    if (fs.existsSync(path.join(candidate, "package.json"))) {
      return require(candidate);
    }
  }
  throw new Error(
    "zod not found. Install di monorepo root:  npm install zod"
  );
}

const { z } = loadZod();

// ---- Environment Schema (harus sama dengan packages/shared/config/src/envSchema.ts) ----
const envSchema = z.object({
  // Application
  NODE_ENV: z
    .enum(["development", "production", "test", "staging"])
    .default("development"),
  PORT: z
    .string()
    .refine((v) => !isNaN(Number(v)) && Number(v) > 0 && Number(v) < 65536, {
      message: "PORT harus angka 1-65535",
    })
    .default("3000"),

  // Logging
  LOG_LEVEL: z
    .enum(["trace", "debug", "info", "warn", "error", "fatal"])
    .default("info"),
  SERVICE_NAME: z.string().min(1, "SERVICE_NAME wajib diisi").default("api"),

  // Database
  DB_HOST: z.string().min(1, "DB_HOST wajib diisi"),
  DB_PORT: z
    .string()
    .refine((v) => !isNaN(Number(v)) && Number(v) > 0, {
      message: "DB_PORT harus angka positif",
    })
    .default("5432"),
  DB_NAME: z.string().min(1, "DB_NAME wajib diisi"),
  DB_USER: z.string().min(1, "DB_USER wajib diisi"),
  DB_PASSWORD: z.string().min(1, "DB_PASSWORD wajib diisi"),
  DB_POOL_MIN: z
    .string()
    .refine((v) => !isNaN(Number(v)) && Number(v) >= 0, {
      message: "DB_POOL_MIN harus angka >= 0",
    })
    .default("2"),
  DB_POOL_MAX: z
    .string()
    .refine((v) => !isNaN(Number(v)) && Number(v) > 0, {
      message: "DB_POOL_MAX harus angka > 0",
    })
    .default("10"),

  // Redis
  REDIS_URL: z
    .string()
    .url("REDIS_URL harus URL valid")
    .default("redis://localhost:6379"),

  // Auth
  JWT_SECRET: z.string().min(1, "JWT_SECRET wajib diisi"),
  JWT_EXPIRY: z.string().default("24h"),

  // External
  EXTERNAL_API_KEY: z.string().optional().default(""),
  EXTERNAL_API_BASE_URL: z.string().url().optional().default(""),

  // Feature flags
  ENABLE_TRACING: z
    .string()
    .transform((v) => v === "true" || v === "1")
    .default("false"),

  // Python service (untuk referensi, divalidasi juga di Python)
  PYTHON_SERVICE_HOST: z.string().default("0.0.0.0"),
  PYTHON_SERVICE_PORT: z
    .string()
    .refine((v) => !isNaN(Number(v)) && Number(v) > 0, {
      message: "PYTHON_SERVICE_PORT harus angka positif",
    })
    .default("8000"),
});

// ---- Validation ---------------------------------------------------------
function main() {
  console.log("🔍 Validasi environment variable...\n");

  const shape = envSchema.shape;
  const missing = [];
  const invalid = [];

  for (const [key, schema] of Object.entries(shape)) {
    const raw = process.env[key];

    if (raw === undefined || raw === "") {
      const hasDefault = schema._def.defaultValue !== undefined;
      if (!hasDefault) missing.push(key);
      continue;
    }

    try {
      schema.parse(raw);
    } catch (err) {
      if (err && typeof err === "object" && "issues" in err) {
        const msgs = err.issues.map((i) => i.message).join("; ");
        invalid.push({ key, message: msgs });
      } else {
        invalid.push({ key, message: String(err) });
      }
    }
  }

  let failed = false;

  if (missing.length > 0) {
    console.error("❌ Variable wajib tidak ada di environment:");
    for (const k of missing) console.error(`   • ${k}`);
    console.error("\n👉 Copy .env.example → .env dan isi nilai yang wajib.");
    failed = true;
  }

  if (invalid.length > 0) {
    console.error("❌ Nilai environment variable tidak valid:");
    for (const entry of invalid) {
      console.error(`   • ${entry.key}: ${entry.message}`);
    }
    failed = true;
  }

  if (failed) {
    console.error("\n🛑 Startup dibatalkan.");
    process.exit(1);
  }

  // Jika lolos — cetak ringkasan
  console.log("✅ Environment variable valid.\n");
  console.log(`   NODE_ENV        = ${process.env.NODE_ENV}`);
  console.log(`   SERVICE_NAME    = ${process.env.SERVICE_NAME}`);
  console.log(`   LOG_LEVEL       = ${process.env.LOG_LEVEL}`);
  console.log(`   PORT            = ${process.env.PORT}`);
  console.log(`   DB_HOST         = ${process.env.DB_HOST}`);
  console.log(`   DB_NAME         = ${process.env.DB_NAME}`);
  console.log(`   DB_USER         = ${process.env.DB_USER}`);
  console.log(`   JWT_SECRET      = ${process.env.JWT_SECRET ? "✓".padEnd(48) : "✗ MISSING"}`);
  console.log(`   REDIS_URL       = ${process.env.REDIS_URL}`);
  console.log(`   ENABLE_TRACING  = ${process.env.ENABLE_TRACING}`);
}

main();
