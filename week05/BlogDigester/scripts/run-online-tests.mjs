/**
 * Cross-platform wrapper for the opt-in online suite.
 *
 * It exists because `RUN_ONLINE=1 node --test ...` is shell-specific: this works
 * from PowerShell, cmd and POSIX shells alike, with no `cross-env` dependency.
 */

import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');

const child = spawn(
  process.execPath,
  ['--test', 'test/online/online.test.js'],
  {
    cwd: root,
    stdio: 'inherit',
    env: { ...process.env, RUN_ONLINE: '1' },
  },
);

child.on('error', (err) => {
  console.error(`[online] could not start the test runner: ${err.message}`);
  process.exit(1);
});

child.on('exit', (code, signal) => {
  if (signal) {
    console.error(`[online] test runner terminated by ${signal}`);
    process.exit(1);
  }
  process.exit(code ?? 1);
});
