import assert from 'node:assert/strict';
import { test } from 'node:test';

import { renderBookHtml } from '../src/render-book.js';
import { makeSettings, vid } from './helpers.js';

function entry(overrides = {}) {
  return {
    topic: {
      id: 't1', order: 1, title: 'Memory', summary: 'How memory works.', videoIds: [vid(1)],
    },
    chapter: {
      title: 'Memory',
      intro: 'Intro paragraph.\n\nSecond intro paragraph.',
      sections: [{ heading: 'Arrays', body: 'First paragraph.\n\nSecond paragraph.' }],
      takeaways: ['Arrays are rows.', 'Indexes start at zero.'],
      citations: [vid(1)],
    },
    source: 'deepseek',
    sources: [{
      id: vid(1),
      title: 'Arrays and pointers',
      channel: 'CS50',
      url: `https://www.youtube.com/watch?v=${vid(1)}`,
      publishedAt: '2025-01-01T00:00:00Z',
    }],
    ...overrides,
  };
}

const COURSE = {
  title: 'CS50 2025',
  channelTitle: 'Harvard CS50',
  videoIds: [vid(1), vid(2)],
};

const GENERATED_AT = new Date('2026-01-02T03:04:05.000Z');

test('the book carries a cover, contents, chapters, key ideas and sources', () => {
  const html = renderBookHtml({
    course: COURSE,
    chapters: [entry()],
    settings: makeSettings(),
    generatedAt: GENERATED_AT,
  });

  assert.match(html, /^<!doctype html>/);
  assert.match(html, /<title>Course Companion — CS50 2025<\/title>/);
  assert.match(html, /class="cover"/);
  assert.match(html, /Harvard CS50/);
  assert.match(html, /Jan 2, 2026 · 2 videos · 1 chapters/);
  assert.match(html, /class="toc"/);
  assert.match(html, /<span class="summary">How memory works\.<\/span>/);
  assert.match(html, /class="chapter"/);
  assert.match(html, /<h1>Memory<\/h1>/);
  assert.match(html, /<p>First paragraph\.<\/p>/);
  assert.match(html, /<p>Second paragraph\.<\/p>/);
  assert.match(html, /<h2>Key ideas<\/h2>/);
  assert.match(html, /<li>Arrays are rows\.<\/li>/);
  assert.match(html, /class="sources"/);
  assert.match(html, new RegExp(`href="https://www\\.youtube\\.com/watch\\?v=${vid(1)}"`));
  assert.match(html, /<h2>Sources<\/h2>/);
  assert.equal(html.includes('<script>'), false);
});

test('every dynamic string is escaped and links are http(s) only', () => {
  const dangerous = '<script>alert("x")</script>';
  const html = renderBookHtml({
    course: { ...COURSE, title: dangerous, channelTitle: dangerous },
    chapters: [entry({
      topic: { id: 't1', order: 1, title: dangerous, summary: dangerous, videoIds: [vid(1)] },
      chapter: {
        title: dangerous,
        intro: dangerous,
        sections: [{ heading: dangerous, body: dangerous }],
        takeaways: [dangerous],
        citations: [vid(1)],
      },
      sources: [{
        id: vid(1),
        title: dangerous,
        channel: dangerous,
        url: 'javascript:alert(1)',
        publishedAt: '2025-01-01T00:00:00Z',
      }],
    })],
    settings: makeSettings(),
    generatedAt: GENERATED_AT,
  });

  assert.equal(html.includes('<script>'), false);
  assert.match(html, /&lt;script&gt;alert\(&quot;x&quot;\)&lt;\/script&gt;/);
  assert.match(html, /href="#"/);
  assert.equal(html.includes('javascript:alert'), false);
});

test('custom style values reach the stylesheet and unsafe values fall back', () => {
  const settings = makeSettings({
    pdf: {
      style: {
        fontFamily: "'Courier New', monospace",
        headingFontFamily: 'Arial, sans-serif',
        bodyFontSizePt: 14,
        lineHeight: 1.8,
        colors: { accent: '#123456', ink: 'not-a-colour' },
      },
    },
  });
  const html = renderBookHtml({ course: COURSE, chapters: [entry()], settings, generatedAt: GENERATED_AT });

  assert.match(html, /font-family: 'Courier New', monospace;/);
  assert.match(html, /--accent: #123456;/);
  assert.match(html, /--ink: #1f1b16;/);
  assert.match(html, /font-size: 14pt;/);
  assert.match(html, /line-height: 1\.8;/);

  const unsafe = renderBookHtml({
    course: COURSE,
    chapters: [entry()],
    settings: {
      pdf: {
        style: {
          fontFamily: 'x;}</style><script>alert(1)</script>',
          colors: { accent: 'red;} body{display:none' },
        },
      },
    },
    generatedAt: GENERATED_AT,
  });
  assert.equal(unsafe.includes('<script>'), false);
  assert.match(unsafe, /font-family: Georgia, serif;/);
  assert.match(unsafe, /--accent: #b4482c;/);
});

test('cover, contents and sources can be switched off', () => {
  const noCover = renderBookHtml({
    course: COURSE,
    chapters: [entry()],
    settings: makeSettings({ pdf: { includeCover: false } }),
    generatedAt: GENERATED_AT,
  });
  assert.equal(noCover.includes('class="cover"'), false);
  assert.match(noCover, /class="toc"/);

  const noToc = renderBookHtml({
    course: COURSE,
    chapters: [entry()],
    settings: makeSettings({ pdf: { includeToc: false } }),
    generatedAt: GENERATED_AT,
  });
  assert.equal(noToc.includes('class="toc"'), false);
  assert.match(noToc, /class="cover"/);

  const noSources = renderBookHtml({
    course: COURSE,
    chapters: [entry()],
    settings: makeSettings({ pdf: { style: { showVideoCitations: false } } }),
    generatedAt: GENERATED_AT,
  });
  assert.equal(noSources.includes('class="sources"'), false);
});

test('chapters written without a model are labelled in the book', () => {
  const html = renderBookHtml({
    course: COURSE,
    chapters: [entry({ source: 'fallback', chapter: { ...entry().chapter, citations: [] } })],
    settings: makeSettings(),
    generatedAt: GENERATED_AT,
  });
  assert.match(html, /Some chapters were assembled locally/);
  assert.match(html, /assembled from the transcripts because the AI writer was unavailable/);
});

test('only the chapters passed in appear, in the order given', () => {
  const second = entry({
    topic: { id: 't2', order: 2, title: 'Pointers', summary: '', videoIds: [vid(2)] },
    chapter: {
      title: 'Pointers', intro: '', sections: [], takeaways: [], citations: [vid(2)],
    },
    sources: [{ id: vid(2), title: 'Pointers', url: `https://www.youtube.com/watch?v=${vid(2)}` }],
  });
  const html = renderBookHtml({
    course: COURSE,
    chapters: [second],
    settings: makeSettings(),
    generatedAt: GENERATED_AT,
  });

  assert.match(html, /Pointers/);
  assert.equal(html.includes('>Memory<'), false);
  assert.equal(html.includes('How memory works.'), false);
});

test('an empty book still renders a valid document', () => {
  const html = renderBookHtml({ course: {}, chapters: [], settings: {}, generatedAt: GENERATED_AT });
  assert.match(html, /<!doctype html>/);
  assert.equal(html.includes('class="toc"'), false);
  assert.equal(html.includes('class="chapter"'), false);
  assert.match(html, /Course Companion/);
});
