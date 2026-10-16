import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Proxying keeps the browser on one origin in development, so there is no
    // CORS preflight and the backend's CORS_ORIGIN setting stays irrelevant
    // locally. In production the frontend is served as static files and points
    // at the API with VITE_API_BASE.
    proxy: {
      '/api': {
        target: 'http://localhost:8787',
        changeOrigin: true,
      },
    },
  },
});
