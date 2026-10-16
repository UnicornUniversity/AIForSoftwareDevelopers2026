import { useEffect } from 'react';
import L from 'leaflet';

import { formatCountdown, phaseColor, phaseLabel } from '../lib/geo.js';
import { useLeafletMap } from '../hooks/useLeafletMap.js';

/** How the two halves of the terminator are drawn. */
const ARC_STYLE = {
  sunset: { color: '#ff7a2f', weight: 3, opacity: 0.95 },
  sunrise: { color: '#5f7492', weight: 2, opacity: 0.7, dashArray: '6 6' },
};

/**
 * Draw one arc across all three world copies.
 *
 * The backend has already split the line at the antimeridian, so each arc is
 * continuous within one frame. Drawing it at lon - 360 and lon + 360 as well is
 * what keeps it continuous when the user pans past the date line - otherwise the
 * line simply stops at the edge of the world.
 */
function drawArc(layers, arc, style) {
  const points = arc.points.filter((p) => Array.isArray(p) && p.length === 2);
  if (points.length < 2) return;

  for (const offset of [-360, 0, 360]) {
    L.polyline(
      points.map(([lon, lat]) => [lat, lon + offset]),
      { ...style, interactive: false },
    ).addTo(layers);
  }
}

/**
 * The terminator, the sample points behind the search, and the chosen cameras.
 *
 * Layer order is deliberate: the terminator first, then the sample dots, then
 * the camera markers on top, because the markers are the thing a reader is
 * actually looking for and the arcs are context.
 */
export function TerminatorMap({ payload, cameras = [], samplePoints = [] }) {
  const { containerRef, mapRef, layersRef } = useLeafletMap({
    center: [20, 0],
    zoom: 2,
  });

  // Redraw on every payload change: the terminator moves 15 degrees an hour, so
  // a stale arc is a wrong arc.
  useEffect(() => {
    const layers = layersRef.current;
    if (!layers) return;

    layers.clearLayers();

    const terminator = payload?.terminator;
    if (terminator) {
      for (const arc of terminator.sunrise?.arcs ?? []) drawArc(layers, arc, ARC_STYLE.sunrise);
      for (const arc of terminator.sunset?.arcs ?? []) drawArc(layers, arc, ARC_STYLE.sunset);
    }

    // A sample point that returned nothing is drawn hollow and dim: it is the
    // honest answer to "why are there no cameras in the South Atlantic".
    for (const point of samplePoints) {
      const empty = !point.results;
      L.circleMarker([point.lat, point.lon], {
        radius: empty ? 2.5 : 4,
        color: empty ? '#3f4a5e' : '#ffd166',
        weight: 1,
        fillColor: empty ? '#2b3345' : '#ffd166',
        fillOpacity: empty ? 0.4 : 0.75,
      })
        .bindTooltip(
          empty
            ? `${point.lat.toFixed(1)}°, ${point.lon.toFixed(1)}° - no cameras within range`
            : `${point.lat.toFixed(1)}°, ${point.lon.toFixed(1)}° - ${point.results} camera(s)`,
          { direction: 'top' },
        )
        .addTo(layers);
    }

    for (const camera of cameras) {
      if (!Number.isFinite(camera.latitude) || !Number.isFinite(camera.longitude)) continue;

      const color = phaseColor(camera.phase);
      const countdown = formatCountdown(camera.minutesToSunset);

      // One marker per camera, at its true longitude. `L.circleMarker` is used
      // rather than an icon so no image asset is needed and the colour can carry
      // the phase directly.
      L.circleMarker([camera.latitude, camera.longitude], {
        radius: 7,
        color: '#0b0f18',
        weight: 2,
        fillColor: color,
        fillOpacity: 1,
      })
        .bindPopup(
          `<strong>${escapeHtml(camera.city ?? camera.title ?? 'Webcam')}</strong><br>` +
            `${escapeHtml(phaseLabel(camera.phase))}` +
            (countdown ? `<br>${escapeHtml(countdown)}` : ''),
        )
        .addTo(layers);
    }
  }, [payload, cameras, samplePoints]);

  // Frame the cameras once per payload, so a fresh result set is actually
  // visible. `getBounds` on an empty array throws, hence the length check.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || cameras.length === 0) return;

    const points = cameras
      .filter((c) => Number.isFinite(c.latitude) && Number.isFinite(c.longitude))
      .map((c) => [c.latitude, c.longitude]);

    if (points.length === 0) return;

    if (points.length === 1) {
      map.setView(points[0], 6);
      return;
    }

    map.fitBounds(L.latLngBounds(points), { padding: [60, 60], maxZoom: 6 });
  }, [cameras, mapRef]);

  return <div className="map" ref={containerRef} role="img" aria-label="Map of the solar terminator and nearby webcams" />;
}

/**
 * Escape text before it goes into a Leaflet popup.
 *
 * Leaflet's `bindPopup` takes an HTML string, and camera titles are untrusted
 * text from Windy. Without this, a camera called
 * `<img src=x onerror=...>` would run in the page.
 */
function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
