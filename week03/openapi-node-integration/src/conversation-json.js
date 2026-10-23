/**
 * Machine-readable target for the same conversation: runs the five Paris
 * landmark questions and prints one JSON document to stdout.
 *
 *   npm run conversation:json
 *   npm run conversation:json > landmark-report.json
 *
 * Shares `run()` with the text demo, so both targets ask the same questions in
 * the same order. Answers still contain the coordinates as prose; `coordinates`
 * is the parsed copy, and it is null whenever the model's wording cannot be
 * parsed unambiguously.
 */
import { pathToFileURL } from 'node:url';

import { run } from './conversation.js';

/**
 * The shapes the model actually produces, most explicit first. The prompt asks
 * for the first one, but a small model drifts, and these five answers have been
 * seen in all three forms across runs.
 */
const COORDINATE_PATTERNS = [
  // Coordinates: 48.8584, 2.2945   (the requested final line)
  /coordinates?\s*[:=]?\s*(-?\d+(?:\.\d+)?)\s*°?\s*([NS])?\s*[,;]?\s*(-?\d+(?:\.\d+)?)\s*°?\s*([EW])?/i,
  // latitude 48.8584, longitude 2.2945
  /lat(?:itude)?\s*[:=]?\s*(-?\d+(?:\.\d+)?)\s*°?\s*([NS])?[^\d-]*lon(?:gitude)?\s*[:=]?\s*(-?\d+(?:\.\d+)?)\s*°?\s*([EW])?/i,
  // 48.8584° N, 2.2945° E
  /(-?\d+(?:\.\d+)?)\s*°\s*([NS])\s*,?\s*(-?\d+(?:\.\d+)?)\s*°\s*([EW])/i,
];

/**
 * Extract the first lat/lon pair from a prose answer. Model output is
 * untrusted, so anything that does not parse into an in-range pair is dropped
 * instead of guessed at.
 */
function parseCoordinates(answer) {
  for (const pattern of COORDINATE_PATTERNS) {
    const match = pattern.exec(answer);
    if (!match) continue;

    const [, latText, latHemisphere, lonText, lonHemisphere] = match;

    let latitude = Number(latText);
    let longitude = Number(lonText);

    if (latHemisphere?.toUpperCase() === 'S') latitude = -latitude;
    if (lonHemisphere?.toUpperCase() === 'W') longitude = -longitude;

    const inRange =
      Number.isFinite(latitude) &&
      Number.isFinite(longitude) &&
      Math.abs(latitude) <= 90 &&
      Math.abs(longitude) <= 180;

    if (inRange) return { latitude, longitude };
  }

  return null;
}

/** Run the conversation and build the report. No output of its own. */
export async function buildReport() {
  const startedAt = Date.now();
  const { turns, messages } = await run();
  const wallMs = Date.now() - startedAt;

  const usage = turns.reduce(
    (sum, turn) => ({
      promptTokens: sum.promptTokens + (turn.usage?.prompt_tokens ?? 0),
      completionTokens: sum.completionTokens + (turn.usage?.completion_tokens ?? 0),
      totalTokens: sum.totalTokens + (turn.usage?.total_tokens ?? 0),
      modelMs: sum.modelMs + turn.elapsedMs,
    }),
    { promptTokens: 0, completionTokens: 0, totalTokens: 0, modelMs: 0 },
  );

  return {
    generatedAt: new Date().toISOString(),
    model: turns[0]?.model ?? null,
    totals: { turns: turns.length, ...usage, wallMs },
    landmarks: turns.map((turn) => ({
      turn: turn.turn,
      question: turn.question,
      description: turn.answer,
      coordinates: parseCoordinates(turn.answer),
      model: turn.model,
      finishReason: turn.finishReason,
      usage: turn.usage,
      elapsedMs: turn.elapsedMs,
    })),
    messages,
  };
}

const isMain =
  process.argv[1] !== undefined && import.meta.url === pathToFileURL(process.argv[1]).href;

if (isMain) {
  console.log(JSON.stringify(await buildReport(), null, 2));
}
