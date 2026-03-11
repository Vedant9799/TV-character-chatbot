import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Backend port selection:
//   npm run dev                        → Ollama server (port 8001)
//   VITE_BACKEND_PORT=8000 npm run dev → HuggingFace server (port 8000)
const BACKEND_PORT = process.env.VITE_BACKEND_PORT ?? '8001'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Proxy WebSocket connections to the FastAPI backend
      '/ws': {
        target: `ws://localhost:${BACKEND_PORT}`,
        ws: true,
        changeOrigin: true,
      },
      // Proxy REST endpoints
      '/characters': {
        target: `http://localhost:${BACKEND_PORT}`,
        changeOrigin: true,
      },
    },
  },
  build: {
    // Vercel builds from ui/ and expects output in ui/dist (configured in vercel.json).
    // For local dev, `npm run dev` uses the Vite dev server with proxy — no build needed.
    outDir: 'dist',
    emptyOutDir: true,
  },
})
