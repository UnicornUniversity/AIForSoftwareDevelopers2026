import { Router } from 'express';

import { config } from '../config.js';
import { cacheStats } from '../cache.js';

export const healthRouter = Router();

/**
 * The one route allowed to answer non-200.
 *
 * Reports *whether* each key is configured, never the key itself, so this is
 * safe to leave reachable. The frontend uses it to explain a first run with no
 * `.env`, which is the most likely state for anyone cloning the repo.
 */
healthRouter.get('/', (req, res) => {
  const cache = cacheStats();
  const ok = true;

  res.status(ok ? 200 : 503).json({
    ok,
    checks: {
      windyKey: config.windy.apiKey !== '',
      deepseekKey: config.llm.apiKey !== '',
      node: process.version,
      cache,
      missingKeys: config.missingKeys,
      model: config.llm.model,
      samples: config.windy.sampleCount,
      radiusKm: config.windy.radiusKm,
    },
    uptimeSeconds: Math.round(process.uptime()),
  });
});
