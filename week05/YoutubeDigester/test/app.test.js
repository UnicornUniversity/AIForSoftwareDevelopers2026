import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { test } from 'node:test';

import { createApp } from '../src/app.js';
import { createDepot } from '../src/depot.js';
import { parseSeedUrl } from '../src/store.js';
import {
  QUIET,
  getJson,
  makeSettings,
  postForm,
  postJson,
  recordingPdfRenderer,
  startServer,
  tempDir,
  vid,
} from './helpers.js';

const VIDEO_URL = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ';
const PLAYLIST_URL = 'https://www.youtube.com/playlist?list=PL1234567890abcdef';
const MISSING_COURSE = 'c_000000000000';
const MISSING_JOB = '00000000-0000-4000-8000-000000000099';

function fakeRunner(store) {
  let counter = 0;
  const running = new Set();
  return {
    running,
    async start({ courseId, kind, force = false } = {}) {
      counter += 1;
      const id = `00000000-0000-4000-8000-${String(counter).padStart(12, '0')}`;
      const job = {
        id,
        courseId,
        kind,
        force: Boolean(force),
        status: 'queued',
        stage: 'queued',
        progress: { total: 0, done: 0, failed: 0 },
        warnings: [],
        error: null,
        result: null,
        createdAt: '2026-01-02T03:04:05.000Z',
        startedAt: null,
        updatedAt: '2026-01-02T03:04:05.000Z',
        finishedAt: null,
      };
      await store.createJob(job);
      return { job, duplicate: false };
    },
    async get(id) {
      return store.getJob(id);
    },
    async listByCourse(courseId, options = {}) {
      return store.listJobs({ ...options, courseId });
    },
    isRunning(courseId) {
      return running.has(courseId);
    },
    async shutdown() {},
  };
}

async function makeApp({ settings = makeSettings(), depot = null } = {}) {
  const dataDir = await tempDir();
  const outputDir = await tempDir('yd-app-out-');
  const store = depot ?? createDepot({ dataDir, warn: QUIET });
  const runner = fakeRunner(store);
  const app = createApp({
    depot: store,
    outputDir,
    readSettings: async () => settings,
    runner,
    pdfRenderer: recordingPdfRenderer(),
    jobConcurrency: 2,
    jobStateWriteIntervalMs: 10,
    warn: QUIET,
  });
  const server = await startServer(app);
  return { app, server, store, runner, outputDir, settings, close: () => server.close() };
}

function withApp(t, options) {
  return makeApp(options).then((context) => {
    t.after(async () => { await context.close(); });
    return context;
  });
}

async function addCourse(store, title = 'CS50', url = VIDEO_URL) {
  const { course } = await store.createCourse({ seed: parseSeedUrl(url), title });
  return course;
}

async function addProposal(store, course) {
  const proposal = await store.saveProposal(course.id, {
    source: 'deepseek',
    model: 'deepseek-chat',
    topics: [
      { id: 't1', order: 1, title: 'Memory', summary: 'How memory works.', videoIds: [vid(1)] },
      { id: 't2', order: 2, title: 'Pointers', summary: 'Where values live.', videoIds: [vid(2)] },
    ],
  });
  await store.updateCourse(course.id, { status: 'ready', stage: 'ready' });
  return proposal;
}

async function getPage(base, pathname, options = {}) {
  const response = await fetch(`${base}${pathname}`, options);
  return { response, text: await response.text() };
}

function locationOf(response) {
  const location = response.headers.get('location');
  assert.ok(location, 'expected a Location header');
  return new URL(location, 'http://localhost').pathname + new URL(location, 'http://localhost').search;
}

test('GET /health reports keys, model and course counts without failing', async (t) => {
  const settings = makeSettings({ youtube: { apiKey: 'YT' }, deepseek: { apiKey: 'DS' } });
  const ctx = await withApp(t, { settings });

  const { response, body } = await getJson(ctx.server.base, '/health');
  assert.equal(response.status, 200);
  assert.equal(body.status, 'ok');
  assert.equal(body.hasYouTubeKey, true);
  assert.equal(body.hasDeepSeekKey, true);
  assert.equal(body.model, settings.deepseek.model);
  assert.equal(body.courseCount, 0);
  assert.equal(typeof body.uptimeSeconds, 'number');
});

