import { escapeHtml, formatDate, formatDateTime, hostOf, safeHref } from './html.js';

const COURSE_STATUS = {
  pending: 'Waiting',
  discovering: 'Discovering the course',
  transcribing: 'Reading transcripts',
  clustering: 'Grouping topics',
  ready: 'Topics ready',
  generating: 'Writing the PDF',
  complete: 'PDF ready',
  failed: 'Failed',
};

const VIDEO_STATUS = {
  pending: 'Pending',
  ok: 'Transcript stored',
  no_transcript: 'No transcript',
  failed: 'Failed',
};

const JOB_STATUS = {
  queued: 'Queued',
  running: 'Running',
  succeeded: 'Finished',
  failed: 'Failed',
};

const NOTICES = {
  started: 'Course added. Discovery has started; this page will refresh itself.',
  duplicate: 'That course is already in the collection.',
  deleted: 'Course removed.',
  reingested: 'Ingest restarted in the background.',
  selected: 'Topics confirmed. The PDF is being prepared.',
  invalid: 'That request could not be accepted.',
  notfound: 'That course or job was not found.',
  busy: 'A job is already running for this course.',
};

const STAGES = {
  queued: 'Waiting for a free slot',
  starting: 'Starting',
  discovering: 'Finding the course videos',
  metadata: 'Loading video details',
  transcribing: 'Fetching transcripts',
  clustering: 'Grouping the material into topics',
  chapters: 'Writing the chapters',
  rendering_html: 'Laying out the book',
  rendering_pdf: 'Rendering the PDF',
  done: 'Finished',
  failed: 'Failed',
  cancelled: 'Cancelled',
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
  .masthead h1 { font-size: clamp(2rem, 5vw, 3.2rem); line-height: 1; margin: 0; font-variant: small-caps; }
  .masthead .sub { margin: 8px 0 0; font-style: italic; color: var(--muted); }
  .masthead a { color: inherit; }
  .notice {
    margin: 18px 0 0; padding: 10px 14px; border: 1px solid var(--rule);
    background: var(--panel); font-size: 15px;
  }
  .notice.alert { border-color: var(--accent); color: var(--accent); }
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
  .table-wrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 15px; }
  th, td { text-align: left; padding: 9px 8px; border-bottom: 1px solid rgba(42,37,30,.25); vertical-align: top; }
  th { font-size: 11px; letter-spacing: .12em; text-transform: uppercase; color: var(--muted); font-weight: normal; }
  td.title a { color: var(--ink); text-decoration-thickness: 1px; }
  td.title .url { display: block; color: var(--muted); font-size: 13px; word-break: break-all; }
  .status { font-size: 12px; letter-spacing: .1em; text-transform: uppercase; }
  .status.ok, .status.complete, .status.ready, .status.succeeded { color: var(--rule); }
  .status.failed, .status.no_transcript, .status.blocked { color: var(--accent); font-weight: bold; }
  .status.pending, .status.queued, .status.running { color: var(--muted); }
  .error-line { color: var(--accent); font-size: 13px; }
  .empty { color: var(--muted); font-style: italic; }
  .actions { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-top: 14px; }
  .actions form { margin: 0; }
  .course-card { border: 1px solid rgba(42,37,30,.35); background: var(--panel); padding: 14px 16px; margin-bottom: 12px; }
  .course-card h3 { margin: 0 0 4px; font-size: 1.2rem; }
  .course-card .meta { color: var(--muted); font-size: 13px; }
  .topics { list-style: none; margin: 0; padding: 0; }
  .topics li { border: 1px solid rgba(42,37,30,.35); background: var(--panel); padding: 12px 14px; margin-bottom: 10px; }
  .topics label { display: flex; gap: 10px; align-items: start; cursor: pointer; }
  .topics input { margin-top: 5px; }
  .topics strong { display: block; font-size: 1.05rem; }
  .topics .summary { display: block; color: var(--muted); font-size: 14px; margin-top: 4px; }
  .topics .count { display: block; font-size: 12px; letter-spacing: .1em; text-transform: uppercase; color: var(--muted); margin-top: 6px; }
  .key-state { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; }
  .key-state div { border: 1px solid rgba(42,37,30,.35); background: var(--panel); padding: 12px 14px; }
  .key-state dt { font-size: 11px; letter-spacing: .13em; text-transform: uppercase; color: var(--muted); }
  .key-state dd { margin: 4px 0 0; }
  pre.settings {
    background: #fffdf7; border: 1px solid var(--rule); padding: 14px; overflow-x: auto;
    font-size: 13px; line-height: 1.45;
  }
  .sr-only {
    position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
    overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0;
  }
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
<footer>YoutubeDigester — a local course reader. Transcripts stay in <code>data/</code>, PDFs in <code>output/</code>.</footer>
</div>
</body>
</html>`;
}

function noticeLine(notice) {
  const text = notice ? NOTICES[notice] ?? null : null;
  return text ? `  <p class="notice" role="status">${escapeHtml(text)}</p>` : '';
}

function warningsBlock(warnings) {
  if (!Array.isArray(warnings) || warnings.length === 0) return '';
  return `  <h2>Notes</h2>
  <ul class="warnings">
