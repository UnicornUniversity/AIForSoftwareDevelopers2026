import assert from 'node:assert/strict';
import { test } from 'node:test';

import { createDepot } from '../src/depot.js';
import { IngestError, runIngest } from '../src/ingest.js';
import { parseSeedUrl } from '../src/store.js';
import { QUIET, tempDir, vid } from './helpers.js';

const SEED = parseSeedUrl('https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL1234567890abcdef');
const SEED_ID = SEED.videoId;
const PLAYLIST = 'PL1234567890abcdef';
const FIXED_NOW = () => new Date('2026-01-02T03:04:05.000Z');

function meta(videoId, title, publishedAt) {
  return {
    videoId,
    title,
    channel: 'CS50',
    channelId: 'UC1',
    publishedAt,
    durationSeconds: 3_000,
  };
}

const METAS = [
  meta(SEED_ID, 'CS50 Lecture 1', '2025-01-01T00:00:00Z'),
  meta(vid(1), 'CS50 Lecture 2', '2025-01-02T00:00:00Z'),
  meta(vid(2), 'CS50 Lecture 3', '2025-01-03T00:00:00Z'),
];

function fakeYoutube({ hasKey = true } = {}) {
  return {
    hasKey: () => hasKey,
    getVideos: async (ids) => METAS.filter((entry) => ids.includes(entry.videoId)),
    getPlaylist: async () => ({
      playlistId: PLAYLIST,
      title: 'CS50 2025',
      channelId: 'UC1',
      channelTitle: 'CS50',
      publishedAt: null,
      itemCount: 3,
    }),
    listPlaylistItems: async () => [
      { videoId: vid(1), title: 'CS50 Lecture 2', channel: 'CS50', channelId: 'UC1', publishedAt: '2025-01-02T00:00:00Z', position: 0 },
      { videoId: vid(2), title: 'CS50 Lecture 3', channel: 'CS50', channelId: 'UC1', publishedAt: '2025-01-03T00:00:00Z', position: 1 },
    ],
  };
}

function fakeTranscripts(overrides = {}) {
  const calls = [];
  return {
    calls,
    async fetchAll(ids, { onEach }) {
      calls.push([...ids]);
      const results = ids.map((id) => ({
        ok: true,
        videoId: id,
        transcriptLanguage: 'en',
        text: `Transcript for ${id}.`,
        wordCount: 3,
        excerpt: `Transcript for ${id}.`,
        errorCode: null,
        ...(overrides[id] ?? {}),
      }));
      for (const result of results) await onEach(result);
      return results;
    },
  };
}

function fakeLlm() {
  const calls = [];
  return {
    calls,
    async clusterTopics(args) {
      calls.push(args);
      return {
        source: 'deepseek',
        model: 'deepseek-chat',
        topics: [{
          id: 't1',
          order: 1,
          title: 'The basics',
          summary: 'What the course covers.',
          videoIds: args.videos.map((video) => video.id),
        }],
        error: null,
        warnings: [],
        accepted: 1,
        rejected: 0,
        latencyMs: 1,
      };
    },
  };
}

async function setup(seed = SEED) {
  const dataDir = await tempDir();
  const depot = createDepot({ dataDir, warn: QUIET });
  const { course } = await depot.createCourse({ seed });
  return { depot, course, dataDir };
}

function run(depot, course, { youtube = fakeYoutube(), transcripts = fakeTranscripts(), llm = fakeLlm(), force = false, signal } = {}) {
  const updates = [];
  const warnings = [];
  const outcome = runIngest({
    courseId: course.id,
    jobId: 'job-1',
    depot,
    settings: {},
    youtube,
    transcripts,
    llm,
    force,
    signal,
    update: (patch) => updates.push(patch),
    addWarning: (message) => warnings.push(message),
    now: FIXED_NOW,
  });
  return { outcome, updates, warnings };
}

test('a full ingest reaches ready with transcripts, a proposal and a channel', async () => {
  const { depot, course } = await setup();
  const transcripts = fakeTranscripts();
  const llm = fakeLlm();
  const { outcome, updates, warnings } = run(depot, course, { transcripts, llm });

  const { result } = await outcome;
  assert.deepEqual(result, {
    courseId: course.id,
    jobId: 'job-1',
    videoCount: 3,
    transcriptCount: 3,
    failedCount: 0,
    topicCount: 1,
    proposalId: result.proposalId,
    topicSource: 'deepseek',
  });
  assert.match(result.proposalId, /^p_[a-f0-9]{12}$/);

  const stored = await depot.getCourse(course.id);
  assert.equal(stored.status, 'ready');
  assert.equal(stored.stage, 'ready');
  assert.equal(stored.title, 'CS50 2025');
  assert.equal(stored.discovery, 'direct_playlist');
  assert.equal(stored.playlistId, PLAYLIST);
  assert.equal(stored.channelId, 'UC1');
  assert.match(stored.proposal.id, /^p_/);
  assert.equal(stored.proposal.source, 'deepseek');
  assert.deepEqual(stored.proposal.topics[0].videoIds, [SEED_ID, vid(1), vid(2)]);

  const videos = await depot.listVideos(course.id);
  assert.deepEqual(videos.map((video) => video.id), [SEED_ID, vid(1), vid(2)]);
  assert.deepEqual(videos.map((video) => video.status), ['ok', 'ok', 'ok']);
  assert.equal(videos[0].transcriptLanguage, 'en');
  assert.equal(videos[0].wordCount, 3);
  assert.equal(await depot.readTranscript(SEED_ID), `Transcript for ${SEED_ID}.`);

  const channels = await depot.listChannels();
  assert.equal(channels.length, 1);
  assert.equal(channels[0].id, 'UC1');

  assert.deepEqual(llm.calls[0].videos.map((video) => video.id), [SEED_ID, vid(1), vid(2)]);
  assert.equal(llm.calls[0].courseTitle, 'CS50 2025');
  assert.deepEqual(transcripts.calls, [[SEED_ID, vid(1), vid(2)]]);
  assert.deepEqual(warnings, []);

  const stages = updates.map((patch) => patch.stage).filter(Boolean);
  assert.deepEqual(stages, ['discovering', 'metadata', 'transcribing', 'clustering']);
});

