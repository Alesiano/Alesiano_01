import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  // Vercel 部署需要以下配置
  base: '/',
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
  },
  server: {
    port: 5173,
    // 开发时把 /api 请求转发到 Python 后端，避免跨域问题
    proxy: {
      '/api': 'http://localhost:8080',
    },
  },
})
