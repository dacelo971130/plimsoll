import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        // Must match .claude/launch.json's "plimsoll-backend" port — that's
        // the port `npm run dev` actually gets started alongside in this
        // repo. A mismatch here means every /api/* call 502s and features
        // like 載入示範資料 silently do nothing. 8110, not 8099 — Postman
        // Interceptor owns 8099 (see docker-compose.yml).
        target: 'http://localhost:8110',
        changeOrigin: true,
      },
    },
  },
})
