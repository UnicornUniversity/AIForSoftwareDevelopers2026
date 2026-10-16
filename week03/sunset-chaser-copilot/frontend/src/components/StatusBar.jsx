import { formatAge } from '../lib/geo.js';

/**
 * What the app knows about the sun right now, and how complete the answer is.
 *
 * This is where the payload's own `meta` is surfaced rather than hidden. A
 * reviewer asking "why are there only four cameras" or "why does it say computed
 * locally" should be able to read the answer off the page instead of the logs.
 */
export function StatusBar({ payload, stale, onRefresh, refreshing }) {
  if (!payload) return null;

  const { sun, meta, generatedAt } = payload;
  const warnings = meta?.warnings ?? [];

  return (
    <section className="status" aria-label="Current conditions">
      <div className="status-facts">
        <Fact label="Sun overhead at" value={`${Math.abs(sun.subsolarLatDeg).toFixed(1)}° ${sun.subsolarLatDeg >= 0 ? 'N' : 'S'}`} />
        <Fact label="Meridian" value={`${Math.abs(sun.subsolarLonDeg).toFixed(1)}° ${sun.subsolarLonDeg >= 0 ? 'E' : 'W'}`} />
        <Fact label="Terminator reaches" value={`±${sun.sunsetTerminatorSpanDeg.toFixed(1)}°`} />
        <Fact label="Equation of time" value={`${sun.equationOfTimeMin >= 0 ? '+' : ''}${sun.equationOfTimeMin.toFixed(1)} min`} />
        <Fact label="Updated" value={formatAge(generatedAt) ?? '-'} />
      </div>

      <div className="status-actions">
        {/* A stale flag rather than an error page: the cameras below are still
            real, they are just from the last successful poll. */}
        {stale && (
          <span className="badge badge-warn" title="The most recent refresh failed.">
            Showing the last good result
          </span>
        )}
        {meta?.degraded && !stale && (
          <span className="badge badge-warn" title="No cameras were found near the terminator.">
            Degraded
          </span>
        )}
        <button type="button" className="button" onClick={onRefresh} disabled={refreshing}>
          {refreshing ? 'Refreshing…' : 'Refresh now'}
        </button>
      </div>

      {warnings.length > 0 && (
        <ul className="status-warnings">
          {warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Fact({ label, value }) {
  return (
    <div className="status-fact">
      <span className="status-fact-label">{label}</span>
      <span className="status-fact-value">{value}</span>
    </div>
  );
}
