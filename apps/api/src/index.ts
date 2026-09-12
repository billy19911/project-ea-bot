/**
 * Express API server for EA Bot
 */

import express from 'express';
import cors from 'cors';

const app = express();
const PORT = process.env.PORT || 3001;

app.use(cors());
app.use(express.json());

// Health check
app.get('/health', (req, res) => {
  res.json({
    status: 'healthy',
    timestamp: Date.now(),
    uptime: process.uptime()
  });
});

// Root endpoint
app.get('/', (req, res) => {
  res.json({
    message: 'EA Bot API',
    version: '1.0.0',
    endpoints: {
      health: 'GET /health',
      signals: 'GET /signals, POST /signals'
    }
  });
});

// Trade signals endpoints
const signals = [];

app.get('/signals', (req, res) => {
  res.json({ signals, count: signals.length });
});

app.post('/signals', (req, res) => {
  const signal = {
    id: `sig_${Date.now()}`,
    ...req.body,
    timestamp: Date.now()
  };
  signals.push(signal);
  res.status(201).json(signal);
});

app.listen(PORT, () => {
  console.log(`EA Bot API server running on http://localhost:${PORT}`);
});
