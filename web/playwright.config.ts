// ABOUTME: Playwright settings for the browser end to end tests against the real API on port 5309.
// ABOUTME: The web server step seeds a fresh database, then starts the API; the bundle must be built.
import { resolve } from "node:path";
import { defineConfig } from "@playwright/test";

const dataDir = resolve(import.meta.dirname, ".e2e-data");
const bank = resolve(import.meta.dirname, "..", "evals", "bank", "sample_bank.yaml");

export default defineConfig({
  testDir: "tests/e2e",
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:5309", headless: true },
  webServer: {
    command: `sh -c 'rm -rf "${dataDir}" && uv run python scripts/seed_ui_fixtures.py && exec uv run cypress-creek-api'`,
    cwd: "..",
    url: "http://127.0.0.1:5309/api/health",
    reuseExistingServer: false,
    timeout: 90_000,
    env: {
      CYPRESS_CREEK_DATA_DIR: dataDir,
      CYPRESS_CREEK_BANK: bank,
      // Nothing listens on the discard port, so the backend is down, like a real outage.
      CYPRESS_CREEK_PROVIDER: "ollama",
      CYPRESS_CREEK_MODEL: "qwen3.5:0.8b",
      CYPRESS_CREEK_BASE_URL: "http://127.0.0.1:9",
    },
  },
});
