import { escapeHtml, formatDate, safeHref } from './html.js';

const STYLES = `
  :root {
    color-scheme: light;
    --paper: #f4f0e4;
    --ink: #17130f;
    --muted: #5b5348;
    --rule: #241f19;
    --accent: #7c1d1d;
  }
  * { box-sizing: border-box; }
  html { background: var(--paper); }
  body {
    margin: 0;
    background: var(--paper);
    color: var(--ink);
    font: 18px/1.55 Georgia, "Iowan Old Style", "Palatino Linotype", "Times New Roman", serif;
    -webkit-font-smoothing: antialiased;
  }
  .page { max-width: 1120px; margin: 0 auto; padding: 26px 22px 64px; }
  a { color: var(--ink); text-decoration-thickness: 1px; text-underline-offset: 2px; }
  a:hover { color: var(--accent); }
  a:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }

  .masthead { text-align: center; border-top: 4px double var(--rule); border-bottom: 4px double var(--rule); padding: 14px 0 12px; }
  .kicker { margin: 0; font-size: 11px; letter-spacing: .34em; text-transform: uppercase; color: var(--muted); }
  .masthead h1 {
    margin: 6px 0 8px; font-size: clamp(2.8rem, 8.5vw, 6.4rem); line-height: .92;
    font-weight: 700; font-variant: small-caps; letter-spacing: .01em;
  }
  .strapline { margin: 0 auto; max-width: 60ch; font-style: italic; color: var(--muted); font-size: 15px; }
  .dateline {
    display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px;
    margin-top: 14px; border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule);
    padding: 6px 2px; font-size: 11px; letter-spacing: .18em; text-transform: uppercase;
  }

  main { margin-top: 26px; }
  .lead { border-bottom: 2px solid var(--rule); padding-bottom: 26px; }
  .story-label {
    margin: 0 0 8px; font-size: 11px; letter-spacing: .3em; text-transform: uppercase; color: var(--accent);
  }
  .lead h2 {
    margin: 0 0 10px; font-size: clamp(2rem, 5.4vw, 3.6rem); line-height: 1.02; letter-spacing: -.01em;
  }
  .deck { margin: 0 0 10px; font-size: clamp(1.05rem, 2.2vw, 1.3rem); font-style: italic; color: #2f2922; }
  .byline { margin: 0 0 18px; font-size: 12px; letter-spacing: .14em; text-transform: uppercase; color: var(--muted); }
  .byline .source { letter-spacing: .04em; text-transform: none; }
  .lead .body { columns: 2; column-gap: 2.2rem; column-rule: 1px solid rgba(36,31,25,.35); }
  .lead .body p { margin: 0 0 1em; text-align: justify; hyphens: auto; }
  .lead .body > p:first-child::first-letter {
    float: left; font-size: 3.6em; line-height: .82; padding: .06em .09em 0 0; font-weight: 700;
  }
  .pull-quote {
    margin: 22px 0; padding: 10px 0; border-top: 2px solid var(--rule); border-bottom: 2px solid var(--rule);
    font-size: 1.35rem; font-style: italic; text-align: center; break-inside: avoid;
  }
  .pull-quote cite { display: block; margin-top: 8px; font-size: 11px; font-style: normal; letter-spacing: .2em; text-transform: uppercase; color: var(--muted); }

  .stories {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
    gap: 0; margin-top: 26px; border-top: 1px solid var(--rule);
  }
  .stories > article { padding: 18px 20px; border-bottom: 1px solid rgba(36,31,25,.4); }
  .stories > article + article { border-left: 1px solid rgba(36,31,25,.4); }
  .stories h3 { margin: 0 0 8px; font-size: 1.35rem; line-height: 1.1; }
  .stories .deck { font-size: 1rem; }
  .stories .body p { margin: 0 0 .8em; }
  .stories .byline { margin-bottom: 10px; }

  .dispatches { margin-top: 30px; border-top: 3px double var(--rule); padding-top: 16px; }
  .dispatches h2 { margin: 0 0 12px; font-size: 13px; letter-spacing: .24em; text-transform: uppercase; }
  .dispatches ul { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 6px 26px; }
  .dispatches li { border-bottom: 1px dotted rgba(36,31,25,.5); padding: 6px 0; font-size: 15px; }
  .dispatches .where { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .1em; }

  .notice {
    margin: 20px 0; padding: 14px 16px; border: 2px solid var(--accent);
    font-size: 15px; background: #fbf5e9;
  }
  .notice h2 { margin: 0 0 8px; font-size: 15px; letter-spacing: .14em; text-transform: uppercase; }
  .notice ul { margin: 0; padding-left: 20px; }

  footer.colophon {
    margin-top: 36px; border-top: 1px solid var(--rule); padding-top: 12px;
    font-size: 12px; color: var(--muted); display: flex; flex-wrap: wrap; gap: 6px 18px; justify-content: space-between;
  }

  @media (max-width: 720px) {
    body { font-size: 17px; }
    .page { padding: 18px 14px 48px; }
    .lead .body { columns: 1; }
    .stories { grid-template-columns: 1fr; }
    .stories > article + article { border-left: 0; }
  }
  @media print {
    :root { --paper: #fff; }
    body { background: #fff; }
    .page { max-width: none; padding: 0; }
    a { text-decoration: none; }
  }
`;

