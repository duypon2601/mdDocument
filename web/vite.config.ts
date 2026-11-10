import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vitest/config'

const API = 'http://localhost:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: fileURLToPath(new URL('../packages/api/src/ingest/api/static/dist', import.meta.url)),
    emptyOutDir: true,
  },
  server: {
    // Chỉ proxy API. GET /search là route của SPA nên để Vite trả index.html.
    proxy: {
      '/documents': API,
      '/stats': API,
      '/temporal': API,
      '/search': {
        target: API,
        bypass: (req) => (req.method === 'GET' ? '/index.html' : undefined),
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
    css: false,
  },
})
