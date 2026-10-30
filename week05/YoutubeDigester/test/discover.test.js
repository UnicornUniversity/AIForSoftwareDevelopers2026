import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  courseKeyTokens,
  deriveCourseTitle,
  discoverCourse,
  pickPlaylist,
  titleMatchScore,
} from '../src/discover.js';
import { parseSeedUrl } from '../src/store.js';
import { vid } from './helpers.js';

const VIDEO_SEED = parseSeedUrl('https://www.youtube.com/watch?v=dQw4w9WgXcQ');
const PLAYLIST = 'PL1234567890abcdef';
const PLAYLIST_SEED = parseSeedUrl(`https://www.youtube.com/playlist?list=${PLAYLIST}`);

function seedVideo(overrides = {}) {
  return {
    videoId: VIDEO_SEED.videoId,
    title: 'CS50 Lecture 5 – Memory',
    channel: 'Harvard CS50',
    channelId: 'UC123',
    publishedAt: '2025-01-05T00:00:00Z',
    durationSeconds: 3_000,
    ...overrides,
  };
}

function playlistMeta(title = 'CS50 2025', overrides = {}) {
  return {
    playlistId: PLAYLIST,
    title,
    channelId: 'UC123',
    channelTitle: 'Harvard CS50',
    publishedAt: '2025-01-01T00:00:00Z',
    itemCount: 3,
    ...overrides,
  };
}

function playlistItems(ids = [1, 2, 3]) {
  return ids.map((number) => ({
    videoId: vid(number),
    title: `CS50 Lecture ${number}`,
    channel: 'Harvard CS50',
    channelId: 'UC123',
    publishedAt: `2025-01-0${number}T00:00:00Z`,
    position: number - 1,
  }));
}

test('deriveCourseTitle strips lecture markers and bracketed noise', () => {
  assert.equal(deriveCourseTitle('CS50 Lecture 1 – Introduction [HD]'), 'CS50 – Introduction');
  assert.equal(deriveCourseTitle('S01E02 – Variables'), 'Variables');
  assert.equal(deriveCourseTitle('Python #12 Lists'), 'Python Lists');
  assert.equal(deriveCourseTitle('Lesson 3: Functions'), 'Functions');
  assert.equal(deriveCourseTitle('Full Course 1/10'), 'Full Course');
  assert.equal(deriveCourseTitle(''), '');
  assert.equal(deriveCourseTitle('Just a title'), 'Just a title');
});

test('courseKeyTokens drops generic words and punctuation', () => {
  assert.deepEqual(courseKeyTokens('CS50 2025 – Full Course'), ['cs50', '2025']);
  assert.deepEqual(courseKeyTokens('Introduction to Python'), ['python']);
  assert.deepEqual(courseKeyTokens('The Complete Beginner Guide'), []);
  assert.deepEqual(courseKeyTokens('Café & Crème'), ['cafe', 'creme']);
});

test('titleMatchScore rewards shared course keys and exact titles', () => {
  assert.equal(titleMatchScore('CS50 2025', 'CS50 Full Course 2025'), 1);
  assert.ok(titleMatchScore('Introduction to Python', 'Python Basics') > 0);
  assert.equal(titleMatchScore('CS50', 'Cooking with Eggs'), 0);
  assert.equal(titleMatchScore('', 'anything'), 0);
});

test('pickPlaylist skips tiny playlists and respects the match threshold', () => {
  const playlists = [
    playlistMeta('Cooking with Eggs', { playlistId: 'PLcooking000000001' }),
    playlistMeta('CS50 2025 Full Course', { playlistId: 'PLmatch000000000001' }),
    playlistMeta('CS50', { playlistId: 'PLtiny0000000000001', itemCount: 1 }),
  ];
  const picked = pickPlaylist(playlists, { courseTitle: 'CS50 2025', minTitleMatch: 0.5 });
  assert.equal(picked.playlistId, 'PLmatch000000000001');
  assert.equal(pickPlaylist(playlists, { courseTitle: 'CS50', minTitleMatch: 1.1 }), null);
  assert.equal(pickPlaylist([], { courseTitle: 'CS50' }), null);
});

