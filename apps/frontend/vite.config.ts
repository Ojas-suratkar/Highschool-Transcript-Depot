import { defineConfig } from 'vite'
import path from 'path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import './scripts/polyfill-structured-clone'

export default defineConfig({
  // Now that this config lives in apps/frontend, the project root is THIS folder
  root: __dirname,

  // These paths are relative to `root`
  publicDir: 'public',

  plugins: [
    react(),
    tailwindcss(),
  ],

  resolve: {
    alias: {
      // Alias @ to apps/frontend/src
      '@': path.resolve(__dirname, 'src'),
    },
  },

  // Dev server settings (local docker-compose)
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/auth': {
  target: process.env.BACKEND_URL || 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
      },
      '/api': {
  target: process.env.BACKEND_URL || 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
      },
    },
  },

  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
