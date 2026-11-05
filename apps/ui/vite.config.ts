import react from '@vitejs/plugin-react';
import path from 'node:path';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@ohd/shared-types': path.resolve(__dirname, '../../packages/shared-types/src/index.ts'),
    },
  },
  server: { port: 5173, strictPort: true },
  base: './',
  build: { outDir: 'dist', emptyOutDir: true, sourcemap: false },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
  },
});
