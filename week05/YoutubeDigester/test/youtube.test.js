import assert from 'node:assert/strict';
import { test } from 'node:test';

import { YouTubeError, createYouTubeClient, parseIsoDuration } from '../src/youtube.js';
import { fakeJsonResponse, recordingFetch, vid } from './helpers.js';

function client(fetchImpl, options = {}) {
  const sleeps = [];
  return {
    sleeps,
    youtube: createYouTubeClient({
      apiKey: 'SECRET-KEY',
      fetchImpl,
      timeoutMs: 50,
      retries: 1,
      sleep: async (ms) => { sleeps.push(ms); },
      warn: () => {},
      ...options,
    }),
  };
}

test('parseIsoDuration handles hours, minutes, seconds and fractions', () => {
  assert.equal(parseIsoDuration('PT1H2M3S'), 3_723);
  assert.equal(parseIsoDuration('PT45S'), 45);
  assert.equal(parseIsoDuration('P1DT1S'), 86_401);
  assert.equal(parseIsoDuration('PT0.5S'), 1);
  assert.equal(parseIsoDuration('PT'), 0);
  assert.equal(parseIsoDuration('P'), 0);
  assert.equal(parseIsoDuration('bogus'), 0);
  assert.equal(parseIsoDuration(undefined), 0);
});

test('a missing key fails before any request', async () => {
  const { fetchImpl, requests } = recordingFetch([]);
  const youtube = createYouTubeClient({ apiKey: '', fetchImpl });
  await assert.rejects(() => youtube.getVideos([vid(1)]), (err) => {
    assert.ok(err instanceof YouTubeError);
    assert.equal(err.code, 'youtube_no_key');
    return true;
  });
  assert.equal(requests.length, 0);
  assert.equal(youtube.hasKey(), false);
});

test('getVideos sends the key as a query parameter and chunks ids by 50', async () => {
  const { fetchImpl, requests } = recordingFetch([
    fakeJsonResponse({ items: [] }),
    fakeJsonResponse({ items: [] }),
  ]);
  const { youtube } = client(fetchImpl);

  const ids = Array.from({ length: 60 }, (_, index) => vid(index + 1));
  await youtube.getVideos(ids);

  assert.equal(requests.length, 2);
  const first = new URL(requests[0].url);
  assert.equal(first.searchParams.get('key'), 'SECRET-KEY');
  assert.equal(first.searchParams.get('part'), 'snippet,contentDetails');
  assert.equal(first.searchParams.get('id').split(',').length, 50);
  const second = new URL(requests[1].url);
  assert.equal(second.searchParams.get('id').split(',').length, 10);
  assert.equal(youtube.quota().units, 2);
  assert.equal(youtube.calls(), 2);
});

test('getVideos maps snippets and ISO durations', async () => {
  const { fetchImpl } = recordingFetch([fakeJsonResponse({
    items: [{
      id: vid(1),
      snippet: {
        title: 'Lecture 1',
        channelTitle: 'CS50',
        channelId: 'UC123',
        publishedAt: '2025-01-01T00:00:00Z',
      },
      contentDetails: { duration: 'PT1H2M3S' },
    }, { id: 'bad' }],
  })]);
  const { youtube } = client(fetchImpl);

  assert.deepEqual(await youtube.getVideos([vid(1)]), [{
    videoId: vid(1),
    title: 'Lecture 1',
    channel: 'CS50',
    channelId: 'UC123',
    publishedAt: '2025-01-01T00:00:00Z',
    durationSeconds: 3_723,
  }]);
});

