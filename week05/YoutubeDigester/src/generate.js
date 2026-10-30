import path from 'node:path';

import { writeChapters as defaultWriteChapters } from './llm.js';
import { renderBookHtml } from './render-book.js';

export class GenerateError extends Error {
  constructor(code, message) {
    super(message);
    this.name = 'GenerateError';
    this.code = code;
    this.expose = true;
  }
}

function throwIfAborted(signal) {
  if (signal?.aborted) throw new GenerateError('cancelled', 'The PDF generation was cancelled.');
}

function footerTemplate(style) {
  const colour = style?.colors?.muted ?? '#5d554a';
  const font = style?.fontFamily ?? 'Georgia, serif';
  return `<div style="width:100%; padding:0 14mm; font-family:${font}; font-size:8pt; color:${colour}; text-align:center;">
    <span class="pageNumber"></span> / <span class="totalPages"></span>
  </div>`;
}

function marginsFrom(style) {
  const margins = style?.marginMm ?? {};
  const value = (name, fallback) => `${Number.isFinite(Number(margins[name])) ? Number(margins[name]) : fallback}mm`;
  return {
    top: value('top', 20),
    right: value('right', 18),
    bottom: value('bottom', 20),
    left: value('left', 18),
  };
}

/**
 * Selected topics → one chapter each → one PDF. Chapters are persisted after
 * every completion, so a failed render still leaves usable text behind.
 */
