// ABOUTME: Playwright settings for the browser end to end tests against the real API on port 5309.
// ABOUTME: The web server step seeds a fresh database, then starts the API; the bundle must be built.
import { resolve } from "node:path";
import { defineConfig } from "@playwright/test";

const dataDir = resolve(import.meta.dirname, ".e2e-data");
// A copy of the fictional sample bank, made by the seed script: the fact bank screen edits it.
const bank = resolve(dataDir, "bank.yaml");

export default defineConfig({
  testDir: "tests/e2e",
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:5309", headless: true },
  webServer: [
    {
      // A hand written model for the Draft help tests: it drafts when asked and refuses the rest.
      command: "uv run python scripts/ui_chat_server.py",
      cwd: "..",
      url: "http://127.0.0.1:5319/health",
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: `sh -c 'rm -rf "${dataDir}" && uv run python scripts/seed_ui_fixtures.py && exec uv run cypress-creek-api'`,
      cwd: "..",
      url: "http://127.0.0.1:5309/api/health",
      reuseExistingServer: false,
      timeout: 90_000,
      env: {
        CYPRESS_CREEK_DATA_DIR: dataDir,
        CYPRESS_CREEK_BANK: bank,
        CYPRESS_CREEK_PROVIDER: "openai_compatible",
        CYPRESS_CREEK_MODEL: "ui-test-model",
        CYPRESS_CREEK_BASE_URL: "http://127.0.0.1:5319/v1",
        CYPRESS_CREEK_CONTEXT_TOKENS: "8192",
      },
    },
  ],
});
