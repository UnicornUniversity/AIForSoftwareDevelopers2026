import { Router } from 'express';

import { badRequest, parseAt } from '../lib/params.js';
import { runChase } from '../services/chase.js';

export const chaseRouter = Router();

/**
 * The composed payload the frontend renders.
 *
 * `no-store` because the whole point is that it tracks the moving terminator,
 * and the upstream image tokens inside it expire in about ten minutes - a
 * cached copy would hand out dead URLs.
 */
chaseRouter.get('/', async (req, res, next) => {
  const { date, error } = parseAt(req.query.at);
  if (error) return badRequest(res, error);

  try {
    // `chaseOptions` is set by `createApp` and is empty in production. It lets a
    // test drive the real HTTP stack without reaching the live upstreams.
    const payload = await runChase({ at: date, ...req.app.locals.chaseOptions });
    res.set('Cache-Control', 'no-store');
    res.json(payload);
  } catch (err) {
    next(err);
  }
});
