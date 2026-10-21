import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

/**
 * 后端地址用 VITE_API_TARGET 覆盖，避免把某台机器的端口写死。
 * 本地 .env.development 当前指向 8011：本机 8000 / 8010 已被其他服务占用。
 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const apiTarget = env.VITE_API_TARGET || 'http://localhost:8000'

  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: 5174,
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
        },
      },
      hmr: {
        overlay: false,
      },
    },
  }
})
