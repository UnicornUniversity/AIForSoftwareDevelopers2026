import express from 'express';

import { chat, defaultModel, deepseekBaseURL } from './deepseek.js';

export function createApp() {
  const app = express();
  app.use(express.json({ limit: '1mb' }));

  app.get('/health', (_req, res) => {
    res.json({
      status: 'ok',
      model: defaultModel,
      baseURL: deepseekBaseURL,
      uptimeSeconds: Math.round(process.uptime()),
    });
  });

  app.post('/api/chat', async (req, res) => {
    const { prompt, messages, model, temperature, json } = req.body ?? {};

    // Accept either a bare prompt or a full message history.
    const history =
      messages ?? (typeof prompt === 'string' ? [{ role: 'user', content: prompt }] : null);

    if (!Array.isArray(history) || history.length === 0) {
      return res.status(400).json({
        error: 'Provide "prompt" (string) or "messages" (non-empty array of {role, content}).',
      });
    }

    res.json(await chat(history, { model, temperature, json }));
  });

  app.use((req, res) => {
    res.status(404).json({ error: `No route for ${req.method} ${req.originalUrl}` });
  });

  // Express 5 forwards rejected handlers here, so a DeepSeek failure reports its
  // own reason (401, timeout, connection error) instead of a bare 500.
  app.use((err, req, res, _next) => {
    console.error(`[error] ${req.method} ${req.originalUrl}: ${err.message}`);
    res.status(err.status ?? 502).json({ error: err.message });
  });

  return app;
}
