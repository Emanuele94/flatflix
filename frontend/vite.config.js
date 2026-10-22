import { defineConfig } from 'vite';
import preact from '@preact/preset-vite';

// base '/' : the portal is served at the origin root (D-05).
// The TV app later builds with base '/tv/'.
export default defineConfig({
  base: '/',
  plugins: [preact()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
  build: {
    outDir: 'dist',
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{js,jsx}'],
  },
});
