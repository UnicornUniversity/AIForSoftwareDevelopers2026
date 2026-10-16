import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';

import { fetchWebcam } from '../api.js';
import {
  formatAge,
  formatCountdown,
  formatDistance,
  formatDuration,
  formatLatLon,
  phaseColor,
  phaseLabel,
} from '../lib/geo.js';

/**
 * How many times one card may try to replace a dead image URL.
 *
 * Windy preview tokens expire after about ten minutes, so the first failure is
 * usually worth a refresh. A camera that is genuinely offline would otherwise
 * refresh forever, once per failed load.
 */
const MAX_IMAGE_RETRIES = 2;

/**
 * One webcam.
 *
 * The image is the product, so it gets the most attention: lazy loading so a
 * gallery of twelve does not fetch twelve images at once, and an `onError` path
 * that mints a fresh token from the backend rather than showing a broken image.
 */
export function CameraCard({ camera }) {
  const [imageUrl, setImageUrl] = useState(camera.imagePreviewUrl);
  const [imageFailed, setImageFailed] = useState(false);
  const [retries, setRetries] = useState(0);
  const [refreshFailed, setRefreshFailed] = useState(false);

  // Tracks the mounted state so an in-flight refresh cannot set state after the
  // card has gone, which happens routinely as the poll replaces the list.
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // A new payload means a new URL, so reset the failure state with it.
  useEffect(() => {
    setImageUrl(camera.imagePreviewUrl);
    setImageFailed(false);
    setRetries(0);
    setRefreshFailed(false);
  }, [camera.webcamId, camera.imagePreviewUrl]);

  const handleError = useCallback(async () => {
    if (retries >= MAX_IMAGE_RETRIES) {
      setImageFailed(true);
      return;
    }

    setRetries((n) => n + 1);

    try {
      const fresh = await fetchWebcam(camera.webcamId);
      if (!mountedRef.current) return;

      if (fresh?.imagePreviewUrl && fresh.imagePreviewUrl !== imageUrl) {
        setImageUrl(fresh.imagePreviewUrl);
        return;
      }
      // The backend answered but the URL is unchanged, so this camera is simply
      // offline. Retrying again would only repeat the same failure.
      setImageFailed(true);
    } catch {
      if (!mountedRef.current) return;
      setRefreshFailed(true);
      setImageFailed(true);
    }
  }, [camera.webcamId, retries, imageUrl]);

  const countdown = formatCountdown(camera.minutesToSunset);
  const duration = formatDuration(camera.sunsetDurationMin);
  const distance = formatDistance(camera.distanceToTerminatorKm);
  const coords = formatLatLon(camera.latitude, camera.longitude);

  return (
    <article className="card">
      <div className="card-image">
        {imageFailed || !imageUrl ? (
          <div className="card-image-fallback">
            <span>{refreshFailed ? 'Image unavailable' : 'Camera offline'}</span>
            <small>
              {refreshFailed
                ? 'The refresh request failed too.'
                : 'Windy has no current frame for this camera.'}
            </small>
          </div>
        ) : (
          <img
            src={imageUrl}
            alt={camera.title ? `${camera.title} - live view` : 'Live webcam view'}
            loading="lazy"
            decoding="async"
            referrerPolicy="no-referrer"
            onError={handleError}
          />
        )}

        <span className="chip chip-phase" style={{ '--phase': phaseColor(camera.phase) }}>
          {phaseLabel(camera.phase)}
        </span>

        {countdown && <span className="chip chip-countdown">{countdown}</span>}
      </div>

      <div className="card-body">
        <h3 className="card-title">
          <Link to={`/camera/${encodeURIComponent(camera.webcamId)}`}>
            {camera.city || camera.title || 'Webcam'}
          </Link>
        </h3>

        {camera.title && camera.city && <p className="card-subtitle">{camera.title}</p>}

        <dl className="card-facts">
          <div>
            <dt>Twilight</dt>
            {/* A dash, not "0 min": an unmeasured duration and a short one are
                different facts. */}
            <dd>{duration ?? 'not measured'}</dd>
          </div>
          <div>
            <dt>From the line</dt>
            <dd>{distance ?? '-'}</dd>
          </div>
          <div>
            <dt>Position</dt>
            <dd>{coords ?? '-'}</dd>
          </div>
        </dl>

        {/* Rendered as text, never as HTML. This string can originate from
            DeepSeek, and camera titles reach the model as data. */}
        <p className="card-reason">{camera.reason}</p>

        <footer className="card-footer">
          <span className="card-source">
            {camera.source === 'fallback' ? 'Big-city fallback' : `Rank ${camera.rank}`}
            {camera.reasonSource === 'deepseek' && <em> · narrated by DeepSeek</em>}
          </span>
          <a
            className="card-link"
            href={camera.windyPageUrl}
            target="_blank"
            rel="noreferrer noopener"
          >
            Open on Windy
          </a>
        </footer>

        {camera.lastUpdatedOn && (
          <p className="card-updated">Frame from {formatAge(camera.lastUpdatedOn)}</p>
        )}
      </div>
    </article>
  );
}
