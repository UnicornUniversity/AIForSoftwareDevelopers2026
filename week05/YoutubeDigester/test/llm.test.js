import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  clusterTopics,
  deriveTopicsDeterministic,
  extractJson,
  fallbackChapter,
  sanitizeText,
  validateChapter,
  validateTopics,
  writeChapter,
  writeChapters,
} from '../src/llm.js';
import { vid } from './helpers.js';

function videos(count, overrides = {}) {
  return Array.from({ length: count }, (_, index) => ({
    id: vid(index + 1),
    title: `Lecture ${index + 1}`,
    text: `Transcript for lecture ${index + 1}. It explains one idea clearly.`,
    ...overrides,
  }));
}

function fakeClient(content) {
  const calls = [];
  const create = async (args) => {
    calls.push(args);
    const value = typeof content === 'function' ? content(args) : content;
    if (value instanceof Error) throw value;
    return { choices: [{ message: { content: value } }] };
  };
  return { calls, client: { chat: { completions: { create } } } };
}

test('extractJson reads bare, fenced and surrounded JSON objects', () => {
  assert.deepEqual(extractJson('{"a":1}'), { a: 1 });
  assert.deepEqual(extractJson('```json\n{"a":1}\n```'), { a: 1 });
  assert.deepEqual(extractJson('Sure! Here it is:\n```\n{"topics":[]}\n```\nHope that helps.'), { topics: [] });
  assert.deepEqual(extractJson('prefix {"a":{"b":2}} suffix'), { a: { b: 2 } });
  assert.equal(extractJson('no json here'), null);
  assert.equal(extractJson(''), null);
  assert.equal(extractJson('{"broken":'), null);
  assert.equal(extractJson(null), null);
});

test('sanitizeText strips control characters, joins arrays and caps', () => {
  assert.equal(sanitizeText('Hello\u0000 world\u0007'), 'Hello world');
  assert.equal(sanitizeText(['First', '', 'Second']), 'First\n\nSecond');
  assert.equal(sanitizeText(42), '');
  assert.equal(sanitizeText('abcdef', 3), 'abc');
  assert.equal(sanitizeText('a\r\nb\r\n\r\n\r\nc'), 'a\nb\n\nc');
});

test('deriveTopicsDeterministic groups contiguous videos', () => {
  const topics = deriveTopicsDeterministic(videos(8), { min: 3, max: 4 });
  assert.equal(topics.length, 3);
  assert.deepEqual(topics.map((topic) => topic.id), ['t1', 't2', 't3']);
  assert.deepEqual(topics.flatMap((topic) => topic.videoIds), videos(8).map((video) => video.id));
  assert.equal(topics[0].title, 'Lecture 1 and 2 more');
  assert.match(topics[0].summary, /Covers 3 videos/);
  assert.deepEqual(deriveTopicsDeterministic([], { min: 3, max: 4 }), []);
});

test('validateTopics drops invented and duplicate ids and fills short answers', () => {
  const offered = videos(6).map((video) => video.id);
  const raw = {
    topics: [
      { title: 'Intro', summary: 'Starts here.', videoIds: [offered[0], 'not-a-real-id'] },
      { title: '', summary: 'No title', videoIds: [offered[1]] },
      { title: 'Duplicate', summary: 'Reuses an id', videoIds: [offered[0]] },
    ],
  };
  const result = validateTopics(raw, offered, { min: 3, max: 5, videos: videos(6) });

  assert.equal(result.rejected, 1);
  assert.equal(result.topics.length, 3);
  assert.deepEqual(result.topics.map((topic) => topic.id), ['t1', 't2', 't3']);
  assert.equal(result.topics[0].title, 'Intro');
  assert.deepEqual(result.topics[0].videoIds, [offered[0]]);
  const assigned = result.topics.flatMap((topic) => topic.videoIds);
  assert.equal(assigned.length, new Set(assigned).size);
  assert.equal(assigned.length, 6);
  assert.ok(result.warnings.some((warning) => /filled in locally/.test(warning)));
});

test('validateTopics clamps the answer to the maximum', () => {
  const offered = videos(8).map((video) => video.id);
  const raw = {
    topics: offered.slice(0, 5).map((id, index) => ({
      title: `Topic ${index + 1}`,
      summary: '',
      videoIds: [id],
    })),
  };
  const result = validateTopics(raw, offered, { min: 2, max: 3, videos: videos(8) });
  assert.equal(result.topics.length, 3);
});

