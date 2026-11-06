/**
 * Launcher for `npm start` / `npm run dev`.
 *
 * HTTPS calls to DeepSeek pass through a TLS-inspecting antivirus or corporate
 * proxy on some networks. Windows tools accept the intercepted chain because
 * the root CA is in the OS certificate store; Node reads its own bundled CA
 * list, so those connections fail with SELF_SIGNED_CERT_IN_CHAIN and the answer
 * silently falls back to extractive text.
 *
 * `--use-system-ca` (Node >= 24) makes Node read the OS store as well, which
 * resolves that. The flag does not exist on older Node, where passing it is a
 * startup error, so it is added only when this interpreter supports it. The
 * server keeps its Node >= 20.12 floor either way.
 *
 * An extra process rather than a changed `start` script: `npm run dev` needs
 * `--watch` passed through too, and the child inherits the same console, so
 * signals and exit codes behave as they did when npm spawned the server
 * directly.
 */

import { spawn } from 'node:child_process';

const systemCa = process.allowedNodeEnvironmentFlags.has('--use-system-ca')
  ? ['--use-system-ca']
  : [];

const child = spawn(
  process.execPath,
  [...systemCa, ...process.argv.slice(2), 'src/index.js'],
  { stdio: 'inherit' },
);

child.on('exit', (code, signal) => {
  // A signalled child already told the terminal why; keep the exit non-zero.
  process.exit(signal ? 1 : (code ?? 0));
});

child.on('error', (err) => {
  console.error(`[startup] could not launch node: ${err.message}`);
  process.exit(1);
});
