/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { defineConfig, loadEnv } from 'vite'

// VITE_BASE is set by the GitHub Pages workflow (e.g. "/Mindex/").
export default defineConfig(({ mode }) => {
  // process.env holds the shell's variables only; loadEnv adds .env, .env.[mode] and their
  // .local files, so VITE_API_PROXY can live in .env.development.local.
  const env = { ...loadEnv(mode, process.cwd()), ...process.env }
  return {
    base: env.VITE_BASE ?? '/',
    plugins: [react(), tailwindcss()],
    // Real API in development (VITE_USE_MOCKS=false): same origin, so no CORS is needed.
    server: {
      proxy: { '/api': { target: env.VITE_API_PROXY ?? 'http://127.0.0.1:8000' } },
    },
    resolve: {
      alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
    },
    build: {
      sourcemap: true,
      rollupOptions: {
        output: {
          manualChunks: (id) => (id.includes('lightweight-charts') ? 'charts' : undefined),
        },
      },
    },
    test: {
      environment: 'jsdom',
      // Tests run against the MSW mock API, like `npm run dev`.
      env: { VITE_USE_MOCKS: 'true' },
      setupFiles: ['./src/test/setup.tsx'],
      css: false,
      coverage: {
        provider: 'v8',
        include: ['src/**/*.{ts,tsx}'],
        exclude: ['src/**/*.test.{ts,tsx}', 'src/test/**', 'src/main.tsx'],
        // NF5: >= 70% coverage; the build fails below this.
        thresholds: { lines: 70, functions: 70, branches: 70, statements: 70 },
      },
    },
  }
})