${warnings.map((warning) => `    <li>${escapeHtml(warning)}</li>`).join('\n')}
  </ul>`;
}

function formatDuration(seconds) {
  const total = Number(seconds);
  if (!Number.isFinite(total) || total <= 0) return '—';
  const hours = Math.floor(total / 3600);
  const minutes = Math.round((total % 3600) / 60);
  return hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`;
}

function statusClass(status) {
  return ['ok', 'complete', 'ready', 'succeeded', 'failed', 'no_transcript', 'blocked', 'pending', 'queued', 'running']
    .includes(status) ? status : 'pending';
}

function renderCourseRow(course) {
  const status = COURSE_STATUS[course.status] ?? course.status ?? 'Unknown';
  return `        <tr>
          <td class="title">
            <a href="/courses/${escapeHtml(course.id)}">${escapeHtml(course.title)}</a>
            <span class="url">${escapeHtml(course.seed?.url ?? '')}</span>
          </td>
          <td><span class="status ${escapeHtml(statusClass(course.status))}">${escapeHtml(status)}</span></td>
          <td>${escapeHtml(String(course.videoIds?.length ?? 0))}</td>
          <td>${escapeHtml(String(course.proposal?.topics?.length ?? 0))}</td>
          <td>${escapeHtml(course.updatedAt ? formatDateTime(course.updatedAt) : '')}</td>
        </tr>`;
}

export function renderHome({
  courses = [], settings = {}, hasYouTubeKey = false, hasDeepSeekKey = false, notice = null,
}) {
  const sorted = [...courses].sort((a, b) => String(b.updatedAt ?? b.createdAt ?? '').localeCompare(String(a.updatedAt ?? a.createdAt ?? '')));
  const rows = sorted.length
    ? `      <div class="table-wrap">
      <table>
        <thead><tr><th scope="col">Course</th><th scope="col">State</th><th scope="col">Videos</th><th scope="col">Topics</th><th scope="col">Updated</th></tr></thead>
        <tbody>
${sorted.map(renderCourseRow).join('\n')}
        </tbody>
      </table>
      </div>`
    : '      <p class="empty">No courses yet. Paste the first lecture of a course above.</p>';

  const keyLine = !hasYouTubeKey || !hasDeepSeekKey
    ? `  <p class="notice" role="status">${!hasYouTubeKey && !hasDeepSeekKey
      ? 'No API keys are configured. The app can store the single video you add and build a plain PDF, but it cannot discover a course or ask DeepSeek to write it.'
      : !hasYouTubeKey
        ? 'No YouTube API key is configured, so only the single video you add can be read.'
        : 'No DeepSeek API key is configured, so topics and chapters will be assembled locally.'}
      <a href="/settings">See settings</a>.</p>`
    : '';

  const body = `  <header class="masthead">
    <p class="kicker">YoutubeDigester · Course Companion</p>
    <h1>Turn a course into a book</h1>
    <p class="sub">Add the first lecture. The app finds the rest of the course, reads the transcripts, and listens while you choose the topics.</p>
  </header>
${noticeLine(notice)}
${keyLine}

  <h2>Add a course</h2>
  <form class="add-form" method="post" action="/courses">
    <div>
      <label for="url">First video or playlist URL</label>
      <input id="url" name="url" type="url" required placeholder="https://www.youtube.com/watch?v=..." autocomplete="off">
    </div>
    <button type="submit">Scan the course</button>
  </form>

  <h2>Courses (${courses.length})</h2>
${rows}

  <h2>How it works</h2>
  <dl class="key-state">
    <div><dt>Discovery</dt><dd>Playlist first, then a matching channel playlist or search</dd></div>
    <div><dt>Transcripts</dt><dd>Public captions stored as Markdown in <code>data/videos/</code></dd></div>
    <div><dt>PDF style</dt><dd>${escapeHtml(settings.pdf?.style?.name ?? 'Explain to a curious 10-year-old')}</dd></div>
    <div><dt>Settings</dt><dd><a href="/settings">Keys and PDF style</a></dd></div>
  </dl>`;

  return layout({ title: 'YoutubeDigester — Course Companion', body });
}

