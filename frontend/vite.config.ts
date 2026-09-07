import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The FastAPI backend runs on :8000; the dev server proxies API calls to it so
// the frontend can use same-origin relative paths.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/diagnose': 'http://localhost:8000',
      '/explain': 'http://localhost:8000',
      '/ingest': 'http://localhost:8000',
      '/live': 'http://localhost:8000',
      '/retrieve': 'http://localhost:8000',
      '/ask': 'http://localhost:8000',
      '/taxonomy': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
})