test('one missing transcript is tolerated and left out of the topics', async () => {
  const { depot, course } = await setup();
  const llm = fakeLlm();
  const { outcome, warnings } = run(depot, course, {
    transcripts: fakeTranscripts({
      [vid(2)]: { ok: false, text: '', wordCount: 0, excerpt: '', errorCode: 'no_transcript' },
    }),
    llm,
  });

  const { result } = await outcome;
  assert.equal(result.transcriptCount, 2);
  assert.equal(result.failedCount, 1);
  assert.equal(result.topicCount, 1);

  const stored = await depot.getCourse(course.id);
  assert.equal(stored.status, 'ready');
  assert.ok(stored.warnings.some((warning) => /no usable transcript/.test(warning)));

  const video = await depot.getVideo(vid(2));
  assert.equal(video.status, 'no_transcript');
  assert.equal(video.error, 'no_transcript');
  assert.equal(await depot.readTranscript(vid(2)), null);

  assert.deepEqual(llm.calls[0].videos.map((entry) => entry.id), [SEED_ID, vid(1)]);
  assert.ok(warnings.some((warning) => warning.includes('CS50 Lecture 3')));
});

test('zero usable transcripts fails the course with a clear message', async () => {
  const { depot, course } = await setup();
  const transcripts = fakeTranscripts();
  const allFail = {
    calls: transcripts.calls,
    async fetchAll(ids, { onEach }) {
      transcripts.calls.push([...ids]);
      for (const id of ids) {
        await onEach({
          ok: false, videoId: id, transcriptLanguage: null, text: '', wordCount: 0,
          excerpt: '', errorCode: 'no_transcript',
        });
      }
      return [];
    },
  };
  const llm = fakeLlm();
  const { outcome } = run(depot, course, { transcripts: allFail, llm });

  await assert.rejects(outcome, (err) => {
    assert.ok(err instanceof IngestError);
    assert.equal(err.code, 'no_transcripts');
    return true;
  });

  const stored = await depot.getCourse(course.id);
  assert.equal(stored.status, 'failed');
  assert.match(stored.error, /captions disabled/);
  assert.equal(stored.proposal, null);
  assert.equal(llm.calls.length, 0);
});

test('no discovered videos fails before any transcript work', async () => {
  const { depot, course } = await setup(parseSeedUrl(`https://www.youtube.com/playlist?list=${PLAYLIST}`));
  const transcripts = fakeTranscripts();
  const { outcome } = run(depot, course, {
    youtube: fakeYoutube({ hasKey: false }),
    transcripts,
  });

  await assert.rejects(outcome, (err) => err.code === 'discovery_failed');
  const stored = await depot.getCourse(course.id);
  assert.equal(stored.status, 'failed');
  assert.match(stored.error, /No videos were found/);
  assert.equal(transcripts.calls.length, 0);
});

test('a reingest reuses finished transcripts unless force is set', async () => {
  const { depot, course } = await setup();
  const ids = [SEED_ID, vid(1), vid(2)];
  for (const [index, id] of ids.entries()) {
    await depot.upsertVideo(course.id, {
      videoId: id,
      title: `Stored ${index + 1}`,
      position: index,
    });
    await depot.writeTranscript(id, { title: `Stored ${index + 1}` }, `Stored transcript ${index + 1}.`);
    await depot.updateVideo(id, { status: 'ok', wordCount: 3 });
  }

  const transcripts = fakeTranscripts();
  const first = await run(depot, course, { transcripts }).outcome;
  assert.equal(first.result.transcriptCount, 3);
  assert.deepEqual(transcripts.calls, []);

  const forced = await run(depot, course, { transcripts, force: true }).outcome;
  assert.equal(forced.result.transcriptCount, 3);
  assert.deepEqual(transcripts.calls, [ids]);
});

test('a deterministic topic fallback still leaves the course ready', async () => {
  const { depot, course } = await setup();
  const llm = {
    async clusterTopics(args) {
      return {
        source: 'deterministic',
        model: 'deepseek-chat',
        topics: [{ id: 't1', order: 1, title: 'Local', summary: '', videoIds: args.videos.map((video) => video.id) }],
        error: { code: 'no_key', message: 'No DeepSeek API key is configured, so topics were derived locally.' },
        warnings: ['Filled locally.'],
        accepted: 0,
        rejected: 0,
        latencyMs: 0,
      };
    },
  };
  const { outcome, warnings } = run(depot, course, { llm });
  const { result } = await outcome;

  assert.equal(result.topicSource, 'deterministic');
  const stored = await depot.getCourse(course.id);
  assert.equal(stored.status, 'ready');
  assert.equal(stored.proposal.source, 'deterministic');
  assert.equal(stored.proposal.error, 'no_key');
  assert.ok(warnings.some((warning) => /No DeepSeek API key/.test(warning)));
  assert.ok(stored.warnings.includes('Filled locally.'));
});

test('an aborted ingest fails cleanly without calling YouTube', async () => {
  const { depot, course } = await setup();
  const controller = new AbortController();
  controller.abort();
  const { outcome } = run(depot, course, { signal: controller.signal });

  await assert.rejects(outcome, (err) => err.code === 'cancelled');
  const stored = await depot.getCourse(course.id);
  assert.equal(stored.status, 'failed');
  assert.match(stored.error, /cancelled/i);
});
