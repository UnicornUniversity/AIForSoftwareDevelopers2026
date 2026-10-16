import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { fetchWebcam } from '../api.js';
import { CameraCard } from '../components/CameraCard.jsx';
import { ErrorState } from '../components/EmptyState.jsx';
import { useChase } from '../hooks/useChase.js';

/**
 * One camera, at its own address.
 *
 * The payload is read from the same chase the main page uses, so this view costs
 * no extra upstream calls when the user arrives from a card. The camera is
 * fetched directly only when it is not in the current payload - a bookmarked or
 * shared link, where the id may not be on the terminator any more.
 */
export function CameraPage() {
  const { webcamId } = useParams();
  const { data, loading: chaseLoading } = useChase();

  const [camera, setCamera] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const fromPayload =
    data?.primary?.find((c) => c.webcamId === webcamId) ??
    data?.fallback?.find((c) => c.webcamId === webcamId) ??
    null;

  useEffect(() => {
    setCamera(fromPayload);
    if (fromPayload) {
      setLoading(false);
      setError(null);
      return undefined;
    }
    if (chaseLoading || !data) return undefined;

    // Not on the terminator in this payload, so ask for it by id.
    const controller = new AbortController();
    setLoading(true);

    fetchWebcam(webcamId, { signal: controller.signal })
      .then((fresh) => {
        setCamera(fresh);
        setError(null);
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(err);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => controller.abort();
  }, [webcamId, fromPayload, chaseLoading, data]);

  return (
    <div className="camera-page">
      <Link className="back-link" to="/">
        ← Back to the chase
      </Link>

      {loading && <p className="page-loading-note">Loading camera…</p>}

      {error && !camera && (
        <ErrorState
          error={{
            code: error.code,
            message:
              error.status === 404
                ? `No webcam with id ${webcamId}.`
                : error.message,
          }}
        />
      )}

      {camera && (
        <>
          <CameraCard camera={camera} />

          <section className="camera-detail">
            <h2>Why this camera</h2>
            <dl>
              <div><dt>Webcam id</dt><dd>{camera.webcamId}</dd></div>
              {camera.country && <div><dt>Country</dt><dd>{camera.country}</dd></div>}
              {camera.region && <div><dt>Region</dt><dd>{camera.region}</dd></div>}
              {camera.sunAltitudeDeg !== undefined && (
                <div><dt>Sun altitude</dt><dd>{camera.sunAltitudeDeg.toFixed(2)}°</dd></div>
              )}
              {camera.hourAngleDeg !== undefined && (
                <div><dt>Hour angle</dt><dd>{camera.hourAngleDeg.toFixed(1)}° ({camera.isDescending ? 'descending' : 'ascending'})</dd></div>
              )}
              {camera.score !== undefined && (
                <div><dt>Score</dt><dd>{camera.score.toFixed(4)}</dd></div>
              )}
            </dl>

            {camera.scoreParts && (
              <ul className="score-parts">
                {Object.entries(camera.scoreParts).map(([key, value]) => (
                  <li key={key}>
                    <span>{key}</span>
                    <span className="score-bar">
                      <i style={{ width: `${Math.round(value * 100)}%` }} />
                    </span>
                    <span>{value.toFixed(2)}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  );
}
