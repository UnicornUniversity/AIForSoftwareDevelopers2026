import { escapeHtml, formatDate, formatDateTime, hostOf, safeHref } from './html.js';

const STATUS_LABELS = {
  pending: 'Waiting',
  ok: 'Archived',
  failed: 'Failed',
  blocked: 'Blocked',
};

const NOTICES = {
  added: 'Added to the desk. It will be fetched on the next run.',
  duplicate: 'That article is already in the collection.',
  deleted: 'Removed from the collection.',
  invalid: 'That URL could not be accepted.',
  notfound: 'That article was not in the collection.',
  empty: 'Add at least one article before composing an edition.',
};

const PHASE_LABELS = {
  starting: 'Preparing the desk',
  scrape: 'Fetching articles',
  rank: 'Choosing the front page',
  summarize: 'Writing the stories',
  render: 'Setting the type',
  done: 'Edition ready',
  failed: 'Run failed',
};

const STYLES = `
  :root {
    color-scheme: light;
    --paper: #f4f0e6;
    --ink: #171512;
    --muted: #5c554a;
    --rule: #2a251e;
    --accent: #7a1f1f;
    --panel: #fbf8f0;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--paper);
    color: var(--ink);
    font: 17px/1.5 Georgia, "Iowan Old Style", "Palatino Linotype", "Times New Roman", serif;
  }
  .sheet { max-width: 1040px; margin: 0 auto; padding: 28px 20px 64px; }
  .masthead { text-align: center; border-bottom: 3px double var(--rule); padding-bottom: 14px; }
  .masthead .kicker {
    font-size: 12px; letter-spacing: .22em; text-transform: uppercase; color: var(--muted); margin: 0 0 4px;
  }
  .masthead h1 {
    font-size: clamp(2rem, 5vw, 3.2rem); line-height: 1; margin: 0;
    font-variant: small-caps; letter-spacing: .02em;
  }
  .masthead .sub { margin: 8px 0 0; font-style: italic; color: var(--muted); }
  .notice {
    margin: 18px 0 0; padding: 10px 14px; border: 1px solid var(--rule);
    background: var(--panel); font-size: 15px;
  }
  h2 {
    font-size: 15px; letter-spacing: .16em; text-transform: uppercase;
    border-bottom: 1px solid var(--rule); padding-bottom: 6px; margin: 34px 0 14px;
  }
  .add-form { display: flex; flex-wrap: wrap; gap: 10px; align-items: end; }
  .add-form label { display: block; font-size: 12px; letter-spacing: .12em; text-transform: uppercase; color: var(--muted); }
  .add-form input[type="url"] {
    width: min(560px, 100%); padding: 9px 11px; font: inherit; color: var(--ink);
    background: #fffdf7; border: 1px solid var(--rule); border-radius: 2px;
  }
  button {
    font: inherit; padding: 9px 16px; cursor: pointer; border-radius: 2px;
    border: 1px solid var(--rule); background: var(--ink); color: var(--paper);
  }
  button.ghost { background: transparent; color: var(--ink); }
  button:disabled { opacity: .45; cursor: not-allowed; }
  button:focus-visible, a:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
  .progress { color: var(--muted); font-size: 14px; }
  ul.warnings { margin: 0; padding-left: 22px; font-size: 15px; }
  ul.warnings li { margin-bottom: 4px; }
  ol.headlines { padding-left: 22px; }
  ol.headlines li { margin-bottom: 8px; }
  .table-wrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 15px; }
  th, td { text-align: left; padding: 9px 8px; border-bottom: 1px solid rgba(42,37,30,.25); vertical-align: top; }
  th { font-size: 11px; letter-spacing: .12em; text-transform: uppercase; color: var(--muted); font-weight: normal; }
  td.title a { color: var(--ink); text-decoration-thickness: 1px; }
  td.title .url { display: block; color: var(--muted); font-size: 13px; word-break: break-all; }
  .status { font-size: 12px; letter-spacing: .1em; text-transform: uppercase; }
  .status.ok { color: var(--rule); }
  .status.failed, .status.blocked { color: var(--accent); font-weight: bold; }
  .status.pending { color: var(--muted); }
  .error-line { color: var(--accent); font-size: 13px; }
  .empty { color: var(--muted); font-style: italic; }
  .sr-only {
    position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
    overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0;
  }
  .settings { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; }
  .settings div { border: 1px solid rgba(42,37,30,.35); background: var(--panel); padding: 12px 14px; }
  .settings dt { font-size: 11px; letter-spacing: .13em; text-transform: uppercase; color: var(--muted); }
  .settings dd { margin: 4px 0 0; }
  footer { margin-top: 40px; border-top: 1px solid var(--rule); padding-top: 12px; font-size: 13px; color: var(--muted); }
  @media (max-width: 560px) { body { font-size: 16px; } .sheet { padding: 20px 14px 48px; } }
`;

