// ABOUTME: Vite and Vitest settings. The dev server is on 5150 and proxies /api to the API on 5309.
// ABOUTME: Everything is local: no remote origin, no CDN. Unit coverage below 80 percent fails.
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [svelte()],
  server: {
    host: "127.0.0.1",
    port: 5150,
    strictPort: true,
    // The API only answers the Host 127.0.0.1:5309, so the proxy must rewrite the Host header.
    proxy: { "/api": { target: "http://127.0.0.1:5309", changeOrigin: true } },
  },
  build: { outDir: "dist", sourcemap: false },
  resolve: process.env["VITEST"] ? { conditions: ["browser"] } : {},
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts", "scripts/**/*.test.ts"],
    coverage: {
      provider: "v8",
      include: ["src/**/*.ts", "src/**/*.svelte", "scripts/check-dist.mjs"],
      exclude: ["src/main.ts", "src/lib/types.ts", "src/test-support.ts", "**/*.test.ts"],
      thresholds: { lines: 80, functions: 80, branches: 80, statements: 80 },
    },
  },
});
