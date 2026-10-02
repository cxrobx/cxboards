import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server proxies the API to the running CXBoards server; `npm run build`
// writes web/dist, which the server itself serves on :4870.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 4871,
    proxy: {
      '/api': 'http://127.0.0.1:4870',
      '/media': 'http://127.0.0.1:4870',
    },
  },
})
