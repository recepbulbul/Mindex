import { defineConfig, devices } from '@playwright/test'

// A dedicated port: 5173 stays free for `npm run dev`.
const PORT = 5183
const isCi = !!process.env.CI

export default defineConfig({
  testDir: './e2e',
  // Every page runs its own MSW mock API (state lives in the tab), so tests never share data.
  fullyParallel: true,
  forbidOnly: isCi,
  retries: isCi ? 1 : 0,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  reporter: isCi ? [['github'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL: `http://localhost:${PORT}`,
    locale: 'tr-TR',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `npm run dev -- --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}`,
    // The mock API, whatever .env.development.local says: no backend, database or LLM.
    env: { VITE_USE_MOCKS: 'true' },
    reuseExistingServer: !isCi,
    timeout: 120_000,
  },
})