test('the home page explains what is missing when no keys are set', async (t) => {
  const ctx = await withApp(t);
  const { response, text } = await getPage(ctx.server.base, '/');
  assert.equal(response.status, 200);
  assert.match(text, /No API keys are configured/);
  assert.match(text, /No courses yet/);
  assert.match(text, /Add a course/);
});

test('POST /api/courses creates a course, starts an ingest and detects duplicates', async (t) => {
  const ctx = await withApp(t);
  const base = ctx.server.base;

  const first = await postJson(base, '/api/courses', { url: VIDEO_URL });
  assert.equal(first.response.status, 201);
  assert.equal(first.body.duplicate, false);
  assert.equal(first.body.course.seed.kind, 'video');
  assert.equal(first.body.job.kind, 'ingest');
  assert.equal(first.body.job.status, 'queued');

  const again = await postJson(base, '/api/courses', { url: VIDEO_URL });
  assert.equal(again.response.status, 200);
  assert.equal(again.body.duplicate, true);
  assert.equal(again.body.course.id, first.body.course.id);
  assert.equal(again.body.job, null);

  const playlist = await postJson(base, '/api/courses', { url: PLAYLIST_URL });
  assert.equal(playlist.response.status, 201);
  assert.equal(playlist.body.course.seed.kind, 'playlist');

  const list = await getJson(base, '/api/courses');
  assert.equal(list.body.courses.length, 2);
});

test('invalid seeds are rejected as HTML for forms and JSON for the API', async (t) => {
  const ctx = await withApp(t);
  const base = ctx.server.base;

  const form = await postForm(base, '/courses', { url: 'not-a-url' });
  assert.equal(form.status, 400);
  assert.match(await form.text(), /not a valid absolute URL/);

  const api = await postJson(base, '/api/courses', { url: 'https://example.com/post' });
  assert.equal(api.response.status, 400);
  assert.match(api.body.error, /YouTube video or playlist/);

  const empty = await postJson(base, '/api/courses', {});
  assert.equal(empty.response.status, 400);
});

test('the form flow redirects with a notice and then shows the course', async (t) => {
  const ctx = await withApp(t);
  const base = ctx.server.base;

  const created = await postForm(base, '/courses', { url: VIDEO_URL });
  assert.equal(created.status, 303);
  const location = locationOf(created);
  assert.match(location, /^\/courses\/c_[a-f0-9]{12}\?notice=started$/);

  const duplicate = await postForm(base, '/courses', { url: VIDEO_URL });
  assert.equal(duplicate.status, 303);
  assert.match(locationOf(duplicate), /\?notice=duplicate$/);

  const page = await getPage(base, location);
  assert.equal(page.response.status, 200);
  assert.match(page.text, /Course added/);
  assert.match(page.text, /YoutubeDigester/);

  const missing = await getPage(base, `/courses/${MISSING_COURSE}`);
  assert.equal(missing.response.status, 404);
  assert.match(missing.text, /not found/);
});

