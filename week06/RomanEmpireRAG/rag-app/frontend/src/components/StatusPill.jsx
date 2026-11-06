/**
 * A one-line answer to "is the thing behind this page working?".
 *
 * `healthError` means /api/health could not be reached at all - the search will
 * fail the same way, so the pill names the likely cause rather than saying
 * "unknown".
 */
export function StatusPill({ health, error }) {
  if (error) {
    return (
      <span className="pill pill--bad" title={error}>
        <span className="pill__dot" aria-hidden="true" />
        Backend offline
      </span>
    );
  }

  if (!health) {
    return (
      <span className="pill pill--muted">
        <span className="pill__dot" aria-hidden="true" />
        Connecting…
      </span>
    );
  }

  const generated = health.answer.mode !== 'extractive' && health.answer.hasLlmKey;

  return (
    <span
      className={`pill ${generated ? 'pill--good' : 'pill--warn'}`}
      title={
        generated
          ? 'Answers are written by the model from the retrieved passages'
          : 'Answers are quoted from the retrieved passages; no model key is configured'
      }
    >
      <span className="pill__dot" aria-hidden="true" />
      {generated ? `DeepSeek · ${health.answer.model}` : 'Extractive mode'}
    </span>
  );
}
