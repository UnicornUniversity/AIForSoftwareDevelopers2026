import { escapeHtml, formatDate, safeHref } from './html.js';

function cssFamily(value, fallback) {
  const text = String(value ?? '');
  return /^[\w\s,'"-]{1,120}$/.test(text) ? text : fallback;
}

function cssColour(value, fallback) {
  return /^#[0-9a-fA-F]{6}$/.test(String(value ?? '')) ? value : fallback;
}

function px(value, fallback, min, max) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.min(Math.max(number, min), max);
}

function stylesFor(style = {}) {
  const ink = cssColour(style.colors?.ink, '#1f1b16');
  const muted = cssColour(style.colors?.muted, '#5d554a');
  const paper = cssColour(style.colors?.paper, '#fffdf8');
  const accent = cssColour(style.colors?.accent, '#b4482c');
  const rule = cssColour(style.colors?.rule, '#2a251e');
  const cover = cssColour(style.coverBackground, '#f3e9d2');
  const bodyFont = cssFamily(style.fontFamily, 'Georgia, serif');
  const headingFont = cssFamily(style.headingFontFamily, bodyFont);
  const size = px(style.bodyFontSizePt, 12, 8, 24);
  const lineHeight = px(style.lineHeight, 1.5, 1, 2.5);

  return `
  :root {
    --ink: ${ink};
    --muted: ${muted};
    --paper: ${paper};
    --accent: ${accent};
    --rule: ${rule};
    --cover: ${cover};
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: var(--paper); color: var(--ink); }
  body {
    font-family: ${bodyFont};
    font-size: ${size}pt;
    line-height: ${lineHeight};
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
  a { color: var(--ink); text-decoration-thickness: 1px; text-underline-offset: 2px; }
  .cover {
    background: var(--cover);
    border: 1px solid var(--rule);
    padding: 26mm 18mm 20mm;
    min-height: 230mm;
    display: flex;
    flex-direction: column;
    break-after: page;
  }
  .cover .kicker {
    margin: 0; font-family: ${headingFont}; font-size: 9pt; letter-spacing: .28em;
    text-transform: uppercase; color: var(--muted);
  }
  .cover h1 {
    margin: 12mm 0 4mm; font-family: ${headingFont}; font-size: 34pt; line-height: 1.02;
    letter-spacing: -.01em;
  }
  .cover .course { margin: 0; font-size: 17pt; font-style: italic; color: var(--ink); }
  .cover .subtitle { margin: 6mm 0 0; font-size: 12pt; color: var(--muted); }
  .cover .meta {
    margin-top: auto; padding-top: 10mm; border-top: 1px solid var(--rule);
    font-size: 9pt; letter-spacing: .12em; text-transform: uppercase; color: var(--muted);
  }
  .toc { break-after: page; padding-top: 4mm; }
  .toc h2, .chapter h2 {
    font-family: ${headingFont}; font-size: 10pt; letter-spacing: .24em; text-transform: uppercase;
    color: var(--muted); border-bottom: 1px solid var(--rule); padding-bottom: 3mm; margin: 0 0 6mm;
  }
  .toc ol { margin: 0; padding-left: 6mm; }
  .toc li { margin: 0 0 4mm; font-size: 13pt; }
  .toc .summary { display: block; font-size: 9.5pt; color: var(--muted); margin-top: 1mm; }
  .locally-written {
    margin: 8mm 0 0; padding: 4mm; border: 1px solid var(--rule); font-size: 9.5pt; color: var(--muted);
  }
  .chapter { break-before: page; }
  .chapter .number {
    margin: 0 0 2mm; font-family: ${headingFont}; font-size: 9pt; letter-spacing: .28em;
    text-transform: uppercase; color: var(--accent);
  }
  .chapter h1 { margin: 0 0 6mm; font-family: ${headingFont}; font-size: 25pt; line-height: 1.08; }
  .chapter .intro p:first-child { font-size: 13pt; font-style: italic; color: #3b342c; }
  .chapter .part { margin: 7mm 0 0; break-inside: avoid-page; }
  .chapter .part h2 {
    margin: 0 0 3mm; font-size: 16pt; letter-spacing: 0; text-transform: none; color: var(--ink);
    border-bottom: 0; padding-bottom: 0;
  }
  .chapter p { margin: 0 0 4mm; text-align: justify; hyphens: auto; }
  .takeaways { margin-top: 9mm; padding: 5mm; border-top: 2px solid var(--rule); border-bottom: 2px solid var(--rule); }
  .takeaways h2 { border: 0; padding: 0; margin: 0 0 3mm; }
  .takeaways ul { margin: 0; padding-left: 6mm; }
  .takeaways li { margin-bottom: 2mm; }
  .sources { margin-top: 9mm; font-size: 9pt; color: var(--muted); }
  .sources h2 { border: 0; padding: 0; margin: 0 0 3mm; }
  .sources ol { margin: 0; padding-left: 6mm; }
  .sources li { margin-bottom: 2mm; }
  .chapter-note { font-size: 9pt; color: var(--muted); font-style: italic; margin-top: 6mm; }
`;
}