test('the topics page is 409 until a proposal exists, then accepts a selection', async (t) => {
  const ctx = await withApp(t);
  const base = ctx.server.base;
  const course = await addCourse(ctx.store);

  const tooEarly = await getPage(base, `/courses/${course.id}/topics`);
  assert.equal(tooEarly.response.status, 409);
  assert.match(tooEarly.text, /not ready yet/);

  const apiTooEarly = await getJson(base, `/api/courses/${course.id}/topics`);
  assert.equal(apiTooEarly.response.status, 409);

  const proposal = await addProposal(ctx.store, course);
  const page = await getPage(base, `/courses/${course.id}/topics`);
  assert.equal(page.response.status, 200);
  assert.match(page.text, /Memory/);
  assert.match(page.text, /Pointers/);
  assert.match(page.text, new RegExp(`value="${proposal.id}"`));
  assert.match(page.text, /name="topicIds" value="t1" checked/);

  const submitted = await postForm(base, `/courses/${course.id}/topics`, {
    proposalId: proposal.id,
    topicIds: ['t1', 't2'],
  });
  assert.equal(submitted.status, 303);
  const location = locationOf(submitted);
  assert.match(location, /\/runs\/[0-9a-f-]{36}\?notice=$/);

  const stored = await ctx.store.getCourse(course.id);
  assert.deepEqual(stored.selection.topicIds, ['t1', 't2']);
  assert.equal(stored.selection.proposalId, proposal.id);

  const jobs = await ctx.store.listJobs({ courseId: course.id });
  assert.equal(jobs[0].kind, 'pdf');
  assert.equal(jobs[0].status, 'queued');

  const noTopics = await postForm(base, `/courses/${course.id}/topics`, { proposalId: proposal.id });
  assert.equal(noTopics.status, 400);
  assert.match(await noTopics.text(), /Select at least one topic/);

  const unknownTopic = await postForm(base, `/courses/${course.id}/topics`, {
    proposalId: proposal.id,
    topicIds: ['gone'],
  });
  assert.equal(unknownTopic.status, 400);
  assert.match(await unknownTopic.text(), /None of the selected topics/);

  const stale = await postForm(base, `/courses/${course.id}/topics`, {
    proposalId: 'p_000000000000',
    topicIds: ['t1'],
  });
  assert.equal(stale.status, 409);
  assert.match(await stale.text(), /out of date/);
});

test('the selection API starts a PDF job for the chosen topics', async (t) => {
  const ctx = await withApp(t);
  const base = ctx.server.base;
  const course = await addCourse(ctx.store);
  await addProposal(ctx.store, course);

  const selected = await postJson(base, `/api/courses/${course.id}/selection`, { topicIds: ['t2'] });
  assert.equal(selected.response.status, 202);
  assert.deepEqual(selected.body.selection.topicIds, ['t2']);
  assert.equal(selected.body.job.kind, 'pdf');
  assert.equal(selected.body.job.courseId, course.id);

  const empty = await postJson(base, `/api/courses/${course.id}/selection`, { topicIds: [] });
  assert.equal(empty.response.status, 400);

  const fresh = await addCourse(ctx.store, 'No proposal', PLAYLIST_URL);
  const missingProposal = await postJson(base, `/api/courses/${fresh.id}/selection`, { topicIds: ['t1'] });
  assert.equal(missingProposal.response.status, 409);
});

test('run pages and the job API expose a job only to its own course', async (t) => {
  const ctx = await withApp(t);
  const base = ctx.server.base;
  const course = await addCourse(ctx.store);
  const other = await addCourse(ctx.store, 'Other', PLAYLIST_URL);
  const { job } = await ctx.runner.start({ courseId: course.id, kind: 'ingest' });

  const page = await getPage(base, `/courses/${course.id}/runs/${job.id}`);
  assert.equal(page.response.status, 200);
  assert.match(page.text, /Run Report/);
  assert.match(page.text, /Waiting for a free slot/);
  assert.match(page.text, /Course ingest/);

  const api = await getJson(base, `/api/jobs/${job.id}`);
  assert.equal(api.response.status, 200);
  assert.equal(api.body.job.id, job.id);

  const wrongCourse = await getPage(base, `/courses/${other.id}/runs/${job.id}`);
  assert.equal(wrongCourse.response.status, 404);

  const badId = await getPage(base, `/courses/${course.id}/runs/not-a-uuid`);
  assert.equal(badId.response.status, 404);

  const unknown = await getJson(base, `/api/jobs/${MISSING_JOB}`);
  assert.equal(unknown.response.status, 404);
  assert.match(unknown.body.error, /not found/i);

  const malformed = await getJson(base, '/api/jobs/not-a-uuid');
  assert.equal(malformed.response.status, 404);
});