function layout({ title, body, refreshSeconds = null }) {
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(title)}</title>
${refreshSeconds ? `<meta http-equiv="refresh" content="${escapeHtml(String(refreshSeconds))}">` : ''}
<style>${STYLES}</style>
</head>
<body>
<div class="sheet">
${body}
<footer>BlogDigester — a local assignment desk. Saved URLs stay in <code>data/store.json</code>.</footer>
</div>
</body>
</html>`;
}

function renderArticleRow(article) {
  const title = article.title || article.url;
  const host = article.siteName || hostOf(article.url);
  const status = STATUS_LABELS[article.status] ?? article.status ?? 'Unknown';
  const statusClass = ['ok', 'failed', 'blocked', 'pending'].includes(article.status) ? article.status : 'pending';

  return `        <tr>
          <td class="title">
            <a href="${escapeHtml(safeHref(article.url))}" rel="noopener noreferrer">${escapeHtml(title)}</a>
            <span class="url">${escapeHtml(host)}${article.publishedAt ? ` · ${escapeHtml(formatDate(article.publishedAt))}` : ''}</span>
          </td>
          <td><span class="status ${statusClass}">${escapeHtml(status)}</span>${article.error ? `<br><span class="error-line">${escapeHtml(article.error)}</span>` : ''}</td>
          <td>${article.wordCount ? escapeHtml(article.wordCount.toLocaleString('en-US')) : '—'}</td>
          <td>${escapeHtml(article.fetchedAt ? formatDateTime(article.fetchedAt) : formatDate(article.addedAt))}</td>
          <td>
            <form method="post" action="/urls/${escapeHtml(article.id)}/delete">
              <button class="ghost" type="submit" aria-label="Remove ${escapeHtml(title)}">Remove</button>
            </form>
          </td>
        </tr>`;
}

export function renderHome({
  settings, articles, notice, activeRunId = null, latestRun = null, digestHref = null,
}) {
  const noticeText = notice ? NOTICES[notice] : '';
  const sorted = [...articles].sort((a, b) => String(b.addedAt).localeCompare(String(a.addedAt)));

  const rows = sorted.length
    ? `      <div class="table-wrap">
      <table>
        <thead><tr><th scope="col">Article</th><th scope="col">State</th><th scope="col">Words</th><th scope="col">Added / fetched</th><th scope="col"><span class="sr-only">Actions</span></th></tr></thead>
        <tbody>
${sorted.map(renderArticleRow).join('\n')}
        </tbody>
      </table>
      </div>`
    : '      <p class="empty">Nothing on the desk yet. Add the first article above.</p>';

  let runPanel;
  if (activeRunId) {
    runPanel = `      <p class="notice" role="status">An edition is being composed.
        <a href="/runs/${escapeHtml(encodeURIComponent(activeRunId))}">Follow the run</a>.</p>`;
  } else {
    runPanel = `      <form method="post" action="/run">
        <button type="submit"${articles.length === 0 ? ' disabled' : ''}>Compose the edition</button>
      </form>`;
  }

  let lastRunLine = '';
  if (latestRun && latestRun.status === 'failed' && !activeRunId) {
    lastRunLine = `<p class="notice" role="status">The last run did not produce a front page (${escapeHtml(latestRun.error ?? 'unknown error')}).
      <a href="/runs/${escapeHtml(encodeURIComponent(latestRun.runId))}">See the run report</a>.</p>`;
  }

  // digestHref is an app-relative path we built ourselves; safeHref is for
  // external article URLs and would reject it.
  const digestLink = digestHref
    ? `<p>Latest edition: <a href="${escapeHtml(digestHref)}">${escapeHtml(digestHref)}</a></p>`
    : '<p class="empty">No edition has been composed yet.</p>';

  const body = `  <header class="masthead">
    <p class="kicker">BlogDigester · Assignment Desk</p>
    <h1>The Daily Digest</h1>
    <p class="sub">Collect articles, re-read them on every run, and set the front page.</p>
  </header>
