import { createApp } from './app.js';
import { config } from './config.js';

const server = createApp().listen(config.port, () => {
  console.log(`listening on http://localhost:${config.port}`);
  console.log(`DeepSeek: ${config.deepseek.model} via ${config.deepseek.baseURL}`);
});

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    console.log(`\n${signal} received, shutting down.`);
    server.close(() => process.exit(0));
  });
}
