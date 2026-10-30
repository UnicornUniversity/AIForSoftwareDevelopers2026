import assert from 'node:assert/strict';
import { access, readFile, readdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { test } from 'node:test';

import { DepotError, createDepot } from '../src/depot.js';
import { readJson } from '../src/files.js';
import { parseSeedUrl } from '../src/store.js';
import { tempDir, vid } from './helpers.js';

const SEED = parseSeedUrl('https://www.youtube.com/watch?v=dQw4w9WgXcQ');
const NOW = () => new Date('2026-01-02T03:04:05.000Z');

async function makeDepot(options = {}) {
  const dataDir = options.dataDir ?? await tempDir();
  const warnings = [];
  const depot = createDepot({
    dataDir,
    now: options.now ?? NOW,
    warn: (message) => warnings.push(message),
  });
  return { depot, dataDir, warnings };
}

async function makeCourse(depot, title = 'CS50') {
  const { course } = await depot.createCourse({ seed: SEED, title });
  return course;
}

test('createCourse deduplicates by seed and is findable', async () => {
  const { depot } = await makeDepot();
  const { course, duplicate } = await depot.createCourse({ seed: SEED, title: 'CS50' });
  assert.equal(duplicate, false);
  assert.match(course.id, /^c_[a-f0-9]{12}$/);
  assert.equal(course.title, 'CS50');
  assert.equal(course.status, 'pending');

  const again = await depot.createCourse({ seed: SEED, title: 'Ignored' });
  assert.equal(again.duplicate, true);
  assert.equal(again.course.id, course.id);

  const found = await depot.findCourseBySeed(SEED);
  assert.equal(found.id, course.id);
  assert.equal((await depot.listCourses()).length, 1);
});

test('createCourse rejects an invalid seed shape', async () => {
  const { depot } = await makeDepot();
  await assert.rejects(() => depot.createCourse({ seed: { kind: 'video', videoId: 'short' } }), DepotError);
  await assert.rejects(() => depot.createCourse({ seed: { kind: 'unknown' } }), DepotError);
});

test('videos upsert without duplicates and keep the requested order', async () => {
  const { depot } = await makeDepot();
  const course = await makeCourse(depot);

  await depot.upsertVideo(course.id, { videoId: vid(1), title: 'One', position: 0 });
  await depot.upsertVideo(course.id, { videoId: vid(1), title: 'One updated' });
  await depot.upsertVideo(course.id, { videoId: vid(2), title: 'Two', position: 1 });

  let videos = await depot.listVideos(course.id);
  assert.equal(videos.length, 2);
  assert.equal(videos[0].title, 'One updated');
  assert.equal(videos[1].status, 'pending');

  await depot.setCourseVideos(course.id, [vid(2), vid(1), vid(2), 'not-an-id']);
  videos = await depot.listVideos(course.id);
  assert.deepEqual(videos.map((video) => video.id), [vid(2), vid(1)]);

  const courseAfter = await depot.getCourse(course.id);
  assert.deepEqual(courseAfter.videoIds, [vid(2), vid(1)]);
  assert.equal(await depot.getVideo('nope'), null);
});

test('updateCourse only allows the known fields', async () => {
  const { depot } = await makeDepot();
  const course = await makeCourse(depot);

  const updated = await depot.updateCourse(course.id, {
    title: 'Renamed',
    status: 'ready',
    id: 'c_ffffffffffff',
    createdAt: '1999-01-01',
    nonsense: true,
  });
  assert.equal(updated.title, 'Renamed');
  assert.equal(updated.status, 'ready');
  assert.equal(updated.id, course.id);
  assert.equal(updated.createdAt, '2026-01-02T03:04:05.000Z');
  assert.equal(Object.hasOwn(updated, 'nonsense'), false);
  assert.equal(await depot.updateCourse('c_000000000000', { title: 'x' }), null);
});

test('transcripts round-trip through Markdown with frontmatter and a cap', async () => {
  const { depot, dataDir } = await makeDepot();
  const course = await makeCourse(depot);
  await depot.upsertVideo(course.id, { videoId: vid(7), title: 'A "quoted" title' });

  const file = await depot.writeTranscript(vid(7), {
    title: 'A "quoted" title',
    url: 'https://www.youtube.com/watch?v=vid00000007',
    channel: 'CS50',
    publishedAt: '2025-01-01',
    fetchedAt: '2026-01-02T03:04:05.000Z',
    transcriptLanguage: 'en',
    wordCount: 4,
  }, 'Hello there, world.');

  assert.equal(file, `videos/${vid(7)}.md`);
  const raw = await readFile(path.join(dataDir, file), 'utf8');
  assert.match(raw, /^---\n/);
  assert.match(raw, /title: "A \\"quoted\\" title"/);
  assert.match(raw, /transcript_language: "en"/);
  assert.match(raw, /\n---\n\nHello there, world\.\n$/);

  assert.equal(await depot.readTranscript(vid(7)), 'Hello there, world.');
  assert.equal(await depot.readTranscript(vid(7), { maxChars: 5 }), 'Hello');
  assert.equal(await depot.readTranscript(vid(8)), null);
});

test('proposals and selections are validated against each other', async () => {
  const { depot } = await makeDepot();
  const course = await makeCourse(depot);

  const proposal = await depot.saveProposal(course.id, {
    source: 'deepseek',
    model: 'deepseek-chat',
    topics: [
      { id: 't1', order: 1, title: 'One', summary: '', videoIds: [vid(1)] },
      { id: 't2', order: 2, title: 'Two', summary: '', videoIds: [vid(2)] },
    ],
  });
  assert.match(proposal.id, /^p_[a-f0-9]{12}$/);
  assert.equal((await depot.getCourse(course.id)).proposal.topics.length, 2);

  const selection = await depot.saveSelection(course.id, proposal.id, ['t2', 'missing', 't2']);
  assert.deepEqual(selection.topicIds, ['t2']);

  assert.equal(await depot.saveSelection(course.id, proposal.id, ['missing']), null);
  await assert.rejects(
    () => depot.saveSelection(course.id, 'p_wrong', ['t1']),
    /does not belong/,
  );
});

test('jobs are created, updated, filtered and ordered newest first', async () => {
  const { depot } = await makeDepot();
  const course = await makeCourse(depot);
  const other = await depot.createCourse({
    seed: parseSeedUrl('https://www.youtube.com/playlist?list=PL1234567890abcdef'),
  });

  await depot.createJob({ id: 'job-1', courseId: course.id, kind: 'ingest', status: 'queued' });
  await depot.createJob({ id: 'job-2', courseId: course.id, kind: 'pdf', status: 'queued' });
  await depot.createJob({ id: 'job-3', courseId: other.course.id, kind: 'ingest', status: 'queued' });

  const updated = await depot.updateJob('job-1', {
    status: 'succeeded',
    stage: 'done',
    result: { chapterCount: 2 },
    statusText: 'ignored',
  });
  assert.equal(updated.status, 'succeeded');
  assert.deepEqual(updated.result, { chapterCount: 2 });
  assert.equal(Object.hasOwn(updated, 'statusText'), false);

  const jobs = await depot.listJobs({ courseId: course.id });
  assert.deepEqual(jobs.map((job) => job.id), ['job-2', 'job-1']);
  assert.equal((await depot.listJobs()).length, 3);
  assert.equal(await depot.updateJob('missing', { status: 'failed' }), null);
});

test('markInterruptedJobs fails active jobs and active courses', async () => {
  const { depot } = await makeDepot();
  const course = await makeCourse(depot);
  await depot.createJob({ id: 'job-run', courseId: course.id, kind: 'ingest', status: 'running' });
  await depot.createJob({ id: 'job-wait', courseId: course.id, kind: 'pdf', status: 'queued' });
  await depot.updateCourse(course.id, { status: 'transcribing' });

  assert.equal(await depot.markInterruptedJobs(), 2);
  assert.equal((await depot.getJob('job-run')).status, 'failed');
  assert.equal((await depot.getJob('job-run')).error.code, 'interrupted');
  assert.equal((await depot.getJob('job-wait')).status, 'failed');
  const after = await depot.getCourse(course.id);
  assert.equal(after.status, 'failed');
  assert.match(after.error, /restarted/);
  assert.equal(await depot.markInterruptedJobs(), 0);
});

test('ready courses and finished jobs are untouched by recovery', async () => {
  const { depot } = await makeDepot();
  const course = await makeCourse(depot);
  await depot.updateCourse(course.id, { status: 'ready' });
  await depot.createJob({ id: 'job-ok', courseId: course.id, kind: 'ingest', status: 'succeeded' });
  assert.equal(await depot.markInterruptedJobs(), 0);
  assert.equal((await depot.getCourse(course.id)).status, 'ready');
  assert.equal((await depot.getJob('job-ok')).status, 'succeeded');
});

test('channels are upserted once', async () => {
  const { depot } = await makeDepot();
  await depot.upsertChannel({ id: 'UC123', title: 'CS50' });
  await depot.upsertChannel({ id: 'UC123', title: 'CS50 Updated' });
  const channels = await depot.listChannels();
  assert.equal(channels.length, 1);
  assert.equal(channels[0].title, 'CS50 Updated');
  await assert.rejects(() => depot.upsertChannel({ id: '' }), DepotError);
});

test('concurrent writes settle into one valid depot.json with no temp files', async () => {
  const { depot, dataDir } = await makeDepot();
  const course = await makeCourse(depot);

  await Promise.all(Array.from({ length: 12 }, (_, index) => depot.updateCourse(course.id, {
    title: `Title ${index}`,
  })));
  await Promise.all(Array.from({ length: 12 }, (_, index) => depot.upsertVideo(course.id, {
    videoId: vid(index + 1),
    title: `Video ${index + 1}`,
    position: index,
  })));

  const stored = JSON.parse(await readFile(path.join(dataDir, 'depot.json'), 'utf8'));
  assert.equal(stored.version, 1);
  assert.equal(stored.courses.length, 1);
  assert.equal(stored.videos.length, 12);
  assert.equal(stored.videos.some((video) => video.title.startsWith('Video')), true);

  const entries = await readdir(dataDir);
  assert.equal(entries.some((entry) => entry.endsWith('.tmp')), false);
});

test('a corrupt depot file raises a named error instead of being overwritten', async () => {
  const dataDir = await tempDir();
  await writeFile(path.join(dataDir, 'depot.json'), '{ broken', 'utf8');
  const depot = createDepot({ dataDir, warn: () => {} });
  await assert.rejects(() => depot.listCourses(), (err) => {
    assert.ok(err instanceof DepotError);
    assert.match(err.message, /depot\.json/);
    return true;
  });
});

test('run directories are created lazily and guarded', async () => {
  const { depot, dataDir } = await makeDepot();
  const jobId = '12345678-1234-1234-1234-123456789abc';
  await depot.writeRunJson(jobId, 'state.json', { status: 'queued' });
  await depot.writeRunText(jobId, 'digest.html', '<p>hi</p>');

  assert.deepEqual(await readJson(path.join(dataDir, 'runs', jobId, 'state.json')), { status: 'queued' });
  assert.equal(await readFile(path.join(dataDir, 'runs', jobId, 'digest.html'), 'utf8'), '<p>hi</p>');
  assert.throws(() => depot.runDir('../escape'), DepotError);
});

test('deleting a course removes its videos and transcript files', async () => {
  const { depot, dataDir } = await makeDepot();
  const course = await makeCourse(depot);
  await depot.upsertVideo(course.id, { videoId: vid(9), title: 'Nine' });
  await depot.writeTranscript(vid(9), { title: 'Nine' }, 'Body');
  const file = path.join(dataDir, 'videos', `${vid(9)}.md`);
  await access(file);

  assert.equal(await depot.deleteCourse(course.id), true);
  assert.equal(await depot.getCourse(course.id), null);
  assert.equal(await depot.getVideo(vid(9)), null);
  await assert.rejects(() => access(file));
  assert.equal(await depot.deleteCourse(course.id), false);
});
