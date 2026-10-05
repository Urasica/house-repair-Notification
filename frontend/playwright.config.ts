import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 45000,
  outputDir: '../artifacts/playwright',
  reporter: [['list']],
  use: { baseURL: 'http://localhost:18080', trace: 'retain-on-failure' },
  projects: [{ name: 'chromium-mobile', use: { ...devices['Desktop Chrome'], viewport: { width: 360, height: 800 } } }],
})