function renderVideoRow(video) {
  const title = video.title || video.url || video.id;
  const status = VIDEO_STATUS[video.status] ?? video.status ?? 'Unknown';
  return `        <tr>
          <td class="title">
            <a href="${escapeHtml(safeHref(video.url))}" rel="noopener noreferrer">${escapeHtml(title)}</a>
            <span class="url">${escapeHtml(video.channel || '')}${video.publishedAt ? ` · ${escapeHtml(formatDate(video.publishedAt))}` : ''}</span>
          </td>
          <td>${escapeHtml(formatDuration(video.durationSeconds))}</td>
          <td><span class="status ${escapeHtml(statusClass(video.status))}">${escapeHtml(status)}</span>${video.error ? `<br><span class="error-line">${escapeHtml(video.error)}</span>` : ''}</td>
          <td>${video.wordCount ? escapeHtml(Number(video.wordCount).toLocaleString('en-US')) : '—'}</td>
          <td>${escapeHtml(video.transcriptLanguage ?? '—')}</td>
        </tr>`;
}

function renderJobRow(course, job) {
  const status = JOB_STATUS[job.status] ?? job.status ?? 'Unknown';
  const stage = STAGES[job.stage] ?? job.stage ?? '';
  return `        <tr>
          <td><a href="/courses/${escapeHtml(course.id)}/runs/${escapeHtml(job.id)}">${escapeHtml(job.kind === 'pdf' ? 'PDF' : 'Ingest')} · ${escapeHtml(job.id.slice(0, 8))}</a></td>
          <td><span class="status ${escapeHtml(statusClass(job.status))}">${escapeHtml(status)}</span></td>
          <td>${escapeHtml(stage)}</td>
          <td>${escapeHtml(job.createdAt ? formatDateTime(job.createdAt) : '')}</td>
        </tr>`;
}

export function renderCoursePage({
  course, videos = [], jobs = [], activeJob = null, notice = null,
}) {
  const status = COURSE_STATUS[course.status] ?? course.status ?? 'Unknown';
  const running = Boolean(activeJob && (activeJob.status === 'queued' || activeJob.status === 'running'));

  let statusPanel = '';
  if (course.status === 'failed') {
    statusPanel = `  <p class="notice alert" role="alert">The last run failed: ${escapeHtml(course.error || 'unknown error')}.</p>`;
  } else if (running) {
    const stage = STAGES[activeJob.stage] ?? activeJob.stage ?? 'Working';
    const progress = activeJob.progress ?? {};
    const count = progress.total > 0 ? ` ${escapeHtml(String(progress.done ?? 0))} of ${escapeHtml(String(progress.total))}.` : '';
    statusPanel = `  <p class="notice" role="status">${escapeHtml(stage)}…${count} This page refreshes itself.</p>`;
  } else if (course.status === 'ready' && course.proposal) {
    statusPanel = `  <p class="notice" role="status">The topics are ready for review.
      <a href="/courses/${escapeHtml(course.id)}/topics">Choose what goes into the book</a>.</p>`;
  } else if (course.status === 'complete') {
    statusPanel = `  <p class="notice" role="status">A PDF has been generated for this course.
      <a href="/courses/${escapeHtml(course.id)}/topics">Review topics and build another</a>.</p>`;
  }

  const latestPdf = jobs.find((job) => job.kind === 'pdf' && job.status === 'succeeded');
  const pdfLine = latestPdf
    ? `  <p><a href="/courses/${escapeHtml(course.id)}/runs/${escapeHtml(latestPdf.id)}/download">Download the latest PDF</a></p>`
    : '';

  const rows = videos.length
    ? `      <div class="table-wrap">
      <table>
        <thead><tr><th scope="col">Video</th><th scope="col">Length</th><th scope="col">Transcript</th><th scope="col">Words</th><th scope="col">Language</th></tr></thead>
        <tbody>
${videos.map(renderVideoRow).join('\n')}
        </tbody>
      </table>
      </div>`
    : '      <p class="empty">No videos discovered yet.</p>';

  const jobsBlock = jobs.length
    ? `      <div class="table-wrap">
      <table>
        <thead><tr><th scope="col">Run</th><th scope="col">State</th><th scope="col">Stage</th><th scope="col">Started</th></tr></thead>
        <tbody>
${jobs.slice(0, 8).map((job) => renderJobRow(course, job)).join('\n')}
        </tbody>
      </table>
      </div>`
    : '      <p class="empty">No runs yet.</p>';

  const topicLink = course.proposal
    ? `    <a href="/courses/${escapeHtml(course.id)}/topics">Review topics</a>`
    : '';

  const body = `  <header class="masthead">
    <p class="kicker">YoutubeDigester · ${escapeHtml(course.discovery ?? 'course')}</p>
    <h1><a href="/courses/${escapeHtml(course.id)}">${escapeHtml(course.title)}</a></h1>
    <p class="sub">${escapeHtml(course.channelTitle || '')}${course.playlistId ? ` · playlist ${escapeHtml(course.playlistId)}` : ''} · <a href="${escapeHtml(safeHref(course.seed?.url ?? ''))}" rel="noopener noreferrer">${escapeHtml(hostOf(course.seed?.url ?? '') || 'seed video')}</a></p>
  </header>
${noticeLine(notice)}
${statusPanel}
  <p class="progress">Status: ${escapeHtml(status)}${course.stage ? ` · ${escapeHtml(STAGES[course.stage] ?? course.stage)}` : ''}</p>
${pdfLine}

  <h2>Videos (${videos.length})</h2>
${rows}

  <h2>Runs</h2>
${jobsBlock}

${warningsBlock(course.warnings)}

  <h2>Actions</h2>
  <div class="actions">
${topicLink}
    <form method="post" action="/courses/${escapeHtml(course.id)}/reingest">
      <label class="progress"><input type="checkbox" name="force" value="1"> Re-fetch stored transcripts</label>
      <button type="submit" class="ghost">Retry ingest</button>
    </form>
    <form method="post" action="/courses/${escapeHtml(course.id)}/delete">
      <button type="submit" class="ghost">Remove course</button>
    </form>
  </div>`;

  return layout({
    title: `${course.title} — YoutubeDigester`,
    body,
    refreshSeconds: running ? 2 : null,
  });
}

