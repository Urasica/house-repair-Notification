import { defineConfig, devices } from '@playwright/test'

const baseURL = process.env.E2E_BASE_URL ?? 'http://localhost:18080'
const allowLocalCertificate = process.env.E2E_ALLOW_SELF_SIGNED === 'true'
if (allowLocalCertificate && new URL(baseURL).hostname !== 'localhost') {
  throw new Error('Self-signed certificate bypass is restricted to localhost')
}

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 45000,
  outputDir: '../artifacts/playwright',
  reporter: [['list']],
  use: { baseURL, ignoreHTTPSErrors: allowLocalCertificate, trace: 'retain-on-failure' },
  projects: [
    { name: 'chromium-desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1000 } } },
    { name: 'chromium-mobile', use: { ...devices['Pixel 7'], viewport: { width: 360, height: 800 } } },
  ],
})