test('downloads respect job state, file location and contents', async (t) => {
  const ctx = await withApp(t);
  const base = ctx.server.base;
  const course = await addCourse(ctx.store);

  const queued = await ctx.runner.start({ courseId: course.id, kind: 'pdf' });
  const notReady = await getPage(base, `/courses/${course.id}/runs/${queued.job.id}/download`);
  assert.equal(notReady.response.status, 409);

  const missingApi = await getJson(base, `/api/courses/${course.id}/pdf`);
  assert.equal(missingApi.response.status, 404);

  const fileName = `pdf-${course.id}.pdf`;
  const pdfPath = path.join(ctx.outputDir, course.id, fileName);
  await mkdir(path.dirname(pdfPath), { recursive: true });
  await writeFile(pdfPath, '%PDF-1.4 app test\n', 'utf8');

  const readyJob = {
    id: '00000000-0000-4000-8000-0000000000aa',
    courseId: course.id,
    kind: 'pdf',
    status: 'succeeded',
    stage: 'done',
    progress: { total: 2, done: 2, failed: 0 },
    warnings: [],
    error: null,
    result: { pdfPath, chapterCount: 2, generatedAt: '2026-01-02T03:04:05.000Z' },
    createdAt: '2026-01-02T03:04:05.000Z',
    startedAt: '2026-01-02T03:04:05.000Z',
    updatedAt: '2026-01-02T03:04:06.000Z',
    finishedAt: '2026-01-02T03:04:06.000Z',
  };
  await ctx.store.createJob(readyJob);

  const download = await fetch(`${base}/courses/${course.id}/runs/${readyJob.id}/download`);
  assert.equal(download.status, 200);
  assert.match(download.headers.get('content-type'), /application\/pdf/);
  const disposition = download.headers.get('content-disposition');
  assert.match(disposition, /attachment/);
  assert.match(disposition, /CS50\.pdf/);
  assert.equal(await download.text(), '%PDF-1.4 app test\n');

  const api = await getJson(base, `/api/courses/${course.id}/pdf`);
  assert.equal(api.response.status, 200);
  assert.equal(api.body.jobId, readyJob.id);
  assert.equal(api.body.downloadUrl, `/courses/${course.id}/runs/${readyJob.id}/download`);
  assert.equal(api.body.chapterCount, 2);

  const ingestJob = { ...readyJob, id: '00000000-0000-4000-8000-0000000000bb', kind: 'ingest' };
  await ctx.store.createJob(ingestJob);
  const wrongKind = await getPage(base, `/courses/${course.id}/runs/${ingestJob.id}/download`);
  assert.equal(wrongKind.response.status, 409);
  assert.match(wrongKind.text, /did not produce a PDF/);

  const outside = path.join(await tempDir('yd-outside-'), 'secret.pdf');
  await writeFile(outside, '%PDF-1.4 outside\n', 'utf8');
  const outsideJob = {
    ...readyJob,
    id: '00000000-0000-4000-8000-0000000000cc',
    result: { pdfPath: outside, chapterCount: 1 },
  };
  await ctx.store.createJob(outsideJob);
  const escaped = await getPage(base, `/courses/${course.id}/runs/${outsideJob.id}/download`);
  assert.equal(escaped.response.status, 404);
  assert.match(escaped.text, /outside the output folder/);

  const goneJob = {
    ...readyJob,
    id: '00000000-0000-4000-8000-0000000000dd',
    result: { pdfPath: path.join(ctx.outputDir, course.id, 'gone.pdf'), chapterCount: 1 },
  };
  await ctx.store.createJob(goneJob);
  const gone = await getPage(base, `/courses/${course.id}/runs/${goneJob.id}/download`);
  assert.equal(gone.response.status, 410);
});