${noticeText ? `  <p class="notice" role="status">${escapeHtml(noticeText)}</p>` : ''}

  <h2>Add an article</h2>
  <form class="add-form" method="post" action="/urls">
    <div>
      <label for="url">Article URL</label>
      <input id="url" name="url" type="url" required placeholder="https://example.com/post" autocomplete="off">
    </div>
    <button type="submit">Add to the desk</button>
  </form>

  <h2>The collection (${articles.length})</h2>
${rows}

  <h2>Edition settings</h2>
  <dl class="settings">
    <div><dt>Theme</dt><dd>${escapeHtml(settings.theme)}</dd></div>
    <div><dt>Stories on the front page</dt><dd>${escapeHtml(String(settings.topN))}</dd></div>
    <div><dt>Settings file</dt><dd><code>settings.json</code></dd></div>
  </dl>

  <h2>Compose</h2>
${runPanel}
${lastRunLine}
  ${digestLink}`;

  return layout({ title: 'The Daily Digest — Assignment Desk', body });
}

function renderWarnings(warnings) {
  if (!Array.isArray(warnings) || warnings.length === 0) return '';
  return `  <h2>Notes</h2>
  <ul class="warnings">
${warnings.map((warning) => `    <li>${escapeHtml(warning)}</li>`).join('\n')}
  </ul>`;
}

export function renderRunPage({ run, digestHref = null }) {
  const running = run.status === 'running';
  const failed = run.status === 'failed';
  const result = run.result ?? {};
  const warnings = result.warnings ?? [];

  const progress = run.progress ?? { phase: run.phase, completed: 0, total: 0 };
  const phaseLabel = PHASE_LABELS[run.phase] ?? run.phase ?? 'Working';
  const countLine = progress.total > 0
    ? `<p class="progress">${escapeHtml(String(progress.completed))} of ${escapeHtml(String(progress.total))} complete.</p>`
    : '';

  let outcome;
  if (running) {
    outcome = `<p class="notice" role="status">${escapeHtml(phaseLabel)}… This page refreshes itself.</p>`;
  } else if (failed) {
    outcome = `<p class="notice" role="alert">The run did not finish: ${escapeHtml(result.error ?? run.error ?? 'unknown error')}.</p>`;
  } else {
    outcome = `<p class="notice" role="status">The edition is ready.
      <a href="${escapeHtml(digestHref ?? '/output/index.html')}">Read the front page</a>.</p>`;
  }

  const counts = result.counts
    ? `<p class="empty">${escapeHtml(String(result.counts.fetched ?? 0))} articles fetched, ${escapeHtml(String(result.counts.failed ?? 0))} failed.</p>`
    : '';

  const stories = Array.isArray(result.stories) && result.stories.length
    ? `  <h2>On the front page</h2>
  <ol class="headlines">
${result.stories.map((story) => `    <li>${escapeHtml(story.headline)} — <a href="${escapeHtml(safeHref(story.url))}" rel="noopener noreferrer">${escapeHtml(story.url)}</a></li>`).join('\n')}
  </ol>`
    : '';

  const body = `  <header class="masthead">
    <p class="kicker">BlogDigester · Run Report</p>
    <h1>The Daily Digest</h1>
    <p class="sub">Run ${escapeHtml(run.runId)} · started ${escapeHtml(formatDateTime(run.startedAt))}${run.finishedAt ? ` · finished ${escapeHtml(formatDateTime(run.finishedAt))}` : ''}</p>
  </header>
  <h2>${escapeHtml(phaseLabel)}</h2>
${outcome}
${countLine}
${counts}
${stories}
${renderWarnings(warnings)}
  <p><a href="/">Back to the desk</a></p>`;

  return layout({
    title: `Run ${run.runId} — The Daily Digest`,
    body,
    refreshSeconds: running ? 2 : null,
  });
}

export function renderErrorPage({ status, message }) {
  const body = `  <header class="masthead">
    <p class="kicker">BlogDigester · Assignment Desk</p>
    <h1>The Daily Digest</h1>
  </header>
  <h2>Error ${escapeHtml(status)}</h2>
  <p class="notice" role="alert">${escapeHtml(message)}</p>
  <p><a href="/">Back to the desk</a></p>`;

  return layout({ title: `Error ${status} — The Daily Digest`, body });
}
