import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://localhost:8010',
        changeOrigin: true,
        // SSE 路径需要禁用缓冲，否则前端收不到流式事件
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            // 告诉代理不要缓冲 SSE 响应
            proxyRes.headers['x-accel-buffering'] = 'no'
            proxyRes.headers['cache-control'] = 'no-cache'
          })
        },
      },
    },
  },
})
