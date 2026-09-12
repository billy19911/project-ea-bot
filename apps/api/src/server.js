"use strict";

const http = require("http");
const path = require("path");
const fs = require("fs");

// Resolve logger relative ke project root (di mana node_modules/zod hidup)
const loggerPath = path.resolve(__dirname, "../../packages/shared/config/src/logger.ts");

// Karena logger.ts pakai ESM import, kita butuh transpilasi cepat atau
// kita ganti jadi require CommonJS. Untuk sekarang, kita buat logger inline
// supaya server.js bisa jalan tanpa build step.

// ---------------------------------------------------------------------------
// Inline structured logger (mirroring apps/api/src/logger.ts)
// ---------------------------------------------------------------------------
let pino;
try {
  pino = require("pino");
} catch {
  // Fallback: gunakan console dengan format JSON
  console.warn("pino not installed — using console-based logger");
}

function getLogger() {
  const level = (process.env.LOG_LEVEL || "info").toLowerCase();
  const service = process.env.SERVICE_NAME || "api";

  if (pino) {
    const transport =
      process.env.NODE_ENV === "development"
        ? { target: "pino-pretty", options: { colorize: true, translateTime: "SYS:standard", ignore: "pid,hostname" } }
        : undefined;

    const logger = pino({
      transport,
      level,
      base: { service },
      formatters: { level: (label) => ({ level: label }) },
    });

    logger.child = function (bindings, name) {
      return logger.child(bindings, name);
    };

    return logger;
  }

  // Fallback: console JSON
  return {
    info: (...args) => console.log(JSON.stringify({ level: "info", service, msg: args[args.length - 1], ts: new Date().toISOString(), ...args[0] || {} })),
    error: (...args) => console.error(JSON.stringify({ level: "error", service, msg: args[args.length - 1], ts: new Date().toISOString(), ...args[0] || {} })),
    warn: (...args) => console.warn(JSON.stringify({ level: "warn", service, msg: args[args.length - 1], ts: new Date().toISOString(), ...args[0] || {} })),
    debug: (...args) => console.log(JSON.stringify({ level: "debug", service, msg: args[args.length - 1], ts: new Date().toISOString(), ...args[0] || {} })),
    trace: (...args) => console.log(JSON.stringify({ level: "trace", service, msg: args[args.length - 1], ts: new Date().toISOString(), ...args[0] || {} })),
    fatal: (...args) => console.error(JSON.stringify({ level: "fatal", service, msg: args[args.length - 1], ts: new Date().toISOString(), ...args[0] || {} })),
    child: () => getLogger(),
  };
}

const logger = getLogger();
const createChild = (bindings, name) => logger.child(bindings, name);

// ---------------------------------------------------------------------------
// Config validation
// ---------------------------------------------------------------------------
function validateEnv() {
  const required = ["DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD", "JWT_SECRET", "SERVICE_NAME"];
  const missing = required.filter((k) => !process.env[k]);
  if (missing.length > 0) {
    logger.error({ missing }, "startup.failed — missing required environment variables");
    process.exit(1);
  }
  const logLevel = process.env.LOG_LEVEL || "info";
  const validLevels = ["trace", "debug", "info", "warn", "error", "fatal"];
  if (!validLevels.includes(logLevel)) {
    logger.error({ logLevel, validLevels }, "startup.failed — invalid LOG_LEVEL");
    process.exit(1);
  }
  logger.info({ nodeEnv: process.env.NODE_ENV, logLevel, serviceName: process.env.SERVICE_NAME, port: process.env.PORT || 3000 }, "startup.ready");
}

// ---------------------------------------------------------------------------
// HTTP server
// ---------------------------------------------------------------------------
function createServer() {
  const port = Number(process.env.PORT) || 3000;
  const server = http.createServer((req, res) => {
    const traceId = (req.headers["x-trace-id"] || require("crypto").randomUUID()).toString().slice(0, 36);
    const reqLog = createChild({ traceId, method: req.method, path: req.url, userAgent: req.headers["user-agent"] }, "http-request");
    reqLog.info({ statusCode: 200 }, "request.received");
    res.setHeader("x-trace-id", traceId);
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ service: process.env.SERVICE_NAME, traceId, message: "project-ea-bot API is running", timestamp: new Date().toISOString() }));
    reqLog.info("request.completed");
  });
  server.on("error", (err) => { logger.error({ err }, "server.error"); process.exit(1); });
  server.on("listening", () => { logger.info({ port }, "server.listening"); });
  server.listen(port);
  return server;
}

validateEnv();
const server = createServer();
