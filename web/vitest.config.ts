/// <reference types="vitest" />
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

// Dedicated Vitest config (separate from vite.config.ts) so the dev-server
// data/translation plugin does not run during the test suite.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/**/*.test.{ts,tsx}'],
    setupFiles: ['./vitest.setup.ts'],
    coverage: {
      provider: 'v8',
      include: ['src/lib/**', 'src/utils/**', 'src/hooks/**'],
      reporter: ['text', 'text-summary'],
    },
  },
});
