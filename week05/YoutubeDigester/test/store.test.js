import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  courseIdFor,
  isPlaylistId,
  isVideoId,
  normalizePlaylistUrl,
  normalizeVideoUrl,
  parseSeedUrl,
} from '../src/store.js';

const VIDEO = 'dQw4w9WgXcQ';
const PLAYLIST = 'PL1234567890abcdef';

test('a normal watch URL becomes a video seed', () => {
  assert.deepEqual(parseSeedUrl(`https://www.youtube.com/watch?v=${VIDEO}`), {
    kind: 'video',
    videoId: VIDEO,
    playlistId: null,
    url: `https://www.youtube.com/watch?v=${VIDEO}`,
  });
});

test('youtu.be, shorts, embed, live and /v/ URLs are accepted', () => {
  for (const url of [
    `https://youtu.be/${VIDEO}`,
    `https://www.youtube.com/shorts/${VIDEO}`,
    `https://www.youtube.com/embed/${VIDEO}`,
    `https://www.youtube.com/live/${VIDEO}`,
    `https://www.youtube.com/v/${VIDEO}`,
    `https://m.youtube.com/watch?v=${VIDEO}`,
    `https://music.youtube.com/watch?v=${VIDEO}`,
    `https://www.youtube-nocookie.com/embed/${VIDEO}`,
  ]) {
    assert.equal(parseSeedUrl(url).videoId, VIDEO, url);
  }
});

test('a watch URL with &list= stays a video seed and keeps the playlist hint', () => {
  const seed = parseSeedUrl(`https://www.youtube.com/watch?v=${VIDEO}&list=${PLAYLIST}&index=3`);
  assert.equal(seed.kind, 'video');
  assert.equal(seed.videoId, VIDEO);
  assert.equal(seed.playlistId, PLAYLIST);
  assert.equal(seed.url, `https://www.youtube.com/watch?v=${VIDEO}`);
});

test('a youtu.be URL carries its list hint too', () => {
  const seed = parseSeedUrl(`https://youtu.be/${VIDEO}?list=${PLAYLIST}`);
  assert.equal(seed.kind, 'video');
  assert.equal(seed.playlistId, PLAYLIST);
});

test('a playlist URL becomes a playlist seed', () => {
  assert.deepEqual(parseSeedUrl(`https://www.youtube.com/playlist?list=${PLAYLIST}`), {
    kind: 'playlist',
    playlistId: PLAYLIST,
    url: `https://www.youtube.com/playlist?list=${PLAYLIST}`,
  });
});

test('an invalid or unusable playlist hint is ignored, not fatal', () => {
  const seed = parseSeedUrl(`https://www.youtube.com/watch?v=${VIDEO}&list=short`);
  assert.equal(seed.kind, 'video');
  assert.equal(seed.playlistId, null);
});

test('non-YouTube, channel, credential and malformed URLs are rejected with 400', () => {
  const rejected = [
    '',
    'not a url',
    'ftp://youtube.com/watch?v=dQw4w9WgXcQ',
    'javascript:alert(1)',
    'https://example.com/watch?v=dQw4w9WgXcQ',
    'https://www.youtube.com/channel/UC1234567890',
    'https://www.youtube.com/@somechannel',
    'https://www.youtube.com/watch?v=too-short',
    `https://user:pass@www.youtube.com/watch?v=${VIDEO}`,
    'https://www.youtube.com/playlist',
  ];
  for (const url of rejected) {
    assert.throws(() => parseSeedUrl(url), (err) => err.status === 400 && err.expose === true, url);
  }
});

test('normalizeVideoUrl and normalizePlaylistUrl keep the old contracts', () => {
  assert.deepEqual(normalizeVideoUrl(`https://youtu.be/${VIDEO}?t=30`), {
    videoId: VIDEO,
    url: `https://www.youtube.com/watch?v=${VIDEO}`,
  });
  assert.throws(() => normalizeVideoUrl(`https://www.youtube.com/playlist?list=${PLAYLIST}`), /playlist/i);
  assert.deepEqual(normalizePlaylistUrl(`https://www.youtube.com/playlist?list=${PLAYLIST}`), {
    playlistId: PLAYLIST,
    url: `https://www.youtube.com/playlist?list=${PLAYLIST}`,
  });
  assert.throws(() => normalizePlaylistUrl(`https://youtu.be/${VIDEO}`), /not a playlist/i);
});

test('video and playlist id predicates enforce their shapes', () => {
  assert.equal(isVideoId(VIDEO), true);
  assert.equal(isVideoId('short'), false);
  assert.equal(isVideoId('dQw4w9WgXc!'), false);
  assert.equal(isPlaylistId(PLAYLIST), true);
  assert.equal(isPlaylistId('too-short'), false);
});

test('courseIdFor is stable and separates videos from playlists', () => {
  const videoSeed = { kind: 'video', videoId: VIDEO };
  const same = { kind: 'video', videoId: VIDEO, playlistId: PLAYLIST };
  assert.equal(courseIdFor(videoSeed), courseIdFor(same));
  assert.notEqual(courseIdFor(videoSeed), courseIdFor({ kind: 'playlist', playlistId: VIDEO }));
  assert.match(courseIdFor(videoSeed), /^c_[a-f0-9]{12}$/);
});
