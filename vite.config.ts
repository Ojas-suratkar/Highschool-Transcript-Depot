import { defineConfig } from 'vite'
import path from 'path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  // Serve the frontend app located in apps/frontend
  root: path.resolve(__dirname, './apps/frontend'),
  publicDir: 'public',
  plugins: [
    // The React and Tailwind plugins are both required for Make, even if
    // Tailwind is not being actively used – do not remove them
    react(),
    tailwindcss(),
  ],
  resolve: {
      alias: {
      // Alias @ to the frontend src directory (moved to apps/frontend/src)
      '@': path.resolve(__dirname, './apps/frontend/src'),
    },
  },
  server: {
    proxy: {
      // Proxy API calls to the backend dev server
      '/auth': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
      },
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
      }
    }
  }
})
