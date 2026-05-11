// @ts-check
/**
 * Playwright config — smoke E2E contra produção.
 * Use: npm run test:e2e
 */
const { defineConfig, devices } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './tests',
  timeout: 90_000,               // ved_varejo.js (8MB) demora pra parsear no headless
  fullyParallel: false,         // smokes contra mesma URL — serial é mais estável
  retries: 1,                    // 1 retry pra cache miss / cold start do CF
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: process.env.VM_URL || 'https://anselmi-roi.pages.dev',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
});
