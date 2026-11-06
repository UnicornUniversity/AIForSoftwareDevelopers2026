import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Proxying keeps the browser on one origin in development: no CORS preflight,
// and the API needs no CORS middleware of its own. `preview` gets the same proxy
// so `npm run build && npm run preview` is a working local production check.
const proxy = {
  '/api': {
    target: 'http://localhost:8788',
    changeOrigin: true,
  },
};

export default defineConfig({
  plugins: [react()],
  server: {
    // 5174 rather than 5173 so this app can run beside sunset-chaser's frontend.
    port: 5174,
    proxy,
  },
  preview: {
    port: 4173,
    proxy,
  },
});
