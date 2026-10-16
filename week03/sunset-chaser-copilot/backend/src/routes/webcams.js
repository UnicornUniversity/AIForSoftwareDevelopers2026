import { Router } from 'express';

import { config } from '../config.js';
import { badRequest, parseAt, parseIntParam } from '../lib/params.js';
import { subsolarPoint, sunEquatorial, sunsetEvents, geometricAltitude } from '../services/solar.js';
import { sampleTerminator } from '../services/sampler.js';
import { createWindyClient } from '../services/windy.js';
import { rankCandidates, selectPrimary } from '../services/scoring.js';

export const webcamsRouter = Router();

/**
 * Scored candidates with no LLM in the path.
 *
 * Exists so the ranking can be inspected and tuned without waiting on a model
 * call, and so the deterministic layer is independently demonstrable - it is the
 * ranking the app falls back to, not a debug leftover.
 */
webcamsRouter.get('/near-terminator', async (req, res, next) => {
  const at = parseAt(req.query.at);
  if (at.error) return badRequest(res, at.error);

  const limit = parseIntParam(req.query.limit, {
    name: 'limit',
    fallback: config.chase.maxPrimaryReturned,
    min: 1,
    max: 50,
  });
  if (limit.error) return badRequest(res, limit.error);

  try {
    const sunEq = sunEquatorial(at.date);
    const subsolar = subsolarPoint(at.date, sunEq);
    const client = createWindyClient();

    const points = sampleTerminator(subsolar, config.windy.sampleCount);
    const result = await client.collect(points, {
      radiusKm: config.windy.radiusKm,
      limit: config.windy.limit,
      concurrency: config.windy.concurrency,
      adaptivePages: 3,
    });

    const resolveEvents = (webcam) =>
      Math.abs(geometricAltitude(webcam.latitude, webcam.longitude, at.date, sunEq)) < 12
        ? sunsetEvents(webcam.latitude, webcam.longitude, at.date, sunEq)
        : null;

    const ranked = rankCandidates(result.webcams, {
      date: at.date,
      sunEq,
      subsolar,
      resolveEvents,
    });

    res.set('Cache-Control', 'no-store');
    res.json({
      generatedAt: new Date().toISOString(),
      at: at.date.toISOString(),
      windy: client.stats,
      candidates: { raw: result.rawCount, deduped: result.webcams.length, passedFilters: ranked.length },
      webcams: selectPrimary(ranked, limit.value),
    });
  } catch (err) {
    next(err);
  }
});

/**
 * One webcam, freshly normalised.
 *
 * This is the token-refresh endpoint: when an `<img>` on the frontend 401s, it
 * calls this and swaps in the new `imagePreviewUrl` rather than reloading the
 * whole payload. There is deliberately no image-proxy route - `<img src>` needs
 * no CORS, and a route that fetched an arbitrary caller-supplied URL on the
 * server's behalf would be an SSRF hole for no benefit.
 */
webcamsRouter.get('/:id', async (req, res, next) => {
  const id = String(req.params.id ?? '').trim();
  if (!/^\d{1,20}$/.test(id)) {
    return badRequest(res, 'webcam id must be numeric');
  }

  try {
    const client = createWindyClient();
    const result = await client.byIds([id]);

    if (!client.stats.authOk) {
      return res.status(200).json({
        webcamId: id,
        available: false,
        reason: 'windy_auth_failed',
        message: 'WINDY_API_KEY is missing or was rejected.',
      });
    }

    const webcam = result.webcams[0];
    if (!webcam) {
      return res.status(404).json({
        error: { code: 'not_found', message: `Windy has no active webcam ${id}` },
      });
    }

    res.set('Cache-Control', 'no-store');
    res.json({ ...webcam, available: true });
  } catch (err) {
    next(err);
  }
});
