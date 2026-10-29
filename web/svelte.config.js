// ABOUTME: Svelte compiler settings for the web UI: TypeScript in components, nothing else special.
// ABOUTME: {@html} is banned by the lint rule and by scripts/check-dist.mjs, not by this file.
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

export default {
  preprocess: vitePreprocess(),
};
