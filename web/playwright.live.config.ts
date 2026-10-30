// ABOUTME: Playwright settings for the model backed UI test: the real API with a real local Ollama.
// ABOUTME: Run by live.yml and by hand with Ollama running; an absent Ollama fails the test, never skips.
import { resolve } from "node:path";
import { defineConfig } from "@playwright/test";

const dataDir = resolve(import.meta.dirname, ".e2e-live-data");
const bank = resolve(import.meta.dirname, "..", "evals", "bank", "sample_bank.yaml");
const model = process.env["CYPRESS_CREEK_LIVE_MODEL"] ?? "qwen3.5:0.8b";
const baseUrl = process.env["CYPRESS_CREEK_LIVE_BASE_URL"] ?? "http://localhost:11434";

export default defineConfig({
  testDir: "tests/live",
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  timeout: 240_000,
  use: { baseURL: "http://127.0.0.1:5309", headless: true },
  webServer: {
    command: `sh -c 'rm -rf "${dataDir}" && exec uv run cypress-creek-api'`,
    cwd: "..",
    url: "http://127.0.0.1:5309/api/health",
    reuseExistingServer: false,
    timeout: 90_000,
    env: {
      CYPRESS_CREEK_DATA_DIR: dataDir,
      CYPRESS_CREEK_BANK: bank,
      CYPRESS_CREEK_PROVIDER: "ollama",
      CYPRESS_CREEK_MODEL: model,
      CYPRESS_CREEK_BASE_URL: baseUrl,
      CYPRESS_CREEK_CONTEXT_TOKENS: "8192",
    },
  },
});
