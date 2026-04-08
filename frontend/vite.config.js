import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/tender': 'http://localhost:8000',
      '/ingest': 'http://localhost:8000',
      '/kb':     'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
})
