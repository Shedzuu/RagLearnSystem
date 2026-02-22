import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Когда подключите бекенд — раскомментируйте и укажите порт Django
      // '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
