/**
 * The answer is shown in a read-only textarea, per specs/ui.md. Read-only
 * matters: it is plain text, so nothing in a model or corpus reply can be
 * rendered as markup.
 */

function sourceLabel(result) {
  switch (result.answerSource) {
    case 'deepseek':
      return {
        tone: 'good',
        text: `Generated · ${result.llm.model} · ${(result.llm.latencyMs / 1000).toFixed(1)} s`,
        title: 'Written by the model from the passages below',
      };
    case 'extractive':
      return {
        tone: 'warn',
        text: `Extractive · ${result.llm.note ?? 'model unavailable'}`,
        title: 'Quoted from the retrieved passages, not generated',
      };
    default:
      return {
        tone: 'muted',
        text: 'No matching passage',
        title: 'Nothing in the six volumes was close enough to this question',
      };
  }
}

export function AnswerPanel({ result, loading, slow }) {
  const badge = result ? sourceLabel(result) : null;

  const placeholder = loading
    ? slow
      ? 'Searching the six volumes — the language model can take up to 40 seconds on a slow link…'
      : 'Searching the six volumes…'
    : 'Ask a question to see an answer grounded in the retrieved passages.';

  return (
    <section className="panel panel--answer" aria-labelledby="answer-title" aria-busy={loading}>
      <div className="panel__head">
        <h2 id="answer-title">Answer</h2>
        {loading ? (
          <span className="panel__meta panel__meta--busy">
            <span className="spinner" aria-hidden="true" />
            Retrieving
          </span>
        ) : (
          badge && (
            <span className={`badge badge--${badge.tone}`} title={badge.title}>
              {badge.text}
            </span>
          )
        )}
      </div>

      <textarea
        className="answer"
        readOnly
        rows={16}
        value={result?.answer ?? ''}
        placeholder={placeholder}
        aria-label="Answer"
      />

      <p className="panel__foot">
        {result ? (
          <>
            <span>
              {result.retrieval.returned} of{' '}
              {result.retrieval.candidates.toLocaleString()} passages retrieved
              in {result.retrieval.latencyMs} ms
            </span>
            <span>{result.timing.totalMs.toLocaleString()} ms total</span>
          </>
        ) : (
          <span>Answers are grounded in the passages beside them.</span>
        )}
      </p>
    </section>
  );
}
