import { useMemo } from 'react';

import { useChase } from '../hooks/useChase.js';
import { Briefing } from '../components/Briefing.jsx';
import { CameraGallery } from '../components/CameraGallery.jsx';
import { ErrorState } from '../components/EmptyState.jsx';
import { StatusBar } from '../components/StatusBar.jsx';
import { TerminatorMap } from '../components/TerminatorMap.jsx';

/**
 * The main view: where the terminator is, and what is standing on it.
 *
 * All the cameras - ranked and fallback - are drawn on one map, because the
 * reader's question is "where in the world is the light good", and splitting
 * them across two maps would answer a different one.
 */
export function ChasePage() {
  const { data, error, loading, refreshing, stale, refresh } = useChase();

  const allCameras = useMemo(
    () => [...(data?.primary ?? []), ...(data?.fallback ?? [])],
    [data],
  );

  if (loading && !data) {
    return (
      <div className="page-loading">
        <p>Finding the terminator…</p>
        <p className="page-loading-note">
          The first sweep makes about two dozen upstream calls and then asks
          DeepSeek to curate the result, so this can take up to a minute.
        </p>
      </div>
    );
  }

  if (error && !data) {
    return <ErrorState error={error} onRetry={refresh} retrying={refreshing} />;
  }

  const primaryCount = data?.primary?.length ?? 0;
  const terminatorOverWater = primaryCount === 0;

  return (
    <div className="chase">
      <StatusBar payload={data} stale={stale} onRefresh={refresh} refreshing={refreshing} />

      <Briefing briefing={data.briefing} />

      <TerminatorMap
        payload={data}
        cameras={allCameras}
        samplePoints={data.terminator?.samplePoints ?? []}
      />

      <div className="legend">
        <span className="legend-item"><i style={{ background: '#ff7a2f' }} />Sunset line</span>
        <span className="legend-item"><i style={{ background: '#5f7492' }} />Sunrise line</span>
        <span className="legend-item"><i style={{ background: '#ffd166' }} />Search point</span>
      </div>

      <CameraGallery
        title="On the terminator"
        description={`Ranked by distance to the day/night line, the length of twilight at that latitude, and how far into the sunset the camera is.`}
        cameras={data.primary ?? []}
        emptyTitle="No cameras on the line right now"
        emptyDetail={
          terminatorOverWater
            ? 'Most of the terminator is crossing open ocean or ice, which is the usual case. The big-city list below is the guaranteed answer.'
            : 'The search found no cameras that passed the filters.'
        }
        hints={
          data.meta?.windy?.authOk === false
            ? ['No Windy API key is configured, so no cameras could be fetched at all.']
            : []
        }
      />

      <CameraGallery
        title="Big cities in daylight"
        description="Always computed, so there is something to look at even when the terminator is over water."
        cameras={data.fallback ?? []}
        emptyTitle="No daylight city cameras"
        emptyDetail="Either no big city was in daylight, or Windy returned nothing for the ones that were."
      />

      <details className="diagnostics">
        <summary>Search details</summary>
        <dl>
          <div><dt>Windy calls</dt><dd>{data.meta?.windy?.callsMade ?? '-'} ({data.meta?.windy?.callsFailed ?? 0} failed)</dd></div>
          <div><dt>Sample points with results</dt><dd>{(data.terminator?.samplePoints ?? []).filter((p) => p.results > 0).length} of {(data.terminator?.samplePoints ?? []).length}</dd></div>
          <div><dt>Candidates</dt><dd>{data.meta?.candidates?.deduped ?? '-'} deduped, {data.meta?.candidates?.passedFilters ?? '-'} passed filters</dd></div>
          <div><dt>Cache</dt><dd>{data.meta?.cache?.hit ? `hit, ${data.meta.cache.ageSeconds}s old` : 'miss'}</dd></div>
          {/* `latencyMs` is the model's own latency even when the answer came
              from the cache, so the reuse is stated rather than left to look
              like a 29-second model call inside a 27-millisecond response. */}
          <div><dt>Model</dt><dd>{data.meta?.llm?.used ? `${data.meta.llm.model} in ${data.meta.llm.latencyMs} ms${data.meta.llm.cached ? ' (cached)' : ''}` : (data.meta?.llm?.error ?? 'not used')}</dd></div>
          <div><dt>Total</dt><dd>{data.meta?.durationMs ?? '-'} ms</dd></div>
        </dl>
      </details>
    </div>
  );
}
