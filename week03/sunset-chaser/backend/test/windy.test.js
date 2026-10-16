import test from 'node:test';
import assert from 'node:assert/strict';

import { UpstreamError } from '../src/http.js';
import { createWindyClient, normalizeWebcam, windyPageUrl } from '../src/services/windy.js';

/** A realistic v3 webcam, shaped like the live response. */
function rawWebcam(overrides = {}) {
  return {
    webcamId: 1234567890,
    status: 'active',
    title: 'Praça do Comércio',
    viewCount: 12345,
    lastUpdatedOn: '2026-10-16T16:52:00.000Z',
    categories: [{ id: 'city' }, { id: 'square' }],
    images: {
      current: {
        preview: 'https://imgproxy.windy.com/preview?token=abc',
        thumbnail: 'https://imgproxy.windy.com/thumb?token=abc',
        icon: 'https://imgproxy.windy.com/icon?token=abc',
      },
    },
    location: {
      city: 'Lisbon',
      region: 'Lisboa',
      country: 'Portugal',
      country_code: 'PT',
      latitude: 38.7071,
      longitude: -9.1365,
    },
    player: { day: 'https://cdn.windy.com/player/day.m3u8' },
    urls: { current: { desktop: 'https://www.windy.com/webcams/1234567890' } },
    ...overrides,
  };
}

const testConfig = (overrides = {}) => ({
  windy: {
    apiKey: 'test-key',
    baseUrl: 'https://api.windy.com/webcams/api/v3',
    radiusKm: 250,
    limit: 50,
    sampleCount: 20,
    candidateTarget: 40,
    timeoutMs: 1000,
    concurrency: 4,
    ...overrides,
  },
});

test('normalizeWebcam flattens the v3 shape into what the app uses', () => {
  const cam = normalizeWebcam(rawWebcam(), { fetchedAt: Date.UTC(2026, 9, 16, 17, 0, 0) });

  assert.equal(cam.webcamId, '1234567890', 'ids are stringified - Windy ids are opaque');
  assert.equal(cam.city, 'Lisbon');
  assert.equal(cam.countryCode, 'PT');
  assert.equal(cam.latitude, 38.7071);
  assert.equal(cam.longitude, -9.1365);
  assert.equal(cam.imagePreviewUrl, 'https://imgproxy.windy.com/preview?token=abc');
  assert.deepEqual(cam.categories, ['city', 'square']);
  assert.equal(cam.lastUpdatedOn, '2026-10-16T16:52:00.000Z');
  // Free-tier terms require a link back to windy.com, so this is always present.
  assert.equal(cam.windyPageUrl, windyPageUrl('1234567890'));
});

test('normalizeWebcam treats Windy\'s literal "unknown" as absent', () => {
  // Windy sends the string "unknown" where it has no value. Passing it through
  // printed "unknown" as a city on the card and scored the camera as though it
  // had a real city name, which is worth 5% of the total.
  const cam = normalizeWebcam(
    rawWebcam({
      location: {
        city: 'unknown',
        region: 'Unknown',
        country: 'unknown',
        country_code: 'unknown',
        latitude: 38.7071,
        longitude: -9.1365,
      },
    }),
  );

  assert.equal(cam.city, null);
  assert.equal(cam.region, null);
  assert.equal(cam.country, null);
  assert.equal(cam.countryCode, null);
  // Whitespace-only is the same nothing.
  assert.equal(normalizeWebcam(rawWebcam({ location: { city: '   ', latitude: 1, longitude: 2 } })).city, null);
  // A real name is untouched.
  assert.equal(normalizeWebcam(rawWebcam({ location: { city: 'Unknownville', latitude: 1, longitude: 2 } })).city, 'Unknownville');
});

test('normalizeWebcam rejects cameras it cannot place or show', () => {
  assert.equal(normalizeWebcam(null), null);
  assert.equal(normalizeWebcam({}), null, 'no webcamId');
  assert.equal(normalizeWebcam(rawWebcam({ images: { current: {} } })), null, 'no preview image');
  assert.equal(
    normalizeWebcam(rawWebcam({ location: { latitude: 'north', longitude: 1 } })),
    null,
    'unparseable latitude',
  );
  assert.equal(
    normalizeWebcam(rawWebcam({ location: { latitude: 91, longitude: 0 } })),
    null,
    'latitude out of range',
  );
});

test('normalizeWebcam clamps longitude into range before it can reach the wire', () => {
  // Windy should never return 185, but a query built from an unclamped value
  // would be rejected upstream, so the clamp is enforced at ingest.
  const cam = normalizeWebcam(rawWebcam({ location: { latitude: 0, longitude: 185 } }));
  assert.equal(cam.longitude, -175);
});

test('buildUrl clamps an out-of-range sample point rather than passing it on', () => {
  const client = createWindyClient({ config: testConfig() });
  const url = new URL(client.buildUrl({ lat: 95, lon: 185, radiusKm: 250, limit: 50 }));
  assert.equal(url.searchParams.get('nearby'), '90,-175,250');
});

test('buildUrl omits offset on the first page and sets it on the second', () => {
  const client = createWindyClient({ config: testConfig() });
  const first = new URL(client.buildUrl({ lat: 0, lon: 0, radiusKm: 250, limit: 50, offset: 0 }));
  const second = new URL(client.buildUrl({ lat: 0, lon: 0, radiusKm: 250, limit: 50, offset: 50 }));
  assert.equal(first.searchParams.get('offset'), null);
  assert.equal(second.searchParams.get('offset'), '50');
  assert.equal(first.searchParams.get('include'), 'images,location,player,urls,categories');
});

