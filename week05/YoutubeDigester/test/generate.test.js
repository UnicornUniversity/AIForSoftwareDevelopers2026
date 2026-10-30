import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { test } from 'node:test';

import { createDepot } from '../src/depot.js';
import { readJson } from '../src/files.js';
import { GenerateError, runPdfGeneration } from '../src/generate.js';
import { parseSeedUrl } from '../src/store.js';
import { QUIET, makeSettings, recordingPdfRenderer, tempDir, vid } from './helpers.js';

const SEED = parseSeedUrl('https://www.youtube.com/watch?v=dQw4w9WgXcQ');
const JOB_ID = 'job-pdf-1';
const FIXED_NOW = () => new Date('2026-01-02T03:04:05.000Z');
const IDS = [vid(1), vid(2), vid(3)];

function fakeLlm() {
  const calls = [];
  return {
    calls,
    async writeChapters(entries, options) {
      calls.push({ entries, options });
      const results = [];
      for (const [index, entry] of entries.entries()) {
        const result = {
          chapter: {
            title: `Chapter for ${entry.topic.title}`,
            intro: 'An intro.',
            sections: [{ heading: 'Section', body: 'A body.' }],
            takeaways: ['A takeaway.'],
            citations: entry.sources.map((source) => source.id),
          },
          source: 'deepseek',
          model: 'deepseek-chat',
          error: null,
          latencyMs: 1,
        };
        await options.onEach?.(result, entry, index);
        results.push(result);
      }
      return results;
    },
  };
}

async function setup({ selection = 'all' } = {}) {
  const dataDir = await tempDir();
  const outputDir = await tempDir('yd-out-');
  const depot = createDepot({ dataDir, warn: QUIET });
  const { course } = await depot.createCourse({ seed: SEED, title: 'CS50' });

  for (const [index, id] of IDS.entries()) {
    await depot.upsertVideo(course.id, {
      videoId: id,
      title: `Lecture ${index + 1}`,
      channel: 'CS50',
      url: `https://www.youtube.com/watch?v=${id}`,
      publishedAt: '2025-01-01T00:00:00Z',
      position: index,
    });
    await depot.writeTranscript(id, { title: `Lecture ${index + 1}` }, `Body for ${id}.`);
    await depot.updateVideo(id, { status: 'ok', wordCount: 3, excerpt: `Excerpt for ${id}.` });
  }

  const proposal = await depot.saveProposal(course.id, {
    source: 'deepseek',
    topics: [
      { id: 't1', order: 1, title: 'Memory', summary: 'How memory works.', videoIds: [IDS[0], IDS[1]] },
      { id: 't2', order: 2, title: 'Pointers', summary: 'Where things live.', videoIds: [IDS[2]] },
    ],
  });

  if (selection === 'all') {
    await depot.saveSelection(course.id, proposal.id, ['t2', 't1']);
  } else if (Array.isArray(selection)) {
    await depot.saveSelection(course.id, proposal.id, selection);
  }

  return {
    depot,
    outputDir,
    courseId: course.id,
    proposal,
    course: await depot.getCourse(course.id),
  };
}

function run(depot, courseId, { outputDir, pdfRenderer, llm, settings = makeSettings(), signal } = {}) {
  const updates = [];
  const warnings = [];
  const outcome = runPdfGeneration({
    courseId,
    jobId: JOB_ID,
    depot,
    settings,
    pdfRenderer: pdfRenderer ?? recordingPdfRenderer(),
    outputDir,
    llm,
    signal,
    update: (patch) => updates.push(patch),
    addWarning: (message) => warnings.push(message),
    now: FIXED_NOW,
  });
  return { outcome, updates, warnings };
}

test('selected topics become one PDF in proposal order', async () => {
  const { depot, outputDir, courseId } = await setup();
  const renderer = recordingPdfRenderer();
  const llm = fakeLlm();
  const { outcome, updates, warnings } = run(depot, courseId, { outputDir, pdfRenderer: renderer, llm });

  const { result } = await outcome;
  const expectedPdf = path.join(outputDir, courseId, `${JOB_ID}.pdf`);
  assert.deepEqual(result, {
    courseId,
    jobId: JOB_ID,
    pdfPath: expectedPdf,
    chapterCount: 2,
    topicCount: 2,
    generatedAt: '2026-01-02T03:04:05.000Z',
    chapterSources: { deepseek: 2 },
  });
  assert.match(await readFile(expectedPdf, 'utf8'), /^%PDF/);

  const stored = await depot.getCourse(courseId);
  assert.equal(stored.status, 'complete');
  assert.equal(stored.stage, 'done');
  assert.equal(stored.error, null);

  const [call] = llm.calls;
  assert.deepEqual(call.entries.map((entry) => entry.topic.id), ['t1', 't2']);
  assert.deepEqual(call.entries[0].sources.map((source) => source.id), [IDS[0], IDS[1]]);
  assert.equal(call.entries[0].sources[0].text, `Body for ${IDS[0]}.`);
  assert.equal(call.options.courseTitle, 'CS50');
  assert.equal(typeof call.options.onEach, 'function');

  const chapters = await readJson(path.join(depot.paths.runsDir, JOB_ID, 'chapters.json'));
  assert.deepEqual(chapters.map((chapter) => chapter.topicId), ['t1', 't2']);
  assert.deepEqual(chapters.map((chapter) => chapter.source), ['deepseek', 'deepseek']);
  assert.deepEqual(chapters.map((chapter) => chapter.title), ['Memory', 'Pointers']);

  const html = await readFile(path.join(depot.paths.runsDir, JOB_ID, 'digest.html'), 'utf8');
  assert.match(html, /<h1>Chapter for Memory<\/h1>/);
  assert.ok(html.indexOf('Chapter for Memory') < html.indexOf('Chapter for Pointers'));

  assert.equal(renderer.calls.length, 1);
  const renderCall = renderer.calls[0];
  assert.equal(renderCall.html, html);
  assert.equal(renderCall.format, 'A4');
  assert.equal(renderCall.displayHeaderFooter, true);
  assert.match(renderCall.footerTemplate, /pageNumber/);
  assert.deepEqual(renderCall.margins, { top: '20mm', right: '18mm', bottom: '20mm', left: '18mm' });
  assert.deepEqual(warnings, []);

  const stages = updates.map((patch) => patch.stage).filter(Boolean);
  assert.deepEqual(stages, ['chapters', 'rendering_html', 'rendering_pdf']);
});

