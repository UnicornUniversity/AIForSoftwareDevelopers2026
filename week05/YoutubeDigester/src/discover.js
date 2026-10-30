import { YouTubeError } from './youtube.js';

const LECTURE_WORDS = 'lecture|lesson|class|episode|ep|part|day|week|chapter|unit|session|module';
const GENERIC_TOKENS = new Set([
  'a', 'an', 'the', 'and', 'or', 'of', 'for', 'to', 'in', 'on', 'with', 'from', 'by', 'at',
  'is', 'are', 'this', 'that', 'it', 'its', 'your', 'my',
  'introduction', 'intro', 'overview', 'basics', 'basic', 'beginner', 'beginners', 'advanced',
  'course', 'courses', 'tutorial', 'tutorials', 'series', 'full', 'complete', 'part', 'lesson',
  'lecture', 'class', 'episode', 'ep', 'day', 'week', 'chapter', 'unit', 'session', 'module',
  'video', 'videos', 'learn', 'learning', 'explained', 'guide', 'how', 'what', 'why',
  'youtube', 'official',
]);

const ENTITIES = {
  amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ', '#39': "'",
};

export function decodeEntities(text) {
  return String(text ?? '').replace(/&(#x?[0-9a-f]+|[a-z]+);/gi, (match, name) => {
    const key = name.toLowerCase();
    if (key.startsWith('#x')) {
      const code = Number.parseInt(key.slice(2), 16);
      return Number.isFinite(code) ? String.fromCodePoint(code) : match;
    }
    if (key.startsWith('#')) {
      const code = Number.parseInt(key.slice(1), 10);
      return Number.isFinite(code) ? String.fromCodePoint(code) : match;
    }
    return ENTITIES[key] ?? match;
  });
}

/**
 * Turns a lecture title into the course title to search for:
 * "CS50 Lecture 1 – Introduction [HD]" → "CS50".
 */
export function deriveCourseTitle(videoTitle) {
  const original = decodeEntities(videoTitle).replace(/\s+/g, ' ').trim();
  if (original === '') return '';

  let text = original
    .replace(/\[[^\]]*\]/g, ' ')
    .replace(/\([^)]*\)/g, ' ')
    .replace(/\bS\d{1,2}\s*E\d{1,2}\b/gi, ' ')
    .replace(new RegExp(`\\b(?:${LECTURE_WORDS})\\s*#?\\s*\\d+(?:\\s*[.,:;–—-]\\s*\\d+)?\\b`, 'gi'), ' ')
    .replace(/\B#\d+\b/g, ' ')
    .replace(/\b\d+\s*\/\s*\d+\b/g, ' ')
    .replace(/\s+/g, ' ')
    .replace(/^[\s|:–—-]+|[\s|:–—-]+$/g, '')
    .trim();

  if (text === '') text = original;
  return text;
}

export function courseKeyTokens(title) {
  const tokens = decodeEntities(title)
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '') // strip combining marks left by NFKD
    .split(/[^a-z0-9]+/)
    .filter((token) => token.length >= 2 && !GENERIC_TOKENS.has(token));
  return [...new Set(tokens)];
}

export function titleMatchScore(left, right) {
  const a = new Set(courseKeyTokens(left));
  const b = new Set(courseKeyTokens(right));
  if (a.size === 0 || b.size === 0) return 0;

  let shared = 0;
  for (const token of a) if (b.has(token)) shared += 1;
  const overlap = shared / Math.min(a.size, b.size);

  const rawLeft = decodeEntities(left).toLowerCase().replace(/\s+/g, ' ').trim();
  const rawRight = decodeEntities(right).toLowerCase().replace(/\s+/g, ' ').trim();
  if (rawLeft !== '' && rawLeft === rawRight) return 1;
  if (rawLeft !== '' && rawRight !== '' && (rawLeft.includes(rawRight) || rawRight.includes(rawLeft))) {
    return Math.max(overlap, 0.9);
  }
  return overlap;
}

