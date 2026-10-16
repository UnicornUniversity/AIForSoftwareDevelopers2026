import { useEffect, useRef } from 'react';
import L from 'leaflet';

/**
 * An imperative Leaflet map, created once and updated in place.
 *
 * Plain Leaflet rather than a React wrapper: mounting the map once and mutating
 * layers on data change is what the library is actually shaped for, and it keeps
 * the React version and the Leaflet wrapper's peer range from constraining each
 * other.
 *
 * The `containerRef` starts null on the first render, so the create effect has to
 * run after the DOM node exists - hence the ref rather than a query. Two guards
 * matter and both are load-bearing:
 *
 *   - `mapRef.current` is checked before creating, because React StrictMode
 *     double-invokes effects in development and a second `L.map()` on a live
 *     container throws "Map container is already initialized".
 *   - cleanup calls `map.remove()` rather than just dropping the reference, which
 *     is what leaves the container reusable for the second StrictMode pass.
 *
 * @param {(map: L.Map, layers: L.LayerGroup) => void} [onReady] called once,
 *   after the map and its layer group exist.
 */
export function useLeafletMap({ center = [20, 0], zoom = 2, onReady } = {}) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const layersRef = useRef(null);

  // `onReady` is read through a ref so a caller passing an inline arrow does not
  // tear down and rebuild the whole map on every render.
  const onReadyRef = useRef(onReady);
  onReadyRef.current = onReady;

  useEffect(() => {
    const container = containerRef.current;
    if (!container || mapRef.current) return undefined;

    const map = L.map(container, {
      center,
      zoom,
      minZoom: 1,
      // The terminator spans the whole globe, so a hard longitude limit would
      // hide half of it. `worldCopyJump` keeps the pins and the arcs aligned
      // when the view jumps between world copies.
      worldCopyJump: true,
      attributionControl: true,
      zoomControl: true,
    });

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 18,
      attribution: '&copy; OpenStreetMap contributors',
    }).addTo(map);

    const layers = L.layerGroup().addTo(map);

    mapRef.current = map;
    layersRef.current = layers;

    onReadyRef.current?.(map, layers);

    return () => {
      map.remove();
      mapRef.current = null;
      layersRef.current = null;
    };
    // Intentionally mounted once. Center and zoom are initial values; changing
    // them is done by calling setView on the returned ref, not by remounting.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { containerRef, mapRef, layersRef };
}