export async function runPdfGeneration({
  courseId,
  jobId,
  depot,
  settings = {},
  pdfRenderer,
  outputDir,
  llm = null,
  force = false,
  signal,
  update = () => {},
  addWarning = () => {},
  now = () => new Date(),
} = {}) {
  const course = await depot.getCourse(courseId);
  if (!course) throw new GenerateError('course_not_found', 'That course does not exist.');

  const pdfSettings = settings.pdf ?? {};
  const style = pdfSettings.style ?? {};
  const llmSettings = settings.llm ?? {};
  const deepseek = settings.deepseek ?? {};
  const transcriptSettings = settings.transcript ?? {};

  try {
    const proposal = course.proposal;
    const selection = course.selection;
    if (!proposal || !Array.isArray(proposal.topics) || proposal.topics.length === 0 || !selection) {
      throw new GenerateError('no_selection', 'Confirm at least one topic before building the PDF.');
    }

    const known = new Set(proposal.topics.map((topic) => topic.id));
    const selectedIds = [...new Set(selection.topicIds ?? [])].filter((id) => known.has(id));
    if (selectedIds.length === 0) {
      throw new GenerateError('invalid_selection', 'The confirmed topics no longer exist. Review the topics again.');
    }

    const topics = proposal.topics
      .filter((topic) => selectedIds.includes(topic.id))
      .sort((a, b) => (a.order ?? 0) - (b.order ?? 0));

    const videos = await depot.listVideos(courseId);
    const videoById = new Map(videos.map((video) => [video.id, video]));

    update({ stage: 'chapters', progress: { total: topics.length, done: 0, failed: 0 } });
    await depot.updateCourse(courseId, { status: 'generating', stage: 'chapters', error: null });
    throwIfAborted(signal);

    const sourcesByTopic = new Map();
    for (const topic of topics) {
      const sources = [];
      for (const id of topic.videoIds ?? []) {
        const video = videoById.get(id);
        if (!video) continue;
        const text = await depot.readTranscript(id, { maxChars: transcriptSettings.maxChars ?? 200_000 });
        sources.push({
          id,
          title: video.title ?? '',
          channel: video.channel ?? '',
          url: video.url ?? `https://www.youtube.com/watch?v=${id}`,
          publishedAt: video.publishedAt ?? null,
          text: text ?? video.excerpt ?? '',
          excerpt: video.excerpt ?? '',
        });
      }
      if (sources.length === 0) {
        addWarning(`Topic "${topic.title}" has no stored transcripts; the chapter will be a short outline.`);
      }
      sourcesByTopic.set(topic.id, sources);
    }

    const writeChapters = llm?.writeChapters ?? defaultWriteChapters;
    const results = new Array(topics.length);
    let done = 0;

    await writeChapters(
      topics.map((topic) => ({ topic, sources: sourcesByTopic.get(topic.id) ?? [] })),
      {
        courseTitle: course.title,
        style,
        apiKey: deepseek.apiKey ?? '',
        baseURL: deepseek.baseURL ?? '',
        model: deepseek.model,
        temperature: deepseek.temperature,
        maxTokens: deepseek.maxTokens,
        timeoutMs: deepseek.timeoutMs,
        chapterConcurrency: llmSettings.chapterConcurrency,
        limits: {
          maxSections: llmSettings.chapterMaxSections,
          maxChars: llmSettings.chapterMaxChars,
          maxInputChars: llmSettings.chapterMaxInputChars,
          maxTotalInputChars: llmSettings.chapterMaxTotalInputChars,
        },
        warn: addWarning,
        onEach: async (result, entry, index) => {
          results[index] = {
            topicId: entry.topic.id,
            title: entry.topic.title,
            source: result.source,
            error: result.error,
            chapter: result.chapter,
          };
          done += 1;
          update({ progress: { total: topics.length, done, failed: 0 } });
          await depot.writeRunJson(jobId, 'chapters.json', results.filter(Boolean));
          if (result.error) addWarning(`${entry.topic.title}: ${result.error.message}`);
        },
      },
    );

    const chapterEntries = topics.map((topic, index) => {
      const result = results[index];
      return {
        topic,
        chapter: result?.chapter ?? null,
        source: result?.source ?? 'fallback',
        error: result?.error ?? null,
        sources: sourcesByTopic.get(topic.id) ?? [],
      };
    });

    update({ stage: 'rendering_html' });
    await depot.updateCourse(courseId, { stage: 'rendering_html' });
    throwIfAborted(signal);

    const generatedAt = now();
    const html = renderBookHtml({ course, chapters: chapterEntries, settings, generatedAt });
    await depot.writeRunText(jobId, 'digest.html', html);

    update({ stage: 'rendering_pdf' });
    await depot.updateCourse(courseId, { stage: 'rendering_pdf' });
    throwIfAborted(signal);

    if (!pdfRenderer || typeof pdfRenderer.render !== 'function') {
      throw new GenerateError('pdf_unavailable', 'The PDF renderer is not available.');
    }

    const pdfPath = path.join(outputDir, courseId, `${jobId}.pdf`);
    const includePageNumbers = pdfSettings.pageNumbers !== false;
    await pdfRenderer.render({
      html,
      outputPath: pdfPath,
      format: pdfSettings.pageSize === 'Letter' ? 'Letter' : 'A4',
      margins: marginsFrom(style),
      displayHeaderFooter: includePageNumbers,
      footerTemplate: includePageNumbers ? footerTemplate(style) : '',
    });

    await depot.updateCourse(courseId, {
      status: 'complete',
      stage: 'done',
      error: null,
    });

    return {
      result: {
        courseId,
        jobId,
        pdfPath,
        chapterCount: chapterEntries.length,
        topicCount: topics.length,
        generatedAt: generatedAt.toISOString(),
        chapterSources: chapterEntries.reduce((counts, entry) => {
          counts[entry.source] = (counts[entry.source] ?? 0) + 1;
          return counts;
        }, {}),
      },
    };
  } catch (err) {
    const message = err?.expose === false ? 'The PDF could not be generated.' : err?.message;
    await depot.updateCourse(courseId, {
      status: 'ready',
      stage: null,
      error: typeof message === 'string' ? message.slice(0, 300) : 'The PDF could not be generated.',
    }).catch(() => {});
    throw err;
  }
}