test('nearby sends the api key as a header, never in the url', async () => {
  const seen = [];
  const client = createWindyClient({
    config: testConfig(),
    fetchJson: async (url, options) => {
      seen.push({ url, options });
      return { total: 1, webcams: [rawWebcam()] };
    },
  });

  const result = await client.nearby({ lat: 38.7, lon: -9.1 });

  assert.equal(seen.length, 1);
  assert.equal(seen[0].options.headers['x-windy-api-key'], 'test-key');
  assert.ok(!seen[0].url.includes('test-key'), 'the key must not appear in the url');
  assert.equal(result.webcams.length, 1);
  assert.equal(client.stats.callsMade, 1);
});

test('nearby returns an empty page instead of throwing when upstream fails', async () => {
  const client = createWindyClient({
    config: testConfig(),
    fetchJson: async () => {
      throw new UpstreamError('429', { status: 429, code: 'rate_limited', retryable: true });
    },
  });

  const result = await client.nearby({ lat: 0, lon: 0 });

  assert.deepEqual(result.webcams, []);
  assert.equal(result.error, 'rate_limited');
  assert.equal(client.stats.callsFailed, 1);
  assert.equal(client.stats.rateLimited, true);
});

test('a rejected key flips authOk and is never retried as a transient fault', async () => {
  const client = createWindyClient({
    config: testConfig(),
    fetchJson: async () => {
      throw new UpstreamError('403', { status: 403, code: 'auth_failed', retryable: false });
    },
  });

  await client.nearby({ lat: 0, lon: 0 });
  assert.equal(client.stats.authOk, false);
});

test('with no key configured, no request is made at all', async () => {
  let calls = 0;
  const client = createWindyClient({
    config: testConfig({ apiKey: '' }),
    fetchJson: async () => {
      calls += 1;
      return { webcams: [] };
    },
  });

  const result = await client.nearby({ lat: 0, lon: 0 });
  assert.equal(calls, 0, 'must not spend a call it knows will fail');
  assert.equal(result.error, 'no_key');
  assert.equal(client.stats.authOk, false);
});

test('collect dedupes the same camera returned by overlapping sample points', async () => {
  // Two sample points 100 km apart both return the same city camera. It is one
  // camera, and it must appear once.
  const shared = rawWebcam();
  const client = createWindyClient({
    config: testConfig(),
    fetchJson: async () => ({ total: 2, webcams: [shared, rawWebcam({ webcamId: 999 })] }),
  });

  const result = await client.collect([{ lat: 0, lon: 0 }, { lat: 0.5, lon: 0.5 }], {
    adaptivePages: 0,
  });

  assert.equal(result.rawCount, 4, 'four results came back across two points');
  assert.equal(result.webcams.length, 2, 'but only two distinct cameras exist');
});

test('collect spends one adaptive page per saturated point, and no more', async () => {
  const offsets = [];
  const client = createWindyClient({
    config: testConfig({ limit: 2 }),
    fetchJson: async (url) => {
      const offset = new URL(url).searchParams.get('offset') ?? '0';
      offsets.push(offset);
      // Always return exactly `limit` results, so every point looks saturated.
      return { total: 500, webcams: [rawWebcam({ webcamId: Math.random() }), rawWebcam({ webcamId: Math.random() })] };
    },
  });

  const points = [{ lat: 0, lon: 0 }, { lat: 1, lon: 1 }, { lat: 2, lon: 2 }, { lat: 3, lon: 3 }, { lat: 4, lon: 4 }];
  await client.collect(points, { limit: 2, adaptivePages: 2 });

  const secondPages = offsets.filter((o) => o === '2');
  assert.equal(secondPages.length, 2, 'adaptive paging is capped at adaptivePages');
  assert.equal(client.stats.saturatedPoints, 5);
  assert.equal(client.stats.adaptivePages, 2);
  assert.equal(client.stats.callsMade, 7, '5 first pages plus 2 adaptive pages');
});

test('collect does not page adaptively when no point is saturated', async () => {
  const client = createWindyClient({
    config: testConfig(),
    fetchJson: async () => ({ total: 3, webcams: [rawWebcam()] }),
  });

  await client.collect([{ lat: 0, lon: 0 }, { lat: 1, lon: 1 }], { adaptivePages: 3 });
  assert.equal(client.stats.adaptivePages, 0);
  assert.equal(client.stats.callsMade, 2);
});

test('collect respects the concurrency limit', async () => {
  let active = 0;
  let peak = 0;
  const client = createWindyClient({
    config: testConfig({ concurrency: 2 }),
    fetchJson: async () => {
      active += 1;
      peak = Math.max(peak, active);
      await new Promise((resolve) => setTimeout(resolve, 5));
      active -= 1;
      return { webcams: [] };
    },
  });

  await client.collect(Array.from({ length: 8 }, (_, i) => ({ lat: i, lon: i })), {
    concurrency: 2,
    adaptivePages: 0,
  });

  assert.ok(peak <= 2, `peak concurrency ${peak} exceeded the limit of 2`);
});

test('byIds fetches one camera for the per-camera token refresh', async () => {
  const urls = [];
  const client = createWindyClient({
    config: testConfig(),
    fetchJson: async (url) => {
      urls.push(url);
      return { webcams: [rawWebcam()] };
    },
  });

  const result = await client.byIds(['1234567890']);

  assert.equal(result.webcams.length, 1);
  assert.equal(new URL(urls[0]).searchParams.get('webcamIds'), '1234567890');
});