export function pickPlaylist(playlists, { courseTitle = '', minTitleMatch = 0.5 } = {}) {
  let best = null;
  let bestScore = -1;

  for (const playlist of playlists ?? []) {
    if (!playlist?.playlistId) continue;
    if (playlist.itemCount !== null && playlist.itemCount !== undefined && playlist.itemCount < 2) continue;
    const score = titleMatchScore(courseTitle, playlist.title);
    if (score > bestScore) {
      best = playlist;
      bestScore = score;
    }
  }
  return bestScore >= minTitleMatch ? best : null;
}

function isShort(durationSeconds) {
  return Number.isFinite(durationSeconds) && durationSeconds > 0 && durationSeconds <= 60;
}

function sharesCourseTokens(title, courseTitle) {
  const courseTokens = new Set(courseKeyTokens(courseTitle));
  if (courseTokens.size === 0) return true;
  return courseKeyTokens(title).some((token) => courseTokens.has(token));
}

function placeholderVideo(seed) {
  return {
    videoId: seed.videoId,
    title: '',
    channel: '',
    channelId: '',
    publishedAt: null,
    durationSeconds: 0,
    position: 0,
  };
}

function dedupeById(videos) {
  const seen = new Set();
  const unique = [];
  for (const video of videos) {
    if (seen.has(video.videoId)) continue;
    seen.add(video.videoId);
    unique.push(video);
  }
  return unique;
}

function withinCap(videos, maxVideos, seedId, warn) {
  if (videos.length <= maxVideos) return videos;
  const kept = videos.slice(0, maxVideos);
  const seed = seedId ? videos.find((video) => video.videoId === seedId) : null;
  if (seed && !kept.some((video) => video.videoId === seedId)) kept[kept.length - 1] = seed;
  warn?.(`Only the first ${maxVideos} videos were kept (the course list is longer).`);
  return kept;
}

async function readPlaylist(client, playlistId, maxVideos, signal) {
  const playlist = await client.getPlaylist(playlistId, { signal });
  const items = await client.listPlaylistItems(playlistId, { max: maxVideos, signal });
  return { playlist, items };
}

/**
 * Discovers a course from its seed: an explicit playlist, a playlist hinted by
 * the seed URL, a matching channel playlist, or a channel video search. Falls
 * back to the single seed video when nothing better can be established.
 */