export function renderTopicsPage({ course, proposal, notice = null }) {
  const selected = new Set(course.selection?.topicIds ?? []);
  const topics = Array.isArray(proposal?.topics) ? proposal.topics : [];
  const checkAll = selected.size === 0;

  const items = topics.map((topic) => `      <li>
        <label>
          <input type="checkbox" name="topicIds" value="${escapeHtml(topic.id)}"${checkAll || selected.has(topic.id) ? ' checked' : ''}>
          <span>
            <strong>${escapeHtml(topic.title)}</strong>
            <span class="summary">${escapeHtml(topic.summary || '')}</span>
            <span class="count">${escapeHtml(String((topic.videoIds ?? []).length))} video(s)</span>
          </span>
        </label>
      </li>`).join('\n');

  const sourceLine = proposal?.source === 'deepseek'
    ? `Topics suggested by ${escapeHtml(proposal.model || 'DeepSeek')}.`
    : 'Topics were grouped locally because the language model was unavailable.';

  const body = `  <header class="masthead">
    <p class="kicker">YoutubeDigester · Topic Review</p>
    <h1>${escapeHtml(course.title)}</h1>
    <p class="sub">${escapeHtml(sourceLine)}</p>
  </header>
${noticeLine(notice)}

  <h2>Choose the chapters</h2>
  <form method="post" action="/courses/${escapeHtml(course.id)}/topics">
    <input type="hidden" name="proposalId" value="${escapeHtml(proposal?.id ?? '')}">
    <ul class="topics">
${items}
    </ul>
    <div class="actions">
      <button type="submit">Build the PDF</button>
      <a href="/courses/${escapeHtml(course.id)}">Back to the course</a>
    </div>
  </form>
${warningsBlock(proposal?.error ? [`Model note: ${proposal.error}`] : [])}`;

  return layout({ title: `Topics — ${course.title}`, body });
}

