// ABOUTME: ESLint rules for the web UI. The {@html} ban is an error here, so it cannot be merged.
// ABOUTME: Type aware TypeScript rules in strict mode, Svelte recommended rules, zero warnings.
import js from "@eslint/js";
import globals from "globals";
import svelte from "eslint-plugin-svelte";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist/", "coverage/", "node_modules/", "test-results/", "playwright-report/", ".e2e-data/"] },
  js.configs.recommended,
  ...tseslint.configs.strictTypeChecked,
  ...svelte.configs["flat/recommended"],
  {
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
      parserOptions: {
        projectService: true,
        extraFileExtensions: [".svelte"],
      },
    },
    rules: {
      "svelte/no-at-html-tags": "error",
      "svelte/no-target-blank": "error",
      "no-restricted-syntax": [
        "error",
        { selector: "AssignmentExpression[left.property.name='innerHTML']", message: "No innerHTML." },
        { selector: "AssignmentExpression[left.property.name='outerHTML']", message: "No outerHTML." },
        { selector: "CallExpression[callee.property.name='insertAdjacentHTML']", message: "No insertAdjacentHTML." },
        { selector: "CallExpression[callee.name='eval']", message: "No eval." },
        { selector: "NewExpression[callee.name='Function']", message: "No new Function." },
      ],
    },
  },
  {
    files: ["**/*.svelte"],
    languageOptions: { parserOptions: { parser: tseslint.parser } },
  },
  {
    files: ["**/*.js", "**/*.mjs", "scripts/**"],
    ...tseslint.configs.disableTypeChecked,
  },
);