function paragraphs(text) {
  return String(text ?? '')
    .split(/\n{2,}/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean)
    .map((paragraph) => `<p>${escapeHtml(paragraph)}</p>`)
    .join('\n      ');
}

function safeList(items, limit = 5) {
  return (Array.isArray(items) ? items : [])
    .filter((item) => typeof item === 'string' && item.trim() !== '')
    .slice(0, limit);
}

function renderSources(entry) {
  const chapter = entry.chapter ?? {};
  const cited = new Set(Array.isArray(chapter.citations) ? chapter.citations : []);
  const sources = (entry.sources ?? []).filter((source) => cited.size === 0 || cited.has(source.id));
  if (sources.length === 0) return '';

  const items = sources.map((source) => {
    const title = source.title || source.url;
    const meta = [source.channel, source.publishedAt ? formatDate(source.publishedAt) : '']
      .filter(Boolean)
      .map((part) => escapeHtml(part))
      .join(' · ');
    return `<li><a href="${escapeHtml(safeHref(source.url))}" rel="noopener noreferrer">${escapeHtml(title)}</a>${meta ? ` — ${meta}` : ''}</li>`;
  });

  return `
    <section class="sources">
      <h2>Sources</h2>
      <ol>${items.join('')}</ol>
    </section>`;
}

function renderChapter(entry, index) {
  const chapter = entry.chapter ?? {};
  const title = chapter.title || entry.topic?.title || `Chapter ${index + 1}`;
  const intro = chapter.intro || entry.topic?.summary || '';
  const sections = Array.isArray(chapter.sections) ? chapter.sections : [];
  const takeaways = safeList(chapter.takeaways, 5);

  const sectionsHtml = sections.map((section) => `
    <div class="part">
      <h2>${escapeHtml(section.heading)}</h2>
      ${paragraphs(section.body)}
    </div>`).join('');

  const takeawaysHtml = takeaways.length
    ? `
    <section class="takeaways">
      <h2>Key ideas</h2>
      <ul>${takeaways.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>
    </section>`
    : '';

  const note = entry.source === 'fallback'
    ? '<p class="chapter-note">This chapter was assembled from the transcripts because the AI writer was unavailable.</p>'
    : '';

  return `
  <article class="chapter">
    <p class="number">Chapter ${index + 1}</p>
    <h1>${escapeHtml(title)}</h1>
    <div class="intro">${paragraphs(intro)}</div>
    ${sectionsHtml}
    ${takeawaysHtml}
    ${renderSources(entry)}
    ${note}
  </article>`;
}

/**
 * The exact document handed to Chromium: self-contained, print-oriented, no
 * scripts or remote assets, and every dynamic string escaped.
 */
export function renderBookHtml({
  course = {},
  chapters = [],
  settings = {},
  generatedAt = new Date(),
} = {}) {
  const pdf = settings.pdf ?? {};
  const style = pdf.style ?? {};
  const includeCover = pdf.includeCover !== false;
  const includeToc = pdf.includeToc !== false;
  const showCitations = style.showVideoCitations !== false;

  const bookTitle = pdf.title || 'Course Companion';
  const subtitle = pdf.subtitle || '';
  const courseTitle = course.title || 'YouTube course';
  const date = formatDate(generatedAt);
  const videoCount = Array.isArray(course.videoIds) ? course.videoIds.length : 0;

  const cover = includeCover
    ? `
  <section class="cover">
    <p class="kicker">${escapeHtml(course.channelTitle || 'Course companion')}</p>
    <h1>${escapeHtml(bookTitle)}</h1>
    <p class="course">${escapeHtml(courseTitle)}</p>
    ${subtitle ? `<p class="subtitle">${escapeHtml(subtitle)}</p>` : ''}
    <div class="meta">${escapeHtml([date, `${videoCount} videos`, `${chapters.length} chapters`].filter(Boolean).join(' · '))}</div>
  </section>`
    : '';

  const toc = includeToc && chapters.length > 0
    ? `
  <section class="toc">
    <h2>Contents</h2>
    <ol>
${chapters.map((entry) => `      <li>${escapeHtml(entry.chapter?.title || entry.topic?.title || 'Chapter')}${entry.topic?.summary ? `<span class="summary">${escapeHtml(entry.topic.summary)}</span>` : ''}</li>`).join('\n')}
    </ol>
    ${chapters.some((entry) => entry.source === 'fallback') ? '<p class="locally-written">Some chapters were assembled locally from the transcripts because the AI writer was unavailable.</p>' : ''}
  </section>`
    : '';

  const body = chapters.map((entry, index) => {
    if (!showCitations) entry = { ...entry, sources: [] };
    return renderChapter(entry, index);
  }).join('\n');

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>${escapeHtml(bookTitle)} — ${escapeHtml(courseTitle)}</title>
<style>${stylesFor(style)}</style>
</head>
<body>
${cover}
${toc}
${body}
</body>
</html>`;
}