test('a playlist seed is read directly in playlist order', async () => {
  const client = {
    hasKey: () => true,
    getPlaylist: async () => playlistMeta(),
    listPlaylistItems: async () => playlistItems(),
  };
  const result = await discoverCourse({ seed: PLAYLIST_SEED, client, settings: { youtube: {} } });
  assert.equal(result.discovery, 'direct_playlist');
  assert.equal(result.courseTitle, 'CS50 2025');
  assert.equal(result.channelId, 'UC123');
  assert.deepEqual(result.videos.map((video) => video.videoId), [vid(1), vid(2), vid(3)]);
  assert.deepEqual(result.warnings, []);
});

test('a playlist hinted in the video URL wins over searching', async () => {
  const seed = parseSeedUrl(`https://www.youtube.com/watch?v=${VIDEO_SEED.videoId}&list=${PLAYLIST}`);
  const client = {
    hasKey: () => true,
    getVideos: async () => [seedVideo()],
    getPlaylist: async () => playlistMeta(),
    listPlaylistItems: async () => playlistItems([1, 2]),
  };
  const result = await discoverCourse({ seed, client, settings: { youtube: {} } });
  assert.equal(result.discovery, 'direct_playlist');
  assert.deepEqual(result.videos.map((video) => video.videoId), [VIDEO_SEED.videoId, vid(1), vid(2)]);
});

test('a matching channel playlist is chosen before a video search', async () => {
  const client = {
    hasKey: () => true,
    getVideos: async () => [seedVideo()],
    searchChannelPlaylists: async () => [
      playlistMeta('Unrelated Things', { playlistId: 'PLunrelated00000001' }),
      playlistMeta('CS50 2025 Full Course', { playlistId: 'PLmatch000000000001' }),
    ],
    getPlaylist: async (id) => playlistMeta('CS50 2025 Full Course', { playlistId: id }),
    listPlaylistItems: async () => playlistItems([1, 2, 3]),
  };
  const result = await discoverCourse({ seed: VIDEO_SEED, client, settings: { youtube: {} } });
  assert.equal(result.discovery, 'playlist_search');
  assert.equal(result.playlistId, 'PLmatch000000000001');
  assert.equal(result.videos.length, 4);
});

test('channel search keeps same-channel course videos and drops shorts and unrelated clips', async () => {
  const client = {
    hasKey: () => true,
    getVideos: async (ids) => {
      if (ids.length === 1 && ids[0] === VIDEO_SEED.videoId) return [seedVideo()];
      return [
        seedVideo({ videoId: vid(1), title: 'CS50 Lecture 1', durationSeconds: 3_000, publishedAt: '2025-01-01T00:00:00Z' }),
        seedVideo({ videoId: vid(2), title: 'CS50 Short', durationSeconds: 30, publishedAt: '2025-01-02T00:00:00Z' }),
        seedVideo({ videoId: vid(3), title: 'CS50 Teaser', durationSeconds: 60, publishedAt: '2025-01-03T00:00:00Z' }),
        seedVideo({ videoId: vid(4), title: 'Cooking with Eggs', durationSeconds: 3_000, publishedAt: '2025-01-04T00:00:00Z' }),
        seedVideo({ videoId: vid(5), title: 'CS50 Lecture 6', durationSeconds: 3_000, channelId: 'OTHER', publishedAt: '2025-01-06T00:00:00Z' }),
        seedVideo({ videoId: vid(6), title: 'CS50 Lecture 7', durationSeconds: 3_000, publishedAt: '2025-01-07T00:00:00Z' }),
      ];
    },
    searchChannelPlaylists: async () => [],
    searchChannelVideos: async () => [
      { videoId: vid(1) }, { videoId: vid(2) }, { videoId: vid(3) },
      { videoId: vid(4) }, { videoId: vid(5) }, { videoId: vid(6) },
      { videoId: VIDEO_SEED.videoId },
    ],
  };
  const result = await discoverCourse({ seed: VIDEO_SEED, client, settings: { youtube: {} } });
  assert.equal(result.discovery, 'channel_search');
  assert.deepEqual(result.videos.map((video) => video.videoId), [
    VIDEO_SEED.videoId,
    vid(1),
    vid(6),
  ]);
});

