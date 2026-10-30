import { randomBytes } from 'node:crypto';
import { readFile, unlink } from 'node:fs/promises';
import path from 'node:path';

import {
  VIDEO_ID_PATTERN,
  courseIdFor,
  isPlaylistId,
  isVideoId,
} from './store.js';
import {
  ensureDir,
  frontmatterValue,
  readTextCapped,
  stripFrontmatter,
  writeAtomic,
  writeJsonAtomic,
} from './files.js';

export class DepotError extends Error {
  constructor(message) {
    super(message);
    this.name = 'DepotError';
  }
}

const COURSE_ID_PATTERN = /^c_[a-f0-9]{12}$/;
const COURSE_FIELDS = [
  'title', 'channelId', 'channelTitle', 'playlistId', 'discovery',
  'status', 'stage', 'error', 'warnings', 'videoIds', 'proposal', 'selection',
];
const VIDEO_FIELDS = [
  'courseId', 'url', 'title', 'channel', 'channelId', 'publishedAt',
  'durationSeconds', 'position', 'status', 'transcriptLanguage', 'fetchedAt',
  'wordCount', 'excerpt', 'error', 'file',
];
const JOB_FIELDS = [
  'status', 'stage', 'progress', 'error', 'warnings', 'result',
  'startedAt', 'finishedAt',
];

const ACTIVE_COURSE_STATUSES = new Set(['discovering', 'transcribing', 'clustering', 'generating']);
const INTERRUPTED_MESSAGE = 'The server restarted before this job finished.';

function emptyState() {
  return { version: 1, channels: [], courses: [], videos: [], jobs: [] };
}

function copy(value) {
  return value === null || value === undefined ? null : structuredClone(value);
}

function isCourse(value) {
  return (
    value &&
    typeof value === 'object' &&
    typeof value.id === 'string' &&
    COURSE_ID_PATTERN.test(value.id) &&
    value.seed &&
    typeof value.seed === 'object'
  );
}

function isVideo(value) {
  return (
    value &&
    typeof value === 'object' &&
    typeof value.id === 'string' &&
    VIDEO_ID_PATTERN.test(value.id)
  );
}

function isJob(value) {
  return value && typeof value === 'object' && typeof value.id === 'string';
}

/**
 * Courses, videos, transcripts, topic proposals, selections and jobs, persisted
 * as data/depot.json with transcripts in data/videos/<id>.md. One instance per
 * process; all writes are whole-file atomic replacements through `writeQueue`.
 */
