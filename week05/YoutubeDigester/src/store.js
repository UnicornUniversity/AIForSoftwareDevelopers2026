import { createHash } from 'node:crypto';

export class InvalidVideoUrlError extends Error {
  constructor(message) {
    super(message);
    this.name = 'InvalidVideoUrlError';
    this.status = 400;
    this.expose = true;
  }
}

export class InvalidSeedUrlError extends Error {
  constructor(message) {
    super(message);
    this.name = 'InvalidSeedUrlError';
    this.status = 400;
    this.expose = true;
  }
}

/** YouTube video ids are exactly 11 characters of [A-Za-z0-9_-]. */
export const VIDEO_ID_PATTERN = /^[A-Za-z0-9_-]{11}$/;
/** Playlist ids have no fixed length; this is the safe, accepted shape. */
export const PLAYLIST_ID_PATTERN = /^[A-Za-z0-9_-]{10,64}$/;

const YOUTUBE_HOSTS = new Set([
  'youtube.com',
  'm.youtube.com',
  'music.youtube.com',
  'youtube-nocookie.com',
]);

const ID_PATH_PREFIXES = new Set(['shorts', 'embed', 'live', 'v']);

export function isVideoId(value) {
  return typeof value === 'string' && VIDEO_ID_PATTERN.test(value);
}

export function isPlaylistId(value) {
  return typeof value === 'string' && PLAYLIST_ID_PATTERN.test(value);
}

function hostOf(url) {
  return url.hostname.toLowerCase().replace(/^www\./, '');
}

function requireUrl(input) {
  const raw = typeof input === 'string' ? input.trim() : '';
  if (raw === '') throw new InvalidSeedUrlError('Provide a YouTube video or playlist URL.');

  let url;
  try {
    url = new URL(raw);
  } catch {
    throw new InvalidSeedUrlError('That is not a valid absolute URL.');
  }

  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    throw new InvalidSeedUrlError('Only http and https URLs are supported.');
  }
  if (url.username !== '' || url.password !== '') {
    throw new InvalidSeedUrlError('URLs with embedded credentials are not supported.');
  }
  return url;
}

function videoIdFrom(url) {
  const host = hostOf(url);
  const segments = url.pathname.split('/').filter(Boolean);

  if (host === 'youtu.be') return segments[0];

  if (YOUTUBE_HOSTS.has(host)) {
    if (segments[0] === 'watch') return url.searchParams.get('v') ?? undefined;
    if (ID_PATH_PREFIXES.has(segments[0])) return segments[1];
  }

  return undefined;
}

/**
 * Accepts a single-video URL (optionally with `&list=…`) or a playlist URL.
 * A watch URL with both `v` and `list` stays a video seed and carries the
 * playlist hint, so the first lecture remains the course anchor.
 *
 * @returns {{ kind: 'video', videoId: string, playlistId: string|null, url: string }
 *         | { kind: 'playlist', playlistId: string, url: string }}
 */
export function parseSeedUrl(input) {
  const url = requireUrl(input);
  const host = hostOf(url);
  const segments = url.pathname.split('/').filter(Boolean);
  const listParam = url.searchParams.get('list');
  const playlistId = listParam && isPlaylistId(listParam) ? listParam : null;

  if (playlistId && (host === 'youtube.com' || host === 'm.youtube.com' || host === 'music.youtube.com') && segments[0] === 'playlist') {
    return {
      kind: 'playlist',
      playlistId,
      url: `https://www.youtube.com/playlist?list=${playlistId}`,
    };
  }

  const videoId = videoIdFrom(url);
  if (!isVideoId(videoId)) {
    throw new InvalidSeedUrlError(
      'That URL does not point at a single YouTube video or playlist.',
    );
  }

  return {
    kind: 'video',
    videoId,
    playlistId,
    url: `https://www.youtube.com/watch?v=${videoId}`,
  };
}

/** Backwards-compatible helper for callers that only expect one video. */
export function normalizeVideoUrl(input) {
  const seed = parseSeedUrl(input);
  if (seed.kind !== 'video') {
    throw new InvalidVideoUrlError('That URL is a playlist, not a single video.');
  }
  return { videoId: seed.videoId, url: seed.url };
}

export function normalizePlaylistUrl(input) {
  const seed = parseSeedUrl(input);
  if (seed.kind !== 'playlist') {
    throw new InvalidSeedUrlError('That URL is not a playlist.');
  }
  return { playlistId: seed.playlistId, url: seed.url };
}

/** Stable course identity: "c_" + 12 hex characters. */
export function courseIdFor(seed) {
  const primary = seed.kind === 'playlist' ? seed.playlistId : seed.videoId;
  return `c_${createHash('sha256').update(`${seed.kind}:${primary}`).digest('hex').slice(0, 12)}`;
}