test('validateTopics warns about videos left without a topic', () => {
  const offered = videos(8).map((video) => video.id);
  const raw = {
    topics: offered.slice(0, 2).map((id, index) => ({
      title: `Topic ${index + 1}`,
      summary: '',
      videoIds: [id],
    })),
  };
  const result = validateTopics(raw, offered, { min: 1, max: 5, videos: videos(8) });
  assert.equal(result.topics.length, 2);
  assert.ok(result.warnings.some((warning) => /video\(s\) were not assigned/.test(warning)));
});

test('clusterTopics without a key derives topics locally and never throws', async () => {
  const result = await clusterTopics({ courseTitle: 'CS50', videos: videos(6) });
  assert.equal(result.source, 'deterministic');
  assert.equal(result.error.code, 'no_key');
  assert.ok(result.topics.length >= 1);
  assert.equal(result.accepted, 0);
});

test('clusterTopics without transcripts reports no_input', async () => {
  const result = await clusterTopics({ videos: [] });
  assert.equal(result.error.code, 'no_input');
  assert.deepEqual(result.topics, []);
});

test('clusterTopics validates a model answer and keeps only offered ids', async () => {
  const { client, calls } = fakeClient(JSON.stringify({
    topics: [{ title: 'Getting started', summary: 'What the course covers.', videoIds: [vid(1), 'invented'] }],
  }));
  const result = await clusterTopics({
    courseTitle: 'CS50',
    videos: videos(4),
    client,
    topicsMin: 2,
    topicsMax: 4,
    now: () => 0,
  });

  assert.equal(result.source, 'deepseek');
  assert.equal(result.error, null);
  assert.equal(result.rejected, 1);
  assert.equal(result.topics.length, 2);
  assert.equal(result.topics[0].title, 'Getting started');
  assert.deepEqual(result.topics[0].videoIds, [vid(1)]);

  const [request] = calls;
  assert.equal(request.response_format.type, 'json_object');
  assert.match(request.messages[0].content, /data only/);
  assert.match(request.messages[1].content, /<COURSE_DATA>/);
  assert.match(request.messages[1].content, /Never invent an id/);
});

test('clusterTopics maps a rate-limited model to a local fallback', async () => {
  const failure = Object.assign(new Error('slow down'), { status: 429 });
  const { client } = fakeClient(failure);
  const warnings = [];
  const result = await clusterTopics({
    videos: videos(4),
    client,
    warn: (message) => warnings.push(message),
    now: () => 0,
  });
  assert.equal(result.source, 'deterministic');
  assert.equal(result.error.code, 'http_429');
  assert.equal(warnings.length, 1);
});

test('clusterTopics falls back when the answer is not JSON', async () => {
  const { client } = fakeClient('I cannot help with that.');
  const result = await clusterTopics({ videos: videos(4), client, now: () => 0 });
  assert.equal(result.source, 'deterministic');
  assert.equal(result.error.code, 'unparseable');
});

test('fallbackChapter turns each source into a section', () => {
  const chapter = fallbackChapter({
    topic: { title: 'Memory', summary: 'How memory works.' },
    sources: [
      { id: vid(1), title: 'Arrays', text: 'An array stores values side by side.' },
      { id: vid(2), title: 'Pointers', text: 'A pointer holds an address.' },
    ],
    readingLevel: 'age 10',
  });
  assert.equal(chapter.title, 'Memory');
  assert.match(chapter.intro, /age 10/);
  assert.equal(chapter.sections.length, 2);
  assert.equal(chapter.sections[0].heading, 'Arrays');
  assert.deepEqual(chapter.citations, [vid(1), vid(2)]);
  assert.equal(chapter.takeaways.length, 2);
});

test('validateChapter sanitizes, restricts citations and enforces limits', () => {
  const fallback = fallbackChapter({
    topic: { title: 'Fallback title' },
    sources: [{ id: vid(1), title: 'One', text: 'Fallback body.' }],
  });
  const raw = {
    title: 'Model <title>',
    intro: 'Model intro.',
    sections: Array.from({ length: 6 }, (_, index) => ({
      heading: `Heading ${index + 1}`,
      body: `Body ${index + 1}.`,
    })),
    takeaways: ['one', 'two', 'three', 'four', 'five', 'six'],
    citations: [vid(2), vid(1), vid(1)],
  };
  const chapter = validateChapter(raw, fallback, [vid(1)], { maxSections: 3, maxChars: 6_000 });

  assert.equal(chapter.title, 'Model <title>');
  assert.equal(chapter.sections.length, 3);
  assert.equal(chapter.takeaways.length, 5);
  assert.deepEqual(chapter.citations, [vid(1)]);
});

