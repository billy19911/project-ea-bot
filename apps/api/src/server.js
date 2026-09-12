/**
 * Example Express/Fastify app yang memakai structured logger.
 *
 * Jalankan dengan:
 *   cd apps/api && node src/server.js
 *
 * Sebelum jalan, pastikan .env sudah di-copy dari .env.example dan
 * environment variable wajib sudah diisi.
 */

"use strict";

const http = require("http");
const { logger, createChild } = require("./logger");

// ---------------------------------------------------------------------------
// Config validation (wajib dijalankan di startup)
// ---------------------------------------------------------------------------
function validateEnv() {
  const required = [
    "DB_HOST",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "JWT_SECRET",
    "SERVICE_NAME",
  ];

  const missing = required.filter((k) => !process.env[k]);
  if (missing.length > 0) {
    logger.error(
      { missing },
      "startup.failed — missing required environment variables"
    );
    process.exit(1);
  }

  const logLevel = process.env.LOG_LEVEL || "info";
  const validLevels = ["trace", "debug", "info", "warn", "error", "fatal"];
  if (!validLevels.includes(logLevel)) {
    logger.error(
      { logLevel, validLevels },
      "startup.failed — invalid LOG_LEVEL"
    );
    process.exit(1);
  }

  logger.info(
    {
      nodeEnv: process.env.NODE_ENV,
      logLevel,
      serviceName: process.env.SERVICE_NAME,
      port: process.env.PORT || 3000,
    },
    "startup.ready"
  );
}

// ---------------------------------------------------------------------------
// HTTP server sederhana (contoh — ganti dengan Express/Fastify saat integrate)
// ---------------------------------------------------------------------------
function createServer() {
  const port = Number(process.env.PORT) || 3000;

  const server = http.createServer((req, res) => {
    const traceId =
      (req.headers["x-trace-id"] || require("crypto").randomUUID())
        .toString()
        .slice(0, 36);

    // Child logger untuk request ini
    const reqLog = createChild(
      {
        traceId,
        method: req.method,
        path: req.url,
        userAgent: req.headers["user-agent"],
      },
      "http-request"
    );

    reqLog.info({ statusCode: 200 }, "request.received");

    // Set traceId di response headers
    res.setHeader("x-trace-id", traceId);

    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(
      JSON.stringify({
        service: process.env.SERVICE_NAME,
        traceId,
        message: "project-ea-bot API is running",
        timestamp: new Date().toISOString(),
      })
    );

    reqLog.info("request.completed");
  });

  server.on("error", (err) => {
    logger.error({ err }, "server.error");
    process.exit(1);
  });

  server.on("listening", () => {
    logger.info({ port }, "server.listening");
  });

  server.listen(port);
  return server;
}

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------
validateEnv();
const server = createServer();