test('includeShorts and minDurationSeconds are configurable', async () => {
  const client = {
    hasKey: () => true,
    getVideos: async () => [seedVideo()],
    searchChannelPlaylists: async () => [],
    searchChannelVideos: async () => [{ videoId: vid(2) }],
  };
  const strict = await discoverCourse({
    seed: VIDEO_SEED,
    client: {
      ...client,
      getVideos: async (ids) => (ids.length === 1 && ids[0] === VIDEO_SEED.videoId
        ? [seedVideo()]
        : [seedVideo({ videoId: vid(2), title: 'CS50 Short', durationSeconds: 30 })]),
    },
    settings: { youtube: { includeShorts: true, minDurationSeconds: 0 } },
  });
  assert.equal(strict.videos.length, 2);
});

test('the seed is always kept when the cap trims the course', async () => {
  const client = {
    hasKey: () => true,
    getVideos: async () => [seedVideo()],
    searchChannelPlaylists: async () => [],
    searchChannelVideos: async () => [{ videoId: vid(1) }, { videoId: vid(2) }, { videoId: vid(3) }],
  };
  const clientWithMeta = {
    ...client,
    getVideos: async (ids) => {
      if (ids.length === 1 && ids[0] === VIDEO_SEED.videoId) return [seedVideo()];
      return [1, 2, 3].map((number) => seedVideo({
        videoId: vid(number),
        title: `CS50 Lecture ${number}`,
        publishedAt: `2025-01-0${number}T00:00:00Z`,
      }));
    },
  };
  const result = await discoverCourse({
    seed: VIDEO_SEED,
    client: clientWithMeta,
    settings: { youtube: { maxVideos: 2 } },
  });
  assert.equal(result.videos.length, 2);
  assert.equal(result.videos[0].videoId, VIDEO_SEED.videoId);
  assert.ok(result.warnings.some((warning) => /first 2 videos/.test(warning)));
});

test('without a YouTube key a video seed degrades to a single video', async () => {
  const client = { hasKey: () => false };
  const result = await discoverCourse({ seed: VIDEO_SEED, client, settings: { youtube: {} } });
  assert.equal(result.discovery, 'seed_only');
  assert.equal(result.videos.length, 1);
  assert.equal(result.videos[0].videoId, VIDEO_SEED.videoId);
  assert.ok(result.warnings.some((warning) => /only this video/.test(warning)));
});

test('without a key a playlist seed reports the limitation instead of inventing videos', async () => {
  const client = { hasKey: () => false };
  const result = await discoverCourse({ seed: PLAYLIST_SEED, client, settings: { youtube: {} } });
  assert.equal(result.videos.length, 0);
  assert.ok(result.warnings.some((warning) => /cannot be read/.test(warning)));
});

test('a failed playlist hint falls back to the channel search', async () => {
  const seed = parseSeedUrl(`https://www.youtube.com/watch?v=${VIDEO_SEED.videoId}&list=${PLAYLIST}`);
  const client = {
    hasKey: () => true,
    getVideos: async (ids) => (ids.length === 1 && ids[0] === VIDEO_SEED.videoId
      ? [seedVideo()]
      : [seedVideo({ videoId: vid(1), title: 'CS50 Lecture 1', publishedAt: '2025-01-01T00:00:00Z' })]),
    getPlaylist: async () => { throw new Error('gone'); },
    searchChannelPlaylists: async () => [],
    searchChannelVideos: async () => [{ videoId: vid(1) }],
  };
  const result = await discoverCourse({ seed, client, settings: { youtube: {} } });
  assert.equal(result.discovery, 'channel_search');
  assert.equal(result.videos.length, 2);
  assert.ok(result.warnings.some((warning) => /could not be read/.test(warning)));
});