export function createDepot({ dataDir, now = () => new Date(), warn = console.warn } = {}) {
  if (!dataDir) throw new DepotError('createDepot requires a dataDir.');

  const depotPath = path.join(dataDir, 'depot.json');
  const videosDir = path.join(dataDir, 'videos');
  const runsDir = path.join(dataDir, 'runs');

  let state = null;
  let loading = null;
  let writeQueue = Promise.resolve();

  async function ensureLoaded() {
    if (state) return state;
    if (loading) return loading;

    loading = (async () => {
      await ensureDir(videosDir);
      await ensureDir(runsDir);

      let text;
      try {
        text = await readFile(depotPath, 'utf8');
      } catch (err) {
        if (err.code !== 'ENOENT') throw err;
        state = emptyState();
        return state;
      }

      let parsed;
      try {
        parsed = JSON.parse(text);
      } catch (err) {
        throw new DepotError(`${depotPath} is not valid JSON (${err.message}). Fix or remove it.`);
      }
      if (!parsed || typeof parsed !== 'object' || !Array.isArray(parsed.courses)) {
        throw new DepotError(`${depotPath} has an unexpected shape; expected { version, courses: [] }.`);
      }

      const channels = Array.isArray(parsed.channels) ? parsed.channels : [];
      const courses = parsed.courses.filter(isCourse);
      const videos = Array.isArray(parsed.videos) ? parsed.videos.filter(isVideo) : [];
      const jobs = Array.isArray(parsed.jobs) ? parsed.jobs.filter(isJob) : [];

      state = {
        version: 1,
        channels,
        courses,
        videos,
        jobs,
      };

      const dropped = parsed.courses.length - courses.length;
      if (dropped > 0) warn(`[depot] ignored ${dropped} malformed course entries`);
      return state;
    })().finally(() => {
      loading = null;
    });

    return loading;
  }

  function persist() {
    const snapshot = JSON.stringify(state, null, 2);
    const run = writeQueue.then(() => writeAtomic(depotPath, `${snapshot}\n`));
    writeQueue = run.catch(() => {});
    return run;
  }

  async function requireCourse(id) {
    if (typeof id !== 'string' || !COURSE_ID_PATTERN.test(id)) return null;
    const { courses } = await ensureLoaded();
    return courses.find((course) => course.id === id) ?? null;
  }

  function primaryId(seed) {
    return seed.kind === 'playlist' ? seed.playlistId : seed.videoId;
  }

  function sameSeed(a, b) {
    return a && b && a.kind === b.kind && primaryId(a) === primaryId(b);
  }

  return {
    paths: { dataDir, depotPath, videosDir, runsDir },

    async init() {
      await ensureLoaded();
    },

    async listCourses() {
      const { courses } = await ensureLoaded();
      return courses.map(copy);
    },

    async getCourse(id) {
      const course = await requireCourse(id);
      return copy(course);
    },

    async findCourseBySeed(seed) {
      const { courses } = await ensureLoaded();
      const found = courses.find((course) => sameSeed(course.seed, seed));
      return copy(found);
    },

    async createCourse({ seed, title = '', channelId = null, channelTitle = null, playlistId = null, discovery = null } = {}) {
      if (!seed || (seed.kind !== 'video' && seed.kind !== 'playlist')) {
        throw new DepotError('createCourse requires a parsed seed.');
      }
      if (seed.kind === 'video' && !isVideoId(seed.videoId)) {
        throw new DepotError('Invalid video id in seed.');
      }
      if (seed.kind === 'playlist' && !isPlaylistId(seed.playlistId)) {
        throw new DepotError('Invalid playlist id in seed.');
      }

      const { courses } = await ensureLoaded();
      const existing = courses.find((course) => sameSeed(course.seed, seed));
      if (existing) return { course: copy(existing), duplicate: true };

      const timestamp = now().toISOString();
      const id = courseIdFor(seed);
      const course = {
        id,
        seed: { kind: seed.kind, videoId: seed.videoId ?? null, playlistId: seed.playlistId ?? null, url: seed.url },
        title: String(title ?? '').trim() || seed.url,
        channelId,
        channelTitle,
        playlistId,
        discovery,
        status: 'pending',
        stage: null,
        error: null,
        warnings: [],
        videoIds: [],
        proposal: null,
        selection: null,
        createdAt: timestamp,
        updatedAt: timestamp,
      };
      courses.push(course);
      await persist();
      return { course: copy(course), duplicate: false };
    },

    async updateCourse(id, patch = {}) {
      const course = await requireCourse(id);
      if (!course) return null;

      for (const field of COURSE_FIELDS) {
        if (Object.hasOwn(patch, field)) course[field] = patch[field];
      }
      course.updatedAt = now().toISOString();
      await persist();
      return copy(course);
    },

    async deleteCourse(id) {
      const { courses, videos } = await ensureLoaded();
      const index = courses.findIndex((course) => course.id === id);
      if (index === -1) return false;

      const [removed] = courses.splice(index, 1);
      const doomed = videos.filter((video) => video.courseId === id);
      state.videos = videos.filter((video) => video.courseId !== id);
      await persist();

      await Promise.all(doomed.map(async (video) => {
        try {
          await unlink(path.join(videosDir, `${video.id}.md`));
        } catch (err) {
          if (err.code !== 'ENOENT') throw err;
        }
      }));
      void removed;
      return true;
    },

    async upsertChannel({ id, title }) {
      if (typeof id !== 'string' || id === '') throw new DepotError('Channel id is required.');
      const { channels } = await ensureLoaded();
      const timestamp = now().toISOString();
      let channel = channels.find((entry) => entry.id === id);
      if (channel) {
        channel.title = title ?? channel.title;
        channel.updatedAt = timestamp;
      } else {
        channel = { id, title: title ?? null, addedAt: timestamp, updatedAt: timestamp };
        channels.push(channel);
      }
      await persist();
      return copy(channel);
    },

    async listChannels() {
      const { channels } = await ensureLoaded();
      return channels.map(copy);
    },

    async setCourseVideos(courseId, orderedIds = []) {
      const course = await requireCourse(courseId);
      if (!course) return null;

      course.videoIds = [...new Set(orderedIds.filter(isVideoId))];
      course.updatedAt = now().toISOString();
      await persist();
      return copy(course);
    },

    async getVideo(id) {
      if (!isVideoId(id)) return null;
      const { videos } = await ensureLoaded();
      return copy(videos.find((video) => video.id === id));
    },

    async listVideos(courseId) {
      const course = await requireCourse(courseId);
      if (!course) return [];
      const { videos } = await ensureLoaded();
      const order = new Map(course.videoIds.map((id, index) => [id, index]));
      return videos
        .filter((video) => video.courseId === courseId)
        .sort((a, b) => (order.get(a.id) ?? 999) - (order.get(b.id) ?? 999))
        .map(copy);
    },

    async upsertVideo(courseId, metadata = {}) {
      const course = await requireCourse(courseId);
      if (!course) throw new DepotError(`No course ${courseId}.`);

      const videoId = metadata.videoId ?? metadata.id;
      if (!isVideoId(videoId)) throw new DepotError('Invalid video id.');

      const { videos } = await ensureLoaded();
      let video = videos.find((entry) => entry.id === videoId);

      if (video) {
        for (const field of VIDEO_FIELDS) {
          if (Object.hasOwn(metadata, field)) video[field] = metadata[field];
        }
        if (!video.courseId) video.courseId = courseId;
      } else {
        video = {
          id: videoId,
          videoId,
          courseId,
          url: metadata.url ?? `https://www.youtube.com/watch?v=${videoId}`,
          title: metadata.title ?? null,
          channel: metadata.channel ?? metadata.channelTitle ?? null,
          channelId: metadata.channelId ?? null,
          publishedAt: metadata.publishedAt ?? null,
          durationSeconds: metadata.durationSeconds ?? null,
          position: metadata.position ?? 0,
          status: 'pending',
          transcriptLanguage: null,
          fetchedAt: null,
          wordCount: 0,
          excerpt: null,
          error: null,
          file: `videos/${videoId}.md`,
        };
        videos.push(video);
      }

      if (!course.videoIds.includes(videoId)) course.videoIds.push(videoId);
      course.updatedAt = now().toISOString();
      await persist();
      return copy(video);
    },

    async updateVideo(id, patch = {}) {
      if (!isVideoId(id)) return null;
      const { videos } = await ensureLoaded();
      const video = videos.find((entry) => entry.id === id);
      if (!video) return null;

      for (const field of VIDEO_FIELDS) {
        if (Object.hasOwn(patch, field)) video[field] = patch[field];
      }
      await persist();
      return copy(video);
    },

    transcriptPath(id) {
      if (!isVideoId(id)) throw new DepotError('Invalid video id.');
      return path.join(videosDir, `${id}.md`);
    },

    async writeTranscript(id, metadata = {}, body = '') {
      if (!isVideoId(id)) throw new DepotError('Invalid video id.');

      const frontmatter = [
        '---',
        `title: ${frontmatterValue(metadata.title)}`,
        `url: ${frontmatterValue(metadata.url)}`,
        `video_id: ${frontmatterValue(id)}`,
        `channel: ${frontmatterValue(metadata.channel)}`,
        `published: ${frontmatterValue(metadata.publishedAt)}`,
        `fetched: ${frontmatterValue(metadata.fetchedAt)}`,
        `transcript_language: ${frontmatterValue(metadata.transcriptLanguage)}`,
        `word_count: ${metadata.wordCount ?? 0}`,
        '---',
        '',
        '',
      ].join('\n');

      await writeAtomic(path.join(videosDir, `${id}.md`), `${frontmatter}${String(body).trim()}\n`);
      return `videos/${id}.md`;
    },

    async readTranscript(id, { maxChars = 200_000 } = {}) {
      if (!isVideoId(id)) return null;
      // Read past the cap so the frontmatter is always intact; the body is
      // trimmed only after the frontmatter has been stripped.
      const limit = Math.max(0, Number(maxChars) || 0) + 4_096;
      const text = await readTextCapped(path.join(videosDir, `${id}.md`), limit);
      if (text === null) return null;
      return stripFrontmatter(text).slice(0, maxChars);
    },

    async saveProposal(courseId, proposal = {}) {
      const course = await requireCourse(courseId);
      if (!course) return null;

      const saved = {
        id: proposal.id ?? `p_${randomBytes(6).toString('hex')}`,
        source: proposal.source ?? 'deterministic',
        model: proposal.model ?? null,
        error: proposal.error ?? null,
        topics: Array.isArray(proposal.topics) ? proposal.topics : [],
        createdAt: now().toISOString(),
      };
      course.proposal = saved;
      course.updatedAt = now().toISOString();
      await persist();
      return copy(saved);
    },

    async saveSelection(courseId, proposalId, topicIds = []) {
      const course = await requireCourse(courseId);
      if (!course || !course.proposal) return null;
      if (course.proposal.id !== proposalId) throw new DepotError('Proposal does not belong to this course.');

      const valid = new Set(course.proposal.topics.map((topic) => topic.id));
      const selection = [...new Set(topicIds)].filter((id) => valid.has(id));
      if (selection.length === 0) return null;

      course.selection = {
        proposalId,
        topicIds: selection,
        confirmedAt: now().toISOString(),
      };
      course.updatedAt = now().toISOString();
      await persist();
      return copy(course.selection);
    },

    async createJob(job = {}) {
      if (typeof job.id !== 'string' || job.id === '') throw new DepotError('Job id is required.');
      const { jobs } = await ensureLoaded();
      const saved = { ...job };
      jobs.push(saved);
      if (jobs.length > 200) state.jobs = jobs.slice(-200);
      await persist();
      return copy(saved);
    },

    async updateJob(id, patch = {}) {
      const { jobs } = await ensureLoaded();
      const job = jobs.find((entry) => entry.id === id);
      if (!job) return null;

      for (const field of JOB_FIELDS) {
        if (Object.hasOwn(patch, field)) job[field] = patch[field];
      }
      job.updatedAt = now().toISOString();
      await persist();
      return copy(job);
    },

    async getJob(id) {
      const { jobs } = await ensureLoaded();
      return copy(jobs.find((job) => job.id === id));
    },

    async listJobs({ courseId = null, limit = 50 } = {}) {
      const { jobs } = await ensureLoaded();
      return jobs
        .filter((job) => courseId === null || job.courseId === courseId)
        .slice(-limit)
        .reverse()
        .map(copy);
    },

    async markInterruptedJobs() {
      const { jobs, courses } = await ensureLoaded();
      const timestamp = now().toISOString();
      let count = 0;

      for (const job of jobs) {
        if (job.status === 'queued' || job.status === 'running') {
          job.status = 'failed';
          job.error = { code: 'interrupted', message: INTERRUPTED_MESSAGE };
          job.finishedAt = timestamp;
          job.updatedAt = timestamp;
          count += 1;
        }
      }

      for (const course of courses) {
        if (ACTIVE_COURSE_STATUSES.has(course.status)) {
          course.status = 'failed';
          course.error = INTERRUPTED_MESSAGE;
          course.updatedAt = timestamp;
        }
      }

      if (count > 0) await persist();
      return count;
    },

    runDir(jobId) {
      if (typeof jobId !== 'string' || !/^[A-Za-z0-9-]{8,64}$/.test(jobId)) {
        throw new DepotError('Invalid job id.');
      }
      return path.join(runsDir, jobId);
    },

    async writeRunJson(jobId, name, value) {
      await writeJsonAtomic(path.join(this.runDir(jobId), name), value);
    },

    async writeRunText(jobId, name, text) {
      await writeAtomic(path.join(this.runDir(jobId), name), text);
    },
  };
}
