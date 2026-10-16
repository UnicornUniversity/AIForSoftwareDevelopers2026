import test from 'node:test';
import assert from 'node:assert/strict';

import { collectFallback } from '../src/services/fallback.js';
import { subsolarPoint, sunEquatorial } from '../src/services/solar.js';

const AT = new Date('2026-10-16T17:00:00Z');
const sunEq = sunEquatorial(AT);
const subsolar = subsolarPoint(AT, sunEq);

/**
 * A stub Windy where every city returns cameras named after its own districts,
 * the way Windy actually reports a metropolis.
 *
 * The district names matter: they are what defeated `selectPrimary`'s dedupe,
 * since Chiyoda and Shinjuku are different strings but the same city. They are
 * also namespaced per queried city here, because real districts are - Tokyo's
 * Chiyoda and Shanghai's Pudong do not share a name, and a stub that reused them
 * made unrelated cities look like one skyline.
 *
 * `counts` gives a per-call result count, so a sweep can be made to run dry.
 */
function stubWindy({ count = 6, counts = null } = {}) {
  const calls = [];
  return {
    calls,
    async nearby({ lat, lon }) {
      const call = calls.length;
      calls.push({ lat, lon });

      const n = counts ? (counts[call] ?? 0) : count;
      const district = `${Math.round(lat)}N${Math.round(lon)}E`;

      return {
        webcams: Array.from({ length: n }, (_, i) => ({
          webcamId: `${district}-${i}`,
          status: 'active',
          title: `Camera ${i}`,
          city: `${district} District ${i}`,
          country: 'Testland',
          countryCode: 'TL',
          latitude: lat + i * 0.001,
          longitude: lon + i * 0.001,
          imagePreviewUrl: `https://img.test/${district}-${i}.jpg`,
          viewCount: 100 + i,
        })),
      };
    },
  };
}

test('the fallback returns cameras at all, not an empty list', async () => {
  // The bug this guards: the fallback applies `passesFilters`, which required
  // |sunAltitude| <= 15. Big cities are selected *for* standing in daylight, so
  // the filter discarded every camera the fallback had just fetched and
  // `fallbackCount` was structurally zero however well Windy responded.
  const client = stubWindy({ count: 4 });
  const result = await collectFallback({ date: AT, sunEq, subsolar, client });

  assert.ok(result.cameras.length > 0, 'the fallback must be able to return cameras');
  assert.equal(result.candidatesConsidered > 0, true);
  for (const camera of result.cameras) {
    assert.equal(camera.source, 'fallback');
    assert.ok(camera.sunAltitudeDeg > 0, 'fallback cameras stand in daylight by construction');
    assert.ok(camera.score > 0);
  }
});

test('the fallback spreads across cities instead of returning one skyline', async () => {
  // Live, this was six Tokyo wards: Chiyoda, Shinjuku, Shibuya, Ota, Suginami,
  // Itabashi. Every one a different city string, so the per-city dedupe never
  // fired and the "big cities" list was one skyline six times.
  const client = stubWindy({ count: 10 });
  const result = await collectFallback({ date: AT, sunEq, subsolar, client });

  const distinctCities = new Set(result.cameras.map((c) => c.fallbackCity));
  assert.ok(
    distinctCities.size >= 3,
    `expected a spread across cities, got ${[...distinctCities].join(', ')}`,
  );

  const perCity = new Map();
  for (const camera of result.cameras) {
    perCity.set(camera.fallbackCity, (perCity.get(camera.fallbackCity) ?? 0) + 1);
  }
  for (const [city, count] of perCity) {
    assert.ok(count <= 2, `${city} contributed ${count} cameras, above the per-city cap`);
  }

  // And the sweep must have queried more than one city to get there.
  assert.ok(result.citiesTried.length >= 3, `only tried ${result.citiesTried.join(', ')}`);
});

test('topping up a short list prefers a new skyline over repeating one', async () => {
  // Only the first city answers, so the per-city cap of 2 leaves the list well
  // short of 6. Live, the top-up then refilled from whichever city dominated -
  // two Chiyodas and two Shinjukus in a six-card gallery. It must exhaust unseen
  // skylines before repeating one.
  const client = stubWindy({ counts: [10, 0, 0, 0, 0] });
  const result = await collectFallback({ date: AT, sunEq, subsolar, client, want: 6 });

  const skylineCounts = new Map();
  for (const camera of result.cameras) {
    skylineCounts.set(camera.city, (skylineCounts.get(camera.city) ?? 0) + 1);
  }

  assert.equal(result.cameras.length, 6, 'a short list is still topped up to the promised size');
  assert.equal(
    skylineCounts.size,
    6,
    `expected six distinct skylines, got ${[...skylineCounts].map(([c, n]) => `${c}x${n}`).join(', ')}`,
  );
});

test('the fallback still respects its hard call budget', async () => {
  const client = stubWindy({ count: 2 });
  const result = await collectFallback({ date: AT, sunEq, subsolar, client, maxCities: 4 });

  assert.ok(
    client.calls.length <= 4,
    `spending ${client.calls.length} calls against a budget of 4`,
  );
  assert.equal(result.citiesTried.length, client.calls.length, 'one call per city tried');
});

test('a city with no cameras does not stop the sweep', async () => {
  // Over open ocean or in a country Windy covers thinly, a big city can return
  // nothing. That must not end the walk.
  let call = 0;
  const client = {
    async nearby({ lat, lon }) {
      call += 1;
      if (call === 1) return { webcams: [] };
      return {
        webcams: [
          {
            webcamId: `later-${call}`,
            status: 'active',
            title: 'Camera',
            city: 'Somewhere',
            country: 'Testland',
            countryCode: 'TL',
            latitude: lat,
            longitude: lon,
            imagePreviewUrl: 'https://img.test/later.jpg',
            viewCount: 50,
          },
        ],
      };
    },
  };

  const result = await collectFallback({ date: AT, sunEq, subsolar, client });
  assert.ok(result.cameras.length > 0, 'the sweep must continue past an empty city');
  assert.ok(call > 1, 'the second city must actually have been queried');
});

test('cities in daylight are all genuinely sunlit and ordered by population', async () => {
  const { citiesInDaylight } = await import('../src/services/fallback.js');
  const daylight = citiesInDaylight(AT, sunEq);

  assert.ok(daylight.length > 0);
  for (const city of daylight) {
    assert.ok(city.sunAltitudeDeg > 0, `${city.name} is not in daylight`);
  }
  for (let i = 1; i < daylight.length; i += 1) {
    assert.ok(daylight[i - 1].population >= daylight[i].population, 'most populous first');
  }
});
