/**
 * A browser-ish global environment for the map tests.
 *
 * Leaflet reads `window` and `document` at module load and probes a few layout
 * APIs, so the globals have to exist *before* `leaflet` is imported. Node's
 * module cache makes that ordering easy to get wrong: importing anything that
 * transitively imports Leaflet first would freeze a broken binding. Every map
 * test therefore imports this module before anything else.
 */
import { JSDOM } from 'jsdom';

const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', {
  pretendToBeVisual: true,
  url: 'http://localhost/',
});

const { window } = dom;

// jsdom does not implement these and Leaflet calls them while measuring the
// container. Without them the map throws before a single layer is added.
window.HTMLElement.prototype.getBoundingClientRect = function getBoundingClientRect() {
  return { width: 800, height: 600, top: 0, left: 0, right: 800, bottom: 600, x: 0, y: 0, toJSON: () => ({}) };
};
window.HTMLElement.prototype.getClientRects = function getClientRects() {
  return [{ width: 800, height: 600, top: 0, left: 0, right: 800, bottom: 600, x: 0, y: 0 }];
};

/**
 * Assign through `defineProperty`, not `globalThis.x = ...`.
 *
 * Node ships its own `navigator` as a getter-only property, so a plain
 * assignment throws "Cannot set property navigator of #<Object> which has only
 * a getter" on Node 21+. Defining the property replaces it on every version.
 */
const define = (name, value) => {
  Object.defineProperty(globalThis, name, {
    value,
    writable: true,
    configurable: true,
    enumerable: true,
  });
};

define('window', window);
define('document', window.document);
define('navigator', window.navigator);
define('HTMLElement', window.HTMLElement);
define('Element', window.Element);
define('Node', window.Node);
define('SVGElement', window.SVGElement);
define('getComputedStyle', window.getComputedStyle.bind(window));
define('requestAnimationFrame', window.requestAnimationFrame.bind(window));
define('cancelAnimationFrame', window.cancelAnimationFrame.bind(window));
// Without this React warns that act() is unsupported and does not flush effects
// synchronously, which would make every assertion below race the render.
define('IS_REACT_ACT_ENVIRONMENT', true);

export { window, dom };
