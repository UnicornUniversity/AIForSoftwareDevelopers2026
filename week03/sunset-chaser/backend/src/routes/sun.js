import { Router } from 'express';

import { config } from '../config.js';
import { round } from '../lib/geo.js';
import { badRequest, parseAt } from '../lib/params.js';
import { subsolarPoint, sunEquatorial, terminatorArcs } from '../services/solar.js';
import { sampleTerminator } from '../services/sampler.js';

export const sunRouter = Router();

/**
 * The terminator, with no upstream dependency at all.
 *
 * Pure ephemeris plus closed-form geometry, so this answers in single-digit
 * milliseconds and is always 200. It is also what the map falls back to when
 * Windy is unreachable, which is why `samplePoints` is included even though this
 * route queries nothing.
 */
sunRouter.get('/terminator', (req, res) => {
  const { date, error } = parseAt(req.query.at);
  if (error) return badRequest(res, error);

  const sunEq = sunEquatorial(date);
  const subsolar = subsolarPoint(date, sunEq);
  const terminator = terminatorArcs(subsolar);

  res.json({
    generatedAt: new Date().toISOString(),
    at: date.toISOString(),
    sun: {
      declinationDeg: round(subsolar.declinationDeg, 3),
      subsolarLatDeg: round(subsolar.subsolarLatDeg, 3),
      subsolarLonDeg: round(subsolar.subsolarLonDeg, 3),
      equationOfTimeMin: subsolar.equationOfTimeMin,
      utcHour: round(subsolar.utcHour, 3),
      sunsetTerminatorSpanDeg: round(subsolar.spanDeg, 3),
      polarDayNorth: subsolar.polarDayNorth,
      polarDaySouth: subsolar.polarDaySouth,
    },
    terminator: {
      sunset: terminator.sunset,
      sunrise: terminator.sunrise,
      samplePoints: sampleTerminator(subsolar, config.windy.sampleCount),
    },
  });
});
