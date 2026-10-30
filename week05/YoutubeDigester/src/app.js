import { stat } from 'node:fs/promises';
import path from 'node:path';

import express from 'express';

import { config } from './config.js';
import { createDepot } from './depot.js';
import { safeFilename } from './files.js';
import { runPdfGeneration } from './generate.js';
import { runIngest } from './ingest.js';
import { createJobRunner } from './jobs.js';
import { createPdfRenderer } from './pdf.js';
import { loadSettings, SETTINGS_PATH } from './settings.js';
import { parseSeedUrl } from './store.js';
import {
  renderCoursePage,
  renderErrorPage,
  renderHome,
  renderRunPage,
  renderSettingsPage,
  renderTopicsPage,
} from './ui.js';

const COURSE_ID = /^c_[a-f0-9]{12}$/;
const JOB_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.name = 'HttpError';
    this.status = status;
    this.expose = status < 500;
  }
}

function wrap(handler) {
  return (req, res, next) => Promise.resolve(handler(req, res, next)).catch(next);
}

function isApiPath(req) {
  return req.path === '/health' || req.path.startsWith('/api/');
}

function courseIdFrom(req) {
  const id = req.params.id;
  if (!COURSE_ID.test(id)) throw new HttpError(404, 'That course was not found.');
  return id;
}

function jobIdFrom(req) {
  const id = req.params.jobId;
  if (!JOB_ID.test(id)) throw new HttpError(404, 'That run was not found.');
  return id;
}

function topicIdsFrom(body) {
  const raw = body?.topicIds;
  if (Array.isArray(raw)) return raw.filter((value) => typeof value === 'string' && value !== '');
  return typeof raw === 'string' && raw !== '' ? [raw] : [];
}

function forceFrom(body) {
  return body?.force === true || body?.force === '1' || body?.force === 'on';
}

function wantsJson(req) {
  return req.is('application/json') === 'application/json';
}

/**
 * Builds the application. Every collaborator is injectable so tests can run
 * without keys, network, or Chromium; index.js uses the defaults.
 */