test('reingest and delete work from both the API and the forms', async (t) => {
  const ctx = await withApp(t);
  const base = ctx.server.base;
  const course = await addCourse(ctx.store);

  const reingest = await postJson(base, `/api/courses/${course.id}/reingest`, { force: true });
  assert.equal(reingest.response.status, 202);
  assert.equal(reingest.body.job.kind, 'ingest');
  assert.equal(reingest.body.job.force, true);

  const formReingest = await postForm(base, `/courses/${course.id}/reingest`, { force: '1' });
  assert.equal(formReingest.status, 303);
  assert.match(locationOf(formReingest), /\/runs\/[0-9a-f-]{36}/);

  ctx.runner.running.add(course.id);
  const blockedDelete = await fetch(`${base}/api/courses/${course.id}`, { method: 'DELETE' });
  assert.equal(blockedDelete.status, 409);
  const blockedForm = await postForm(base, `/courses/${course.id}/delete`, {});
  assert.equal(blockedForm.status, 409);

  ctx.runner.running.delete(course.id);
  const deleted = await fetch(`${base}/api/courses/${course.id}`, { method: 'DELETE' });
  assert.equal(deleted.status, 204);
  assert.equal((await getJson(base, `/api/courses/${course.id}`)).response.status, 404);

  const second = await addCourse(ctx.store, 'Second', PLAYLIST_URL);
  const removed = await postForm(base, `/courses/${second.id}/delete`, {});
  assert.equal(removed.status, 303);
  assert.equal(locationOf(removed), '/?notice=deleted');
});

test('the deprecated digest alias still creates courses', async (t) => {
  const ctx = await withApp(t);
  const base = ctx.server.base;

  const first = await postJson(base, '/api/digest', { url: VIDEO_URL });
  assert.equal(first.response.status, 201);
  assert.equal(first.body.deprecated, '/api/courses');
  assert.equal(first.body.course.seed.kind, 'video');

  const again = await postJson(base, '/api/digest', { url: VIDEO_URL });
  assert.equal(again.response.status, 200);
  assert.equal(again.body.duplicate, true);

  const invalid = await postJson(base, '/api/digest', {});
  assert.equal(invalid.response.status, 400);
});

test('JSON routes answer JSON 404 and malformed bodies are a 400', async (t) => {
  const ctx = await withApp(t);
  const base = ctx.server.base;

  const api = await getJson(base, '/api/nope');
  assert.equal(api.response.status, 404);
  assert.match(api.body.error, /No route for GET \/api\/nope/);

  const page = await getPage(base, '/nope');
  assert.equal(page.response.status, 404);
  assert.match(page.text, /No page at GET \/nope/);

  const brokenBody = await fetch(`${base}/api/courses`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: '{"url":',
  });
  assert.equal(brokenBody.status, 400);
  const body = await brokenBody.json();
  assert.match(body.error, /not valid JSON/);
});

test('unexpected failures are scrubbed and health degrades instead of failing', async (t) => {
  const dataDir = await tempDir();
  const store = createDepot({ dataDir, warn: QUIET });
  const broken = {
    ...store,
    listCourses: async () => {
      throw new Error('SECRET database detail');
    },
  };
  const ctx = await withApp(t, { depot: broken });
  const base = ctx.server.base;

  const api = await getJson(base, '/api/courses');
  assert.equal(api.response.status, 500);
  assert.match(api.body.error, /Something failed/);
  assert.equal(String(api.body.error).includes('SECRET'), false);

  const page = await getPage(base, '/');
  assert.equal(page.response.status, 500);
  assert.equal(page.text.includes('SECRET'), false);
  assert.match(page.text, /Something failed/);

  const health = await getJson(base, '/health');
  assert.equal(health.response.status, 200);
  assert.equal(health.body.status, 'degraded');
  assert.equal(health.body.courseCount, null);
});

test('the settings page shows keys as configured but never reveals them', async (t) => {
  const settings = makeSettings({
    youtube: { apiKey: 'YT_SECRET_123' },
    deepseek: { apiKey: 'DS_SECRET_456' },
  });
  const ctx = await withApp(t, { settings });

  const { response, text } = await getPage(ctx.server.base, '/settings');
  assert.equal(response.status, 200);
  assert.equal(text.includes('YT_SECRET_123'), false);
  assert.equal(text.includes('DS_SECRET_456'), false);
  assert.match(text, /Configured/);
  assert.match(text, /\(set\)/);
  assert.match(text, /secrets redacted/);
  assert.match(text, /age 10/);
});