test('only the confirmed topics are written', async () => {
  const { depot, outputDir, courseId } = await setup({ selection: ['t2'] });
  const llm = fakeLlm();
  const { outcome } = run(depot, courseId, { outputDir, llm });

  const { result } = await outcome;
  assert.equal(result.chapterCount, 1);
  assert.equal(result.topicCount, 1);
  assert.equal(llm.calls[0].entries.length, 1);
  assert.equal(llm.calls[0].entries[0].topic.id, 't2');

  const html = await readFile(path.join(depot.paths.runsDir, JOB_ID, 'digest.html'), 'utf8');
  assert.match(html, /Chapter for Pointers/);
  assert.equal(html.includes('Chapter for Memory'), false);
});

test('without a selection the PDF is refused before any chapter work', async () => {
  const { depot, outputDir, courseId } = await setup({ selection: 'none' });
  const llm = fakeLlm();
  const { outcome } = run(depot, courseId, { outputDir, llm });

  await assert.rejects(outcome, (err) => {
    assert.ok(err instanceof GenerateError);
    assert.equal(err.code, 'no_selection');
    return true;
  });
  assert.equal(llm.calls.length, 0);
  assert.equal((await depot.getCourse(courseId)).status, 'ready');
});

test('a selection that no longer matches the proposal is invalid', async () => {
  const { depot, outputDir, courseId, proposal } = await setup({ selection: 'none' });
  await depot.updateCourse(courseId, {
    selection: { proposalId: proposal.id, topicIds: ['gone'], confirmedAt: '2026-01-01T00:00:00.000Z' },
  });
  const llm = fakeLlm();
  const { outcome } = run(depot, courseId, { outputDir, llm });

  await assert.rejects(outcome, (err) => err.code === 'invalid_selection');
  assert.equal(llm.calls.length, 0);
});

test('without a DeepSeek key the PDF is assembled from transcripts', async () => {
  const { depot, outputDir, courseId } = await setup();
  const renderer = recordingPdfRenderer();
  const { outcome, warnings } = run(depot, courseId, {
    outputDir,
    pdfRenderer: renderer,
    settings: makeSettings({ deepseek: { apiKey: '' } }),
  });

  const { result } = await outcome;
  assert.deepEqual(result.chapterSources, { fallback: 2 });
  assert.equal(warnings.length, 2);
  assert.ok(warnings.every((warning) => /No DeepSeek API key/.test(warning)));

  const html = await readFile(path.join(depot.paths.runsDir, JOB_ID, 'digest.html'), 'utf8');
  assert.match(html, /assembled from the transcripts because the AI writer was unavailable/);
});

test('a renderer failure keeps the chapters and resets the course to ready', async () => {
  const { depot, outputDir, courseId } = await setup();
  const { outcome } = run(depot, courseId, {
    outputDir,
    pdfRenderer: recordingPdfRenderer({ fail: true }),
    llm: fakeLlm(),
  });

  await assert.rejects(outcome, (err) => err.code === 'render_failed');

  const stored = await depot.getCourse(courseId);
  assert.equal(stored.status, 'ready');
  assert.equal(stored.error, 'The PDF could not be generated.');

  const chapters = await readJson(path.join(depot.paths.runsDir, JOB_ID, 'chapters.json'));
  assert.equal(chapters.length, 2);
  const html = await readFile(path.join(depot.paths.runsDir, JOB_ID, 'digest.html'), 'utf8');
  assert.match(html, /Chapter for Memory/);
});

test('a missing renderer fails with pdf_unavailable', async () => {
  const { depot, outputDir, courseId } = await setup();
  const { outcome } = run(depot, courseId, { outputDir, llm: fakeLlm(), pdfRenderer: {} });
  await assert.rejects(outcome, (err) => err.code === 'pdf_unavailable');
  assert.equal((await depot.getCourse(courseId)).status, 'ready');
});

test('an aborted generation stops before writing chapters', async () => {
  const { depot, outputDir, courseId } = await setup();
  const controller = new AbortController();
  controller.abort();
  const llm = fakeLlm();
  const { outcome } = run(depot, courseId, { outputDir, llm, signal: controller.signal });

  await assert.rejects(outcome, (err) => err.code === 'cancelled');
  assert.equal(llm.calls.length, 0);
  assert.equal((await depot.getCourse(courseId)).status, 'ready');
});