test('listPlaylistItems paginates and stops at the cap', async () => {
  const pageOne = {
    items: [
      { contentDetails: { videoId: vid(1) }, snippet: { title: 'One', position: 0, videoOwnerChannelTitle: 'CS50', videoOwnerChannelId: 'UC123' } },
      { contentDetails: { videoId: vid(2) }, snippet: { title: 'Two', position: 1 } },
    ],
    nextPageToken: 'page-2',
  };
  const pageTwo = {
    items: [
      { contentDetails: { videoId: vid(3) }, snippet: { title: 'Three', position: 2 } },
      { contentDetails: { videoId: 'deleted' }, snippet: { title: 'Gone' } },
    ],
  };
  const { fetchImpl, requests } = recordingFetch([
    fakeJsonResponse(pageOne),
    fakeJsonResponse(pageTwo),
  ]);
  const { youtube } = client(fetchImpl);

  const items = await youtube.listPlaylistItems('PL1234567890abcdef', { max: 10 });
  assert.deepEqual(items.map((item) => item.videoId), [vid(1), vid(2), vid(3)]);
  assert.equal(items[0].channel, 'CS50');
  assert.equal(requests.length, 2);
  assert.equal(new URL(requests[1].url).searchParams.get('pageToken'), 'page-2');

  const { fetchImpl: cappedFetch, requests: cappedRequests } = recordingFetch([fakeJsonResponse(pageOne)]);
  const { youtube: capped } = client(cappedFetch);
  const cappedItems = await capped.listPlaylistItems('PL1234567890abcdef', { max: 2 });
  assert.equal(cappedItems.length, 2);
  assert.equal(cappedRequests.length, 1);
  assert.equal(new URL(cappedRequests[0].url).searchParams.get('maxResults'), '2');
});

test('getPlaylist returns channel metadata and maps a 404', async () => {
  const { fetchImpl } = recordingFetch([fakeJsonResponse({
    items: [{
      id: 'PL1234567890abcdef',
      snippet: { title: 'CS50', channelId: 'UC123', channelTitle: 'Harvard' },
      contentDetails: { itemCount: 25 },
    }],
  })]);
  const { youtube } = client(fetchImpl);
  const playlist = await youtube.getPlaylist('PL1234567890abcdef');
  assert.deepEqual(playlist, {
    playlistId: 'PL1234567890abcdef',
    title: 'CS50',
    channelId: 'UC123',
    channelTitle: 'Harvard',
    publishedAt: null,
    itemCount: 25,
  });

  const { fetchImpl: missingFetch } = recordingFetch([fakeJsonResponse({ items: [] })]);
  const { youtube: missing } = client(missingFetch);
  await assert.rejects(() => missing.getPlaylist('PL1234567890abcdef'), (err) => err.code === 'youtube_404');
});

test('search pages cost 100 units each and respect the page cap', async () => {
  const { fetchImpl, requests } = recordingFetch([
    fakeJsonResponse({
      items: [{ id: { videoId: vid(1) }, snippet: { title: 'One', channelId: 'UC123' } }],
      nextPageToken: 'next',
    }),
    fakeJsonResponse({
      items: [{ id: { videoId: vid(2) }, snippet: { title: 'Two', channelId: 'UC123' } }],
    }),
  ]);
  const { youtube } = client(fetchImpl);

  const results = await youtube.searchChannelVideos({
    channelId: 'UC123',
    query: 'CS50',
    max: 50,
    pages: 2,
  });
  assert.deepEqual(results.map((result) => result.videoId), [vid(1), vid(2)]);
  assert.equal(requests.length, 2);
  assert.equal(youtube.quota().units, 200);
  assert.equal(new URL(requests[0].url).searchParams.get('type'), 'video');
});

test('searchChannelPlaylists keeps only valid playlist ids', async () => {
  const { fetchImpl } = recordingFetch([fakeJsonResponse({
    items: [
      { id: { playlistId: 'PL1234567890abcdef' }, snippet: { title: 'Course', channelId: 'UC123' } },
      { id: { videoId: vid(1) }, snippet: { title: 'Not a playlist' } },
    ],
  })]);
  const { youtube } = client(fetchImpl);
  const playlists = await youtube.searchChannelPlaylists({ channelId: 'UC123', query: 'Course' });
  assert.equal(playlists.length, 1);
  assert.equal(playlists[0].playlistId, 'PL1234567890abcdef');
});