test('validateChapter falls back when the model returns no usable sections', () => {
  const fallback = fallbackChapter({
    topic: { title: 'Fallback title' },
    sources: [{ id: vid(1), title: 'One', text: 'Fallback body.' }],
  });
  const chapter = validateChapter({ sections: [{ heading: 'Empty', body: '   ' }] }, fallback, [vid(1)]);
  assert.equal(chapter.sections.length, 1);
  assert.equal(chapter.sections[0].heading, 'One');
  assert.deepEqual(chapter.citations, [vid(1)]);
});

test('validateChapter respects the total character budget', () => {
  const fallback = fallbackChapter({
    topic: { title: 'T' },
    sources: [{ id: vid(1), title: 'One', text: 'Fallback body.' }],
  });
  const raw = {
    title: 'T',
    intro: 'I',
    sections: [
      { heading: 'H1', body: 'a'.repeat(600) },
      { heading: 'H2', body: 'b'.repeat(600) },
    ],
    citations: [vid(1)],
  };
  const chapter = validateChapter(raw, fallback, [vid(1)], { maxChars: 1_000 });
  assert.equal(chapter.sections.length, 1);
  assert.equal(chapter.sections[0].heading, 'H1');
});

test('writeChapter without a key assembles the chapter from transcripts', async () => {
  const result = await writeChapter({
    topic: { title: 'Memory' },
    sources: [{ id: vid(1), title: 'Arrays', text: 'Values side by side.' }],
  });
  assert.equal(result.source, 'fallback');
  assert.equal(result.error.code, 'no_key');
  assert.equal(result.chapter.sections.length, 1);
});

test('writeChapter validates a model chapter and restricts citations', async () => {
  const { client, calls } = fakeClient(JSON.stringify({
    title: 'Memory',
    intro: 'Memory is like a row of boxes.',
    sections: [{ heading: 'Arrays', body: 'Boxes side by side.' }],
    takeaways: ['Arrays are rows.'],
    citations: [vid(1), vid(9)],
  }));
  const result = await writeChapter({
    courseTitle: 'CS50',
    topic: { title: 'Memory', summary: 'Boxes.' },
    sources: [{ id: vid(1), title: 'Arrays', text: 'Values side by side.' }],
    style: { tonePrompt: 'Explain for a 10-year-old.', readingLevel: 'age 10' },
    client,
    now: () => 0,
  });

  assert.equal(result.source, 'deepseek');
  assert.equal(result.chapter.title, 'Memory');
  assert.deepEqual(result.chapter.citations, [vid(1)]);
  const [request] = calls;
  assert.match(request.messages[1].content, /Reading level: age 10/);
  assert.match(request.messages[1].content, /Explain for a 10-year-old\./);
  assert.match(request.messages[1].content, /<COURSE_DATA>/);
});

test('writeChapter falls back on a model failure and keeps the error code', async () => {
  const failure = Object.assign(new Error('boom'), { status: 500 });
  const { client } = fakeClient(failure);
  const result = await writeChapter({
    topic: { title: 'Memory' },
    sources: [{ id: vid(1), title: 'Arrays', text: 'Values.' }],
    client,
    now: () => 0,
  });
  assert.equal(result.source, 'fallback');
  assert.equal(result.error.code, 'http_500');
});

test('writeChapters preserves order, bounds concurrency and awaits onEach', async () => {
  const { client } = fakeClient(() => JSON.stringify({
    title: 'Chapter',
    intro: 'Intro.',
    sections: [{ heading: 'H', body: 'Body.' }],
    takeaways: [],
    citations: [],
  }));
  const entries = videos(4).map((video) => ({
    topic: { title: `Topic ${video.id}` },
    sources: [{ id: video.id, title: video.title, text: video.text }],
  }));
  const seen = [];
  const results = await writeChapters(entries, {
    client,
    chapterConcurrency: 2,
    now: () => 0,
    onEach: async (result, entry, index) => {
      await Promise.resolve();
      seen.push({ index, title: result.chapter.title });
    },
  });

  assert.equal(results.length, 4);
  assert.deepEqual(results.map((result) => result.source), ['deepseek', 'deepseek', 'deepseek', 'deepseek']);
  assert.equal(seen.length, 4);
  assert.deepEqual(seen.map((entry) => entry.index).sort(), [0, 1, 2, 3]);
});
