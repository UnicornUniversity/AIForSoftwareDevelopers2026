/**
 * Runs one of the frontend checks.
 *
 * The checks are `.jsx` and import application source, so they need a JSX
 * transform and module resolution - they cannot be handed to `node` directly the
 * way the backend's `node --test` suites can. Rather than add a second test
 * runner, this bundles the check with the Vite that is already a dev dependency
 * and then runs the bundle in Node.
 *
 * Dependencies stay external (`build.ssr` externalises `node_modules` by
 * default), so the bundle is a few kilobytes of our own code and Node resolves
 * React, Leaflet and the rest from the install that is already there.
 *
 * Output goes to `node_modules/.cache/`, which is inside the install the checks
 * are built against and is already ignored by the root `.gitignore`'s
 * `node_modules` rule - a build artefact that needs no ignore entry of its own.
 */
import { spawnSync } from 'node:child_process';
import { readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import react from '@vitejs/plugin-react';

const CHECKS = {
  // Needs a DOM before Leaflet is imported, hence the preload, and React's
  // development build, because `act` - the only correct way to flush effects
  // around a render outside a browser - is not exported by the production one.
  map: { entry: 'test/map.check.jsx', preloadDom: true, nodeEnv: 'development' },
  // Pure server rendering against a live payload, with the fixture as fallback.
  api: { entry: 'test/render.check.jsx', preloadDom: false, nodeEnv: 'production' },
  // The real page against a stubbed fetch, so it needs a DOM and `act` too.
  chase: { entry: 'test/chase.check.jsx', preloadDom: true, nodeEnv: 'development' },
};

const name = process.argv[2];
const check = CHECKS[name];
if (!check) {
  console.error(`usage: node test/run-check.mjs <${Object.keys(CHECKS).join('|')}>`);
  process.exit(2);
}

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const outDir = path.join(root, 'node_modules', '.cache', 'checks', name);

await build({
  root,
  // The app's own `vite.config.js` proxies /api for `vite dev` and has nothing
  // to say about a Node bundle, so it is deliberately not loaded.
  configFile: false,
  logLevel: 'warn',
  plugins: [react()],
  build: {
    ssr: path.join(root, check.entry),
    outDir,
    emptyOutDir: true,
    minify: false,
    target: 'node20',
  },
});

const bundle = readdirSync(outDir).find((file) => file.endsWith('.js') || file.endsWith('.mjs'));
if (!bundle) {
  console.error(`vite produced no bundle in ${outDir}`);
  process.exit(1);
}

const args = [
  ...(check.preloadDom ? ['--import', './test/setup-dom.js'] : []),
  path.join(outDir, bundle),
];

const result = spawnSync(process.execPath, args, {
  cwd: root,
  stdio: 'inherit',
  env: { ...process.env, NODE_ENV: check.nodeEnv },
});
if (result.error) throw result.error;
process.exit(result.status ?? 1);
