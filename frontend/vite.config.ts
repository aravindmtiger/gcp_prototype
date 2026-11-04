import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The single root .env (one directory up) is shared with the backend. Only UI_* keys
// are exposed to the browser bundle, so secrets such as DATABASE_URL never leak here.
export default defineConfig({
  plugins: [react()],
  envDir: '..',
  envPrefix: 'UI_',
  server: { port: 5173 },
  test: { environment: 'node', include: ['src/**/*.test.ts'] },
});