test('429 and 5xx responses are retried once, then succeed', async () => {
  const { fetchImpl, requests } = recordingFetch([
    fakeJsonResponse({ error: { message: 'slow down' } }, 429),
    fakeJsonResponse({ items: [] }),
  ]);
  const { youtube, sleeps } = client(fetchImpl);

  await youtube.getVideos([vid(1)]);
  assert.equal(requests.length, 2);
  assert.equal(sleeps.length, 1);
  assert.ok(sleeps[0] >= 250);

  const { fetchImpl: fiveHundred, requests: serverRequests } = recordingFetch([
    fakeJsonResponse({}, 503),
    fakeJsonResponse({ items: [] }),
  ]);
  const { youtube: retrying } = client(fiveHundred);
  await retrying.getVideos([vid(1)]);
  assert.equal(serverRequests.length, 2);
});

test('quota exhaustion, rate limits and not-found map to typed errors', async () => {
  const quotaPayload = {
    error: { message: 'quota', errors: [{ reason: 'quotaExceeded' }] },
  };
  const { fetchImpl } = recordingFetch([fakeJsonResponse(quotaPayload, 403)]);
  const { youtube } = client(fetchImpl);
  await assert.rejects(() => youtube.getVideos([vid(1)]), (err) => err.code === 'youtube_quota');

  const ratePayload = { error: { errors: [{ reason: 'rateLimitExceeded' }] } };
  const { fetchImpl: rateFetch, requests } = recordingFetch([
    fakeJsonResponse(ratePayload, 403),
    fakeJsonResponse(ratePayload, 403),
  ]);
  const { youtube: rateLimited } = client(rateFetch);
  await assert.rejects(() => rateLimited.getVideos([vid(1)]), (err) => {
    assert.equal(err.code, 'youtube_rate_limited');
    assert.equal(err.message.includes('SECRET-KEY'), false);
    return true;
  });
  assert.equal(requests.length, 2);
});

test('timeouts and network failures are typed and never leak the key', async () => {
  const timeout = new DOMException('timed out', 'TimeoutError');
  const { fetchImpl, requests } = recordingFetch([async () => { throw timeout; }, async () => { throw timeout; }]);
  const { youtube } = client(fetchImpl);
  await assert.rejects(() => youtube.getVideos([vid(1)]), (err) => {
    assert.equal(err.code, 'youtube_timeout');
    assert.equal(String(err.message).includes('SECRET-KEY'), false);
    return true;
  });
  assert.equal(requests.length, 2);

  const { fetchImpl: brokenFetch } = recordingFetch([
    async () => { throw new TypeError('network down'); },
    async () => { throw new TypeError('network down'); },
  ]);
  const { youtube: broken } = client(brokenFetch);
  await assert.rejects(() => broken.getVideos([vid(1)]), (err) => err.code === 'youtube_failed');
});

test('identical calls share a cached response until the cache expires', async () => {
  const { fetchImpl, requests } = recordingFetch([fakeJsonResponse({ items: [] })]);
  const { youtube } = client(fetchImpl);
  await youtube.getVideos([vid(1)]);
  await youtube.getVideos([vid(1)]);
  assert.equal(requests.length, 1);

  const { fetchImpl: noCacheFetch, requests: noCacheRequests } = recordingFetch([
    fakeJsonResponse({ items: [] }),
    fakeJsonResponse({ items: [] }),
  ]);
  const { youtube: noCache } = client(noCacheFetch, {
    cache: { async run(_key, fn) { return { value: await fn(), cached: false }; } },
  });
  await noCache.getVideos([vid(1)]);
  await noCache.getVideos([vid(1)]);
  assert.equal(noCacheRequests.length, 2);
});
