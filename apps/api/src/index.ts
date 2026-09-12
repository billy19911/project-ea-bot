/**
 * Express API server for EA Bot — dengan structured logging
 */

import express from 'express';
import cors from 'cors';
import { logger, createChild } from './logger';

const app = express();
const PORT = process.env.PORT || 3001;

// Middleware: parse JSON dan attach logger ke request
app.use(cors());
app.use(express.json());

// Middleware: inject child logger per request + traceId
app.use((req, res, next) => {
  const traceId = (req.headers['x-trace-id'] || require('crypto').randomUUID()).toString().slice(0, 36);
  (req as any).log = createChild({ traceId, method: req.method, path: req.url, userAgent: req.headers['user-agent'] }, 'http-request');
  res.setHeader('x-trace-id', traceId);
  next();
});

// Health check
app.get('/health', (req, res) => {
  const log = (req as any).log;
  log.info({ statusCode: 200 }, 'health.check');
  res.json({
    status: 'healthy',
    timestamp: Date.now(),
    uptime: process.uptime(),
  });
});

// Root endpoint
app.get('/', (req, res) => {
  const log = (req as any).log;
  log.info('root.requested');
  res.json({
    message: 'EA Bot API',
    version: '1.0.0',
    service: process.env.SERVICE_NAME || 'api',
    endpoints: {
      health: 'GET /health',
      signals: 'GET /signals, POST /signals',
    },
  });
});

// Trade signals endpoints
const signals: any[] = [];

app.get('/signals', (req, res) => {
  const log = (req as any).log;
  log.info({ count: signals.length }, 'signals.list');
  res.json({ signals, count: signals.length });
});

app.post('/signals', (req, res) => {
  const log = (req as any).log;
  const signal = {
    id: `sig_${Date.now()}`,
    ...req.body,
    timestamp: Date.now(),
  };
  signals.push(signal);
  log.info({ signalId: signal.id }, 'signal.created');
  res.status(201).json(signal);
});

// 404 handler
app.use((req, res) => {
  const log = (req as any).log;
  log.warn({ path: req.path, method: req.method }, 'route.not_found');
  res.status(404).json({ error: 'Not found' });
});

// Error handler
app.use((err: any, req: any, res: any, _next: any) => {
  const log = req?.log || logger;
  log.error({ err: err?.stack, path: req?.path }, 'server.error');
  res.status(500).json({ error: 'Internal server error' });
});

app.listen(PORT, () => {
  logger.info({ port: PORT, nodeEnv: process.env.NODE_ENV, serviceName: process.env.SERVICE_NAME }, 'server.started');
  console.log(`EA Bot API server running on http://localhost:${PORT}`);
});