export async function discoverCourse({
  seed,
  client,
  settings = {},
  signal,
  warn = () => {},
} = {}) {
  if (!seed || (seed.kind !== 'video' && seed.kind !== 'playlist')) {
    throw new Error('discoverCourse requires a parsed seed.');
  }

  const youtube = settings.youtube ?? {};
  const maxVideos = Math.max(1, youtube.maxVideos ?? 30);
  const warnings = [];

  if (seed.kind === 'playlist') {
    if (!client?.hasKey?.()) {
      warnings.push('YouTube API key is not configured, so the playlist cannot be read.');
      return {
        discovery: 'direct_playlist', courseTitle: seed.url, channelId: null, channelTitle: null,
        playlistId: seed.playlistId, videos: [], warnings,
      };
    }
    const { playlist, items } = await readPlaylist(client, seed.playlistId, maxVideos, signal);
    return {
      discovery: 'direct_playlist',
      courseTitle: playlist.title || seed.url,
      channelId: playlist.channelId || null,
      channelTitle: playlist.channelTitle || null,
      playlistId: playlist.playlistId,
      videos: withinCap(dedupeById(items), maxVideos, null, warnings.push.bind(warnings)),
      warnings,
    };
  }

  if (!client?.hasKey?.()) {
    warnings.push('YouTube API key is not configured, so only this video can be read.');
    return {
      discovery: 'seed_only',
      courseTitle: seed.url,
      channelId: null,
      channelTitle: null,
      playlistId: seed.playlistId ?? null,
      videos: [placeholderVideo(seed)],
      warnings,
    };
  }

  const [seedMeta] = await client.getVideos([seed.videoId], { signal });
  const seedVideo = seedMeta
    ? { ...seedMeta, position: 0 }
    : placeholderVideo(seed);
  const courseTitle = deriveCourseTitle(seedVideo.title) || seed.url;
  const channelId = seedVideo.channelId || null;
  const channelTitle = seedVideo.channel || null;

  // 1. An explicit playlist in the seed URL is the strongest signal.
  if (seed.playlistId) {
    try {
      const { playlist, items } = await readPlaylist(client, seed.playlistId, maxVideos, signal);
      if (items.length > 0) {
        const ordered = dedupeById([seedVideo, ...items]);
        return {
          discovery: 'direct_playlist',
          courseTitle: playlist.title || courseTitle,
          channelId: playlist.channelId || channelId,
          channelTitle: playlist.channelTitle || channelTitle,
          playlistId: playlist.playlistId,
          videos: withinCap(ordered, maxVideos, seed.videoId, warnings.push.bind(warnings)),
          warnings,
        };
      }
      warnings.push('The playlist linked from that video is empty; looked for another one.');
    } catch (err) {
      if (err instanceof YouTubeError && err.code === 'youtube_no_key') throw err;
      warnings.push('The playlist linked from that video could not be read; looked for another one.');
    }
  }

  // 2. A channel playlist matching the derived course title.
  if (channelId) {
    try {
      const playlists = await client.searchChannelPlaylists({
        channelId,
        query: courseTitle,
        max: youtube.playlistSearchMaxResults ?? 10,
        signal,
      });
      const picked = pickPlaylist(playlists, {
        courseTitle,
        minTitleMatch: youtube.minTitleMatch ?? 0.5,
      });
      if (picked) {
        const { items } = await readPlaylist(client, picked.playlistId, maxVideos, signal);
        if (items.length > 0) {
          const ordered = dedupeById([seedVideo, ...items]);
          return {
            discovery: 'playlist_search',
            courseTitle: picked.title || courseTitle,
            channelId: picked.channelId || channelId,
            channelTitle: picked.channelTitle || channelTitle,
            playlistId: picked.playlistId,
            videos: withinCap(ordered, maxVideos, seed.videoId, warnings.push.bind(warnings)),
            warnings,
          };
        }
      }
    } catch (err) {
      if (err instanceof YouTubeError && err.code === 'youtube_no_key') throw err;
      warnings.push('No matching channel playlist could be found; searched the channel instead.');
    }

    // 3. Channel video search, filtered by title tokens and duration.
    try {
      const candidates = await client.searchChannelVideos({
        channelId,
        query: courseTitle,
        max: youtube.searchMaxResults ?? 50,
        pages: youtube.searchPages ?? 1,
        signal,
      });
      const candidateIds = candidates
        .map((candidate) => candidate.videoId)
        .filter((id) => id !== seed.videoId)
        .slice(0, 100);
      const metas = candidateIds.length > 0
        ? await client.getVideos(candidateIds, { signal })
        : [];
      const metaById = new Map(metas.map((meta) => [meta.videoId, meta]));

      const matches = [];
      for (const meta of metas) {
        if (!meta.channelId || meta.channelId !== channelId) continue;
        if (!youtube.includeShorts && isShort(meta.durationSeconds)) continue;
        const minDuration = youtube.minDurationSeconds ?? 120;
        if (minDuration > 0 && meta.durationSeconds > 0 && meta.durationSeconds < minDuration) continue;
        if (!sharesCourseTokens(meta.title, courseTitle)) continue;
        matches.push(meta);
      }
      matches.sort((a, b) => String(a.publishedAt ?? '').localeCompare(String(b.publishedAt ?? '')));

      if (matches.length > 0 || candidates.some((candidate) => candidate.videoId === seed.videoId)) {
        const ordered = dedupeById([seedVideo, ...matches]);
        if (ordered.length > 1) {
          return {
            discovery: 'channel_search',
            courseTitle,
            channelId,
            channelTitle,
            playlistId: null,
            videos: withinCap(ordered, maxVideos, seed.videoId, warnings.push.bind(warnings)),
            warnings,
          };
        }
      }
      warnings.push('No other videos from this course were found on the channel.');
    } catch (err) {
      if (err instanceof YouTubeError && err.code === 'youtube_no_key') throw err;
      warnings.push('The channel search failed; only the seed video is included.');
    }
  }

  return {
    discovery: 'seed_only',
    courseTitle,
    channelId,
    channelTitle,
    playlistId: seed.playlistId ?? null,
    videos: [seedVideo],
    warnings,
  };
}