function paragraphs(text) {
  return String(text ?? '')
    .split(/\n{2,}/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean)
    .map((paragraph) => `        <p>${escapeHtml(paragraph)}</p>`)
    .join('\n');
}

function sourceLine(article) {
  const site = escapeHtml(article.siteName || 'Unknown source');
  const date = article.publishedAt ? ` · ${escapeHtml(formatDate(article.publishedAt))}` : '';
  return `<span class="source">${site}${date}</span>`;
}

function storyBody(summary) {
  return `<div class="body">
${paragraphs(summary.summary)}
      </div>`;
}

function renderLead(story) {
  const { article, summary } = story;
  return `      <article class="lead">
        <p class="story-label">Lead story</p>
        <h2>${escapeHtml(summary.headline)}</h2>
        <p class="deck">${escapeHtml(summary.dek)}</p>
        <p class="byline">By the Digest Desk · ${sourceLine(article)}</p>
${storyBody(summary)}
${summary.pullQuote ? `        <blockquote class="pull-quote">“${escapeHtml(summary.pullQuote)}”<cite>From the dispatch</cite></blockquote>` : ''}
      </article>`;
}

function renderStory(story) {
  const { article, summary } = story;
  return `        <article>
          <h3>${escapeHtml(summary.headline)}</h3>
          <p class="deck">${escapeHtml(summary.dek)}</p>
          <p class="byline">${sourceLine(article)}</p>
${storyBody(summary)}
        </article>`;
}

function renderDispatches(articles) {
  if (articles.length === 0) return '';

  const items = articles
    .map((article) => `        <li><a href="${escapeHtml(safeHref(article.url))}" rel="noopener noreferrer">${escapeHtml(article.title || article.url)}</a> <span class="where">${escapeHtml(article.siteName || '')}</span></li>`)
    .join('\n');

  return `      <section class="dispatches" aria-labelledby="dispatches-heading">
        <h2 id="dispatches-heading">Also on the desk</h2>
        <ul>
${items}
        </ul>
      </section>`;
}

function renderWarningBox(edition) {
  const problems = edition.warnings ?? [];
  if (problems.length === 0) return '';

  const items = problems.slice(0, 12).map((warning) => `          <li>${escapeHtml(warning)}</li>`).join('\n');
  const more = problems.length > 12 ? `\n          <li>…and ${problems.length - 12} more.</li>` : '';

  return `      <div class="notice" role="note">
        <h2>Note from the desk</h2>
        <ul>
${items}${more}
        </ul>
      </div>`;
}

function issueNumber(runId) {
  return escapeHtml(String(runId ?? '').slice(-4).toUpperCase() || '0001');
}

/**
 * Render one edition as a self-contained 1920s-style newspaper page.
 *
 * All text is escaped and all links pass through `safeHref`; there is no
 * script, no remote font and no remote image, so the file opens from disk.
 */
export function renderNewspaper(edition) {
  const generatedAt = edition.generatedAt ? new Date(edition.generatedAt) : new Date();
  const longDate = generatedAt.toLocaleDateString('en-US', {
    weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
  });

  const stories = edition.stories ?? [];
  const [lead, ...rest] = stories;
  const remaining = edition.remaining ?? [];
  const counts = edition.counts ?? {};
  const llm = edition.llm ?? {};

  const leadHtml = lead ? renderLead(lead) : '';
  const restHtml = rest.length
    ? `      <section class="stories" aria-label="More stories">
${rest.map(renderStory).join('\n')}
      </section>`
    : '';

  const emptyNotice = stories.length === 0
    ? `      <div class="notice" role="alert">
        <h2>No dispatches could be fetched</h2>
        <p>Every saved article failed to yield readable text on this run. Check the notes below, then try again.</p>
      </div>`
    : '';

  const modelLine = llm.rankingSource === 'deepseek'
    ? 'Ranked and summarised by DeepSeek'
    : 'Ranked by recency and topic overlap; summaries written locally because the model was unavailable';

  const body = `<div class="page">
    <header class="masthead">
      <p class="kicker">Vol. I · No. ${issueNumber(edition.runId)}</p>
      <h1>The Daily Digest</h1>
      <p class="strapline">${escapeHtml(edition.theme ?? '')}</p>
      <p class="dateline">
        <span>${escapeHtml(longDate)}</span>
        <span>Price Two Cents</span>
      </p>
    </header>

    <main>
${emptyNotice}
${renderWarningBox(edition)}
${leadHtml}
${restHtml}
${renderDispatches(remaining)}
    </main>

    <footer class="colophon">
      <span>${escapeHtml(modelLine)}.</span>
      <span>${escapeHtml(String(counts.fetched ?? 0))} dispatches fetched · ${escapeHtml(String(counts.failed ?? 0))} failed · top ${escapeHtml(String(edition.topN ?? stories.length))} on the front page.</span>
      <span>Composed ${escapeHtml(generatedAt.toLocaleString('en-US'))}.</span>
    </footer>
  </div>`;

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(edition.headline || 'The Daily Digest')}</title>
<meta name="description" content="${escapeHtml(edition.theme ?? 'A digest of saved blog articles.')}">
<style>${STYLES}</style>
</head>
<body>
${body}
</body>
</html>`;
}