export function createApp({
  depot = null,
  dataDir = config.dataDir,
  outputDir = config.outputDir,
  settingsPath = SETTINGS_PATH,
  readSettings = null,
  runner = null,
  pdfRenderer = null,
  pdfExecutablePath = config.pdf.executablePath,
  jobConcurrency = 2,
  jobStateWriteIntervalMs = 500,
  warn = console.warn,
} = {}) {
  const store = depot ?? createDepot({ dataDir, warn });
  const loadCurrentSettings = readSettings ?? (() => loadSettings(settingsPath, { warn }));
  const renderer = pdfRenderer ?? createPdfRenderer({ executablePath: pdfExecutablePath, warn });

  const handlers = {
    ingest: (context) => runIngest({ ...context, depot: store }),
    pdf: (context) => runPdfGeneration({
      ...context,
      depot: store,
      pdfRenderer: renderer,
      outputDir,
    }),
  };

  const jobs = runner ?? createJobRunner({
    depot: store,
    handlers,
    readSettings: loadCurrentSettings,
    concurrency: jobConcurrency,
    stateWriteIntervalMs: jobStateWriteIntervalMs,
    warn,
  });

  const app = express();
  app.disable('x-powered-by');
  app.use(express.urlencoded({ extended: false, limit: '2mb' }));
  app.use(express.json({ limit: '2mb' }));

  app.use((req, res, next) => {
    res.setHeader('x-content-type-options', 'nosniff');
    next();
  });

  async function requireCourse(id) {
    const course = await store.getCourse(id);
    if (!course) throw new HttpError(404, 'That course was not found.');
    return course;
  }

  async function loadForPage() {
    return loadCurrentSettings();
  }

  function renderError(res, status, message) {
    res.status(status).type('html').send(renderErrorPage({ status, message }));
  }

  async function createCourseFromUrl(url) {
    const seed = parseSeedUrl(url);
    const existing = await store.findCourseBySeed(seed);
    if (existing) return { course: existing, duplicate: true, job: null };

    const created = await store.createCourse({ seed });
    if (created.duplicate) return { course: created.course, duplicate: true, job: null };

    const { job } = await jobs.start({ courseId: created.course.id, kind: 'ingest' });
    return { course: created.course, duplicate: false, job };
  }

  // ---- Pages -------------------------------------------------------------

  app.get('/', wrap(async (_req, res) => {
    const [courses, settings] = await Promise.all([store.listCourses(), loadForPage()]);
    res.type('html').send(renderHome({
      courses,
      settings,
      hasYouTubeKey: settings.youtube.apiKey !== '',
      hasDeepSeekKey: settings.deepseek.apiKey !== '',
      notice: typeof _req.query.notice === 'string' ? _req.query.notice : null,
    }));
  }));

  app.post('/courses', wrap(async (req, res) => {
    const { course, duplicate } = await createCourseFromUrl(req.body?.url);
    res.redirect(303, `/courses/${course.id}?notice=${duplicate ? 'duplicate' : 'started'}`);
  }));

  app.get('/courses/:id', wrap(async (req, res) => {
    const course = await requireCourse(courseIdFrom(req));
    const [videos, courseJobs] = await Promise.all([
      store.listVideos(course.id),
      jobs.listByCourse(course.id, { limit: 20 }),
    ]);
    const activeJob = courseJobs.find((job) => job.status === 'queued' || job.status === 'running') ?? null;
    res.type('html').send(renderCoursePage({
      course,
      videos,
      jobs: courseJobs,
      activeJob,
      notice: typeof req.query.notice === 'string' ? req.query.notice : null,
    }));
  }));

  app.get('/courses/:id/topics', wrap(async (req, res) => {
    const course = await requireCourse(courseIdFrom(req));
    if (!course.proposal || !Array.isArray(course.proposal.topics) || course.proposal.topics.length === 0) {
      throw new HttpError(409, 'The topics are not ready yet. Wait for the ingest to finish.');
    }
    res.type('html').send(renderTopicsPage({
      course,
      proposal: course.proposal,
      notice: typeof req.query.notice === 'string' ? req.query.notice : null,
    }));
  }));

  app.post('/courses/:id/topics', wrap(async (req, res) => {
    const course = await requireCourse(courseIdFrom(req));
    const proposalId = typeof req.body?.proposalId === 'string' ? req.body.proposalId : '';
    if (!course.proposal || course.proposal.id !== proposalId) {
      throw new HttpError(409, 'That topic list is out of date. Open the course and review the topics again.');
    }
    const topicIds = topicIdsFrom(req.body);
    if (topicIds.length === 0) throw new HttpError(400, 'Select at least one topic.');

    const selection = await store.saveSelection(course.id, proposalId, topicIds);
    if (!selection) throw new HttpError(400, 'None of the selected topics exist in this course.');

    const { job } = await jobs.start({ courseId: course.id, kind: 'pdf' });
    res.redirect(303, `/courses/${course.id}/runs/${job.id}?notice=${job.status === 'running' ? 'busy' : ''}`);
  }));

  app.post('/courses/:id/reingest', wrap(async (req, res) => {
    const course = await requireCourse(courseIdFrom(req));
    const { job } = await jobs.start({ courseId: course.id, kind: 'ingest', force: forceFrom(req.body) });
    res.redirect(303, `/courses/${course.id}/runs/${job.id}?notice=${job.status === 'running' ? 'busy' : ''}`);
  }));

  app.post('/courses/:id/delete', wrap(async (req, res) => {
    const course = await requireCourse(courseIdFrom(req));
    if (jobs.isRunning(course.id)) throw new HttpError(409, 'A job is running for this course. Try again when it finishes.');
    await store.deleteCourse(course.id);
    res.redirect(303, '/?notice=deleted');
  }));

  app.get('/courses/:id/runs/:jobId', wrap(async (req, res) => {
    const course = await requireCourse(courseIdFrom(req));
    const job = await jobs.get(jobIdFrom(req));
    if (!job || job.courseId !== course.id) throw new HttpError(404, 'That run was not found.');
    res.type('html').send(renderRunPage({ course, job }));
  }));

  app.get('/courses/:id/runs/:jobId/download', wrap(async (req, res, next) => {
    const course = await requireCourse(courseIdFrom(req));
    const job = await jobs.get(jobIdFrom(req));
    if (!job || job.courseId !== course.id) throw new HttpError(404, 'That run was not found.');
    if (job.kind !== 'pdf') throw new HttpError(409, 'This run did not produce a PDF.');
    if (job.status !== 'succeeded' || !job.result?.pdfPath) {
      throw new HttpError(409, 'The PDF is not ready yet.');
    }

    const resolvedOutput = path.resolve(outputDir);
    const pdfPath = path.resolve(job.result.pdfPath);
    if (pdfPath !== resolvedOutput && !pdfPath.startsWith(`${resolvedOutput}${path.sep}`)) {
      throw new HttpError(404, 'That PDF is outside the output folder.');
    }
    try {
      await stat(pdfPath);
    } catch {
      throw new HttpError(410, 'The PDF file is no longer on disk. Generate it again.');
    }

    const filename = `${safeFilename(course.title, 'course')}.pdf`;
    res.download(pdfPath, filename, (err) => {
      if (err && !res.headersSent) next(err);
    });
  }));

  app.get('/settings', wrap(async (_req, res) => {
    const settings = await loadForPage();
    res.type('html').send(renderSettingsPage({
      settings,
      paths: { dataDir, outputDir },
      notice: typeof _req.query.notice === 'string' ? _req.query.notice : null,
    }));
  }));

  // ---- JSON API ----------------------------------------------------------

  app.get('/health', wrap(async (_req, res) => {
    const base = {
      status: 'ok',
      nodeEnv: config.nodeEnv,
      uptimeSeconds: Math.round(process.uptime()),
    };
    try {
      const [settings, courses] = await Promise.all([loadForPage(), store.listCourses()]);
      res.json({
        ...base,
        model: settings.deepseek.model,
        hasDeepSeekKey: settings.deepseek.apiKey !== '',
        hasYouTubeKey: settings.youtube.apiKey !== '',
        courseCount: courses.length,
      });
    } catch (err) {
      warn(`[health] degraded: ${err.message}`);
      res.json({ ...base, status: 'degraded', courseCount: null });
    }
  }));

  app.get('/api/courses', wrap(async (_req, res) => {
    res.json({ courses: await store.listCourses() });
  }));

  app.post('/api/courses', wrap(async (req, res) => {
    const { course, duplicate, job } = await createCourseFromUrl(req.body?.url);
    res.status(duplicate ? 200 : 201).json({ course, duplicate, job });
  }));

  // Deprecated alias kept for the original scaffold's clients.
  app.post('/api/digest', wrap(async (req, res) => {
    const { course, duplicate, job } = await createCourseFromUrl(req.body?.url);
    res.status(duplicate ? 200 : 201).json({ course, duplicate, job, deprecated: '/api/courses' });
  }));

  app.get('/api/courses/:id', wrap(async (req, res) => {
    const course = await requireCourse(courseIdFrom(req));
    const [videos, courseJobs] = await Promise.all([
      store.listVideos(course.id),
      jobs.listByCourse(course.id, { limit: 50 }),
    ]);
    res.json({
      course,
      videos,
      proposal: course.proposal,
      selection: course.selection,
      jobs: courseJobs,
    });
  }));

  app.get('/api/courses/:id/topics', wrap(async (req, res) => {
    const course = await requireCourse(courseIdFrom(req));
    if (!course.proposal) throw new HttpError(409, 'The topics are not ready yet.');
    res.json({ proposal: course.proposal });
  }));

  app.post('/api/courses/:id/selection', wrap(async (req, res) => {
    const course = await requireCourse(courseIdFrom(req));
    if (!course.proposal) throw new HttpError(409, 'The topics are not ready yet.');
    const topicIds = topicIdsFrom(req.body);
    if (topicIds.length === 0) throw new HttpError(400, 'Select at least one topic.');

    const selection = await store.saveSelection(course.id, course.proposal.id, topicIds);
    if (!selection) throw new HttpError(400, 'None of the selected topics exist in this course.');
    const { job } = await jobs.start({ courseId: course.id, kind: 'pdf' });
    res.status(202).json({ selection, job });
  }));

  app.post('/api/courses/:id/reingest', wrap(async (req, res) => {
    const course = await requireCourse(courseIdFrom(req));
    const { job, duplicate } = await jobs.start({
      courseId: course.id,
      kind: 'ingest',
      force: forceFrom(req.body),
    });
    res.status(202).json({ job, duplicate });
  }));

  app.get('/api/courses/:id/jobs', wrap(async (req, res) => {
    const course = await requireCourse(courseIdFrom(req));
    res.json({ jobs: await jobs.listByCourse(course.id, { limit: 50 }) });
  }));

  app.get('/api/jobs/:id', wrap(async (req, res) => {
    const id = req.params.id;
    if (!JOB_ID.test(id)) throw new HttpError(404, 'That run was not found.');
    const job = await jobs.get(id);
    if (!job) throw new HttpError(404, 'That run was not found.');
    res.json({ job });
  }));

  app.get('/api/courses/:id/pdf', wrap(async (req, res) => {
    const course = await requireCourse(courseIdFrom(req));
    const courseJobs = await jobs.listByCourse(course.id, { limit: 100 });
    const job = courseJobs.find((entry) => entry.kind === 'pdf' && entry.status === 'succeeded' && entry.result?.pdfPath);
    if (!job) throw new HttpError(404, 'No PDF has been generated for this course yet.');

    try {
      await stat(job.result.pdfPath);
    } catch {
      throw new HttpError(410, 'The PDF file is no longer on disk. Generate it again.');
    }

    res.json({
      jobId: job.id,
      pdfPath: job.result.pdfPath,
      downloadUrl: `/courses/${course.id}/runs/${job.id}/download`,
      generatedAt: job.result.generatedAt ?? job.finishedAt,
      chapterCount: job.result.chapterCount ?? 0,
    });
  }));

  app.delete('/api/courses/:id', wrap(async (req, res) => {
    const course = await requireCourse(courseIdFrom(req));
    if (jobs.isRunning(course.id)) throw new HttpError(409, 'A job is running for this course.');
    await store.deleteCourse(course.id);
    res.status(204).end();
  }));

  // ---- Fallbacks ---------------------------------------------------------

  app.use((req, res) => {
    if (isApiPath(req)) {
      res.status(404).json({ error: `No route for ${req.method} ${req.path}` });
      return;
    }
    renderError(res, 404, `No page at ${req.method} ${req.path}.`);
  });

  app.use((err, req, res, _next) => {
    const status = Number.isInteger(err?.status) ? err.status : Number.isInteger(err?.statusCode) ? err.statusCode : 500;
    const expose = err?.expose === true || status < 500;
    let message = expose && typeof err?.message === 'string' && err.message !== ''
      ? err.message
      : 'Something failed while handling this request. The server log has the details.';

    if (err?.type === 'entity.parse.failed') message = 'The request body is not valid JSON.';

    if (status >= 500) {
      warn(`[error] ${req.method} ${req.originalUrl}: ${err?.stack ?? err}`);
    }

    if (res.headersSent) {
      res.end();
      return;
    }
    if (isApiPath(req) || wantsJson(req)) {
      res.status(status).json({ error: message });
      return;
    }
    renderError(res, status, message);
  });

  app.locals.depot = store;
  app.locals.runner = jobs;
  app.locals.pdfRenderer = renderer;
  app.locals.shutdown = async () => {
    await jobs.shutdown?.();
    await renderer.close?.();
  };

  return app;
}
