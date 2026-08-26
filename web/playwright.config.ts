import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  use: {
    baseURL: 'http://127.0.0.1:5173',
  },
  webServer: [
    {
      command: "rm -f /tmp/starklabs-model-evals-e2e.sqlite && STARKLABS_SESSION_TOKEN=browser-smoke UV_CACHE_DIR=../.uv-cache uv run --project .. python -m starklabs_evals.server --db /tmp/starklabs-model-evals-e2e.sqlite --host 127.0.0.1 --port 8765",
      url: 'http://127.0.0.1:8765/api/health',
      reuseExistingServer: false,
    },
    {
      command: 'npm run dev -- --strictPort',
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: !process.env.CI,
    },
  ],
});
