import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// The dev server proxies API and WebSocket calls to the FastAPI backend on :8000.
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', rewrite: (p) => p.replace(/^\/api/, ''), ws: true },
    },
  },
})