export function renderRunPage({ course, job, notice = null }) {
  const running = job.status === 'queued' || job.status === 'running';
  const stage = STAGES[job.stage] ?? job.stage ?? 'Working';
  const progress = job.progress ?? {};
  const count = progress.total > 0
    ? `  <p class="progress">${escapeHtml(String(progress.done ?? 0))} of ${escapeHtml(String(progress.total))} complete${progress.failed ? `, ${escapeHtml(String(progress.failed))} failed` : ''}.</p>`
    : '';

  let outcome;
  if (running) {
    outcome = `  <p class="notice" role="status">${escapeHtml(stage)}… This page refreshes itself.</p>`;
  } else if (job.status === 'failed') {
    outcome = `  <p class="notice alert" role="alert">The run did not finish: ${escapeHtml(job.error?.message || 'unknown error')}.</p>`;
  } else {
    const download = job.kind === 'pdf'
      ? `  <p class="notice" role="status">The PDF is ready. <a href="/courses/${escapeHtml(course.id)}/runs/${escapeHtml(job.id)}/download">Download it</a>.</p>`
      : '  <p class="notice" role="status">The course is ready. <a href="/courses/' + escapeHtml(course.id) + '/topics">Review the topics</a>.</p>';
    outcome = download;
  }

  const result = job.result ?? {};
  const summary = result.chapterCount
    ? `  <p class="progress">${escapeHtml(String(result.chapterCount))} chapter(s) written.</p>`
    : '';

  const body = `  <header class="masthead">
    <p class="kicker">YoutubeDigester · Run Report</p>
    <h1>${escapeHtml(course.title)}</h1>
    <p class="sub">${escapeHtml(job.kind === 'pdf' ? 'PDF generation' : 'Course ingest')} · ${escapeHtml(job.id)}
      ${job.startedAt ? ` · started ${escapeHtml(formatDateTime(job.startedAt))}` : ''}${job.finishedAt ? ` · finished ${escapeHtml(formatDateTime(job.finishedAt))}` : ''}</p>
  </header>
${noticeLine(notice)}
  <h2>${escapeHtml(stage)}</h2>
${outcome}
${count}
${summary}
${warningsBlock(job.warnings)}
  <p><a href="/courses/${escapeHtml(course.id)}">Back to the course</a> · <a href="/">All courses</a></p>`;

  return layout({
    title: `Run ${job.id.slice(0, 8)} — ${course.title}`,
    body,
    refreshSeconds: running ? 2 : null,
  });
}

export function renderSettingsPage({ settings, paths = {}, notice = null }) {
  const safe = {
    youtube: { ...settings.youtube, apiKey: settings.youtube?.apiKey ? '(set)' : '' },
    deepseek: { ...settings.deepseek, apiKey: settings.deepseek?.apiKey ? '(set)' : '' },
    transcript: settings.transcript,
    llm: settings.llm,
    pdf: settings.pdf,
    output: settings.output,
    jobs: settings.jobs,
  };

  const body = `  <header class="masthead">
    <p class="kicker">YoutubeDigester · Settings</p>
    <h1>Effective settings</h1>
    <p class="sub">Edit <code>settings.json</code> and restart or re-run a job to apply changes.</p>
  </header>
${noticeLine(notice)}

  <h2>API keys</h2>
  <dl class="key-state">
    <div><dt>YouTube Data API</dt><dd>${settings.youtube?.apiKey ? 'Configured' : 'Not configured — single-video mode'}</dd></div>
    <div><dt>DeepSeek</dt><dd>${settings.deepseek?.apiKey ? 'Configured' : 'Not configured — local topic and chapter fallbacks'}</dd></div>
    <div><dt>Data directory</dt><dd><code>${escapeHtml(paths.dataDir ?? 'data')}</code></dd></div>
    <div><dt>Output directory</dt><dd><code>${escapeHtml(paths.outputDir ?? 'output')}</code></dd></div>
  </dl>

  <h2>settings.json (secrets redacted)</h2>
  <pre class="settings">${escapeHtml(JSON.stringify(safe, null, 2))}</pre>

  <h2>PDF style</h2>
  <dl class="key-state">
    <div><dt>Name</dt><dd>${escapeHtml(settings.pdf?.style?.name ?? '—')}</dd></div>
    <div><dt>Reading level</dt><dd>${escapeHtml(settings.pdf?.style?.readingLevel ?? '—')}</dd></div>
    <div><dt>Page size</dt><dd>${escapeHtml(settings.pdf?.pageSize ?? 'A4')}</dd></div>
    <div><dt>Video citations</dt><dd>${settings.pdf?.style?.showVideoCitations === false ? 'Off' : 'On'}</dd></div>
  </dl>

  <p><a href="/">Back to the courses</a></p>`;

  return layout({ title: 'Settings — YoutubeDigester', body });
}

export function renderErrorPage({ status, message }) {
  const body = `  <header class="masthead">
    <p class="kicker">YoutubeDigester · Course Companion</p>
    <h1>Something went wrong</h1>
  </header>
  <h2>Error ${escapeHtml(status)}</h2>
  <p class="notice alert" role="alert">${escapeHtml(message)}</p>
  <p><a href="/">Back to the courses</a></p>`;

  return layout({ title: `Error ${status} — YoutubeDigester`, body });
}
