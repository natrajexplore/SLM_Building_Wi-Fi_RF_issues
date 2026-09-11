import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The FastAPI backend runs on :8090 (moved off the default :8000, which on
// this dev machine collides with another project's backend); the dev server
// proxies API calls to it so the frontend can use same-origin relative paths.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5190,
    strictPort: true,
    proxy: {
      '/diagnose': 'http://localhost:8090',
      '/explain': 'http://localhost:8090',
      '/ingest': 'http://localhost:8090',
      '/live': 'http://localhost:8090',
      '/retrieve': 'http://localhost:8090',
      '/ask': 'http://localhost:8090',
      '/taxonomy': 'http://localhost:8090',
      '/health': 'http://localhost:8090',
    },
  },
})
