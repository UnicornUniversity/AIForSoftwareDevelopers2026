/**
 * The no-cameras explanation.
 *
 * This is the most likely first-run state, and it has three very different
 * causes that must not read the same: no API key configured, the terminator is
 * over open ocean, or the backend is unreachable. A blank grid would leave the
 * reader to guess which.
 */
export function EmptyState({ title, detail, hints = [] }) {
  return (
    <div className="empty">
      <p className="empty-title">{title ?? 'Nothing to show'}</p>
      {detail && <p className="empty-detail">{detail}</p>}
      {hints.length > 0 && (
        <ul className="empty-hints">
          {hints.map((hint) => (
            <li key={hint}>{hint}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * The full-page version, used when the first load failed and there is no
 * previous payload to fall back on.
 */
export function ErrorState({ error, onRetry, retrying }) {
  const isNetwork = error?.code === 'network';

  return (
    <div className="empty empty-page">
      <p className="empty-title">Could not load the sunset chase</p>
      <p className="empty-detail">{error?.message ?? 'Something went wrong.'}</p>

      <ul className="empty-hints">
        {isNetwork && (
          <>
            <li>Start the backend: <code>cd backend &amp;&amp; npm run dev</code></li>
            <li>It should be listening on <code>http://localhost:8787</code>.</li>
            <li>Check it directly: <code>curl http://localhost:8787/api/v1/health</code></li>
          </>
        )}
        {error?.code === 'timeout' && (
          <li>
            The first request sweeps roughly two dozen upstream calls and then asks
            DeepSeek to curate them, so it can take up to a minute. Trying again
            should hit the cache.
          </li>
        )}
      </ul>

      {onRetry && (
        <button type="button" className="button" onClick={onRetry} disabled={retrying}>
          {retrying ? 'Retrying…' : 'Try again'}
        </button>
      )}
    </div>
  );
}
