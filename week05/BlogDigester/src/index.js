import { createApp } from './app.js';
import { config } from './config.js';

const server = createApp().listen(config.port, () => {
  const { port } = server.address();
  console.log(`listening on http://localhost:${port}`);
  console.log(`model: ${config.llm.model} via ${config.llm.baseURL}`);
});

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    console.log(`\n${signal} received, shutting down.`);
    server.close(() => process.exit(0));
  });
}
