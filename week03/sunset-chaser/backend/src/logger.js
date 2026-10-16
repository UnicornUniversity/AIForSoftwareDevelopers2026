const LEVELS = { debug: 10, info: 20, warn: 30, error: 40 };
const threshold = LEVELS[process.env.LOG_LEVEL] ?? LEVELS.info;

function emit(level, message, fields) {
  if (LEVELS[level] < threshold) return;
  const parts = [`${new Date().toISOString()} ${level.toUpperCase().padEnd(5)} ${message}`];
  if (fields && Object.keys(fields).length > 0) {
    parts.push(
      Object.entries(fields)
        .map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`)
        .join(' '),
    );
  }
  const line = parts.join('  ');
  if (level === 'error') console.error(line);
  else if (level === 'warn') console.warn(line);
  else console.log(line);
}

export const log = {
  debug: (m, f) => emit('debug', m, f),
  info: (m, f) => emit('info', m, f),
  warn: (m, f) => emit('warn', m, f),
  error: (m, f) => emit('error', m, f),
};
