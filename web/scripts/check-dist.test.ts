// ABOUTME: Tests the build check: it must fail on {@html}, inline scripts and remote origins.
// ABOUTME: Each failing case is built in a scratch folder, so the ban is proven, not assumed.
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
// @ts-expect-error the check script is plain JavaScript
import { checkDist, checkSources } from "./check-dist.mjs";

const folders: string[] = [];

function scratch(files: Record<string, string>): string {
  const root = mkdtempSync(join(tmpdir(), "check-dist-"));
  folders.push(root);
  for (const [name, text] of Object.entries(files)) {
    const target = join(root, name);
    mkdirSync(join(target, ".."), { recursive: true });
    writeFileSync(target, text, "utf-8");
  }
  return root;
}

afterEach(() => {
  for (const folder of folders.splice(0)) rmSync(folder, { recursive: true, force: true });
});

const CLEAN_COMPONENT = "<p>{text}</p>\n<script lang=\"ts\">let text = $state('x');</script>\n";

describe("checkSources", () => {
  it("passes components that only use text interpolation", () => {
    const root = scratch({ "A.svelte": CLEAN_COMPONENT });
    expect(checkSources(root)).toEqual([]);
  });

  it("fails on {@html}, wherever it is", () => {
    const root = scratch({
      "A.svelte": CLEAN_COMPONENT,
      "deep/B.svelte": "<div>{@html danger}</div>\n<script lang=\"ts\">let danger = 'x';</script>\n",
    });
    const problems = checkSources(root) as string[];
    expect(problems).toHaveLength(1);
    expect(problems[0]).toContain("B.svelte");
    expect(problems[0]).toContain("{@html}");
  });

  it("fails on {@html} inside a block or an attribute-adjacent expression", () => {
    const root = scratch({
      "C.svelte": "{#if ok}{@html raw}{/if}\n<script lang=\"ts\">let ok = true; let raw = 'x';</script>\n",
    });
    expect(checkSources(root)).toHaveLength(1);
  });

  it("reports a component it cannot parse instead of skipping it", () => {
    const root = scratch({ "D.svelte": "<div>{#if}</div>" });
    const problems = checkSources(root) as string[];
    expect(problems[0]).toContain("D.svelte");
  });
});

describe("checkDist", () => {
  const goodHtml =
    '<!doctype html><html><head><script type="module" src="/assets/app.js"></script>' +
    '<link rel="stylesheet" href="/assets/app.css"></head><body><div id="app"></div></body></html>';

  it("passes a bundle with only external local files", () => {
    const root = scratch({
      "index.html": goodHtml,
      "assets/app.js": 'const a = document.createElementNS("http://www.w3.org/2000/svg", "svg");',
      "assets/app.css": "body{color:#111}",
    });
    expect(checkDist(root)).toEqual([]);
  });

  it("fails when the page has an inline script", () => {
    const root = scratch({ "index.html": goodHtml.replace("</body>", "<script>alert(1)</script></body>") });
    expect((checkDist(root) as string[]).join()).toContain("inline script");
  });

  it("fails on inline event handlers and javascript: links", () => {
    const root = scratch({
      "index.html": goodHtml.replace('<div id="app">', '<div id="app" onclick="x()"><a href="javascript:x()">a</a>'),
    });
    const text = (checkDist(root) as string[]).join();
    expect(text).toContain("inline event handler");
    expect(text).toContain("javascript:");
  });

  it("fails on a remote origin in the page, the script or the styles", () => {
    const root = scratch({
      "index.html": goodHtml.replace("/assets/app.css", "https://cdn.example/app.css"),
      "assets/app.js": 'fetch("https://evil.example/x")',
      "assets/app.css": "@import url(https://fonts.example/f.css);",
    });
    const text = (checkDist(root) as string[]).join("\n");
    expect(text).toContain("index.html");
    expect(text).toContain("app.js");
    expect(text).toContain("app.css");
  });

  it("fails on eval and new Function in the bundle", () => {
    const root = scratch({
      "index.html": goodHtml,
      "assets/app.js": "eval('1'); new Function('return 1');",
    });
    const text = (checkDist(root) as string[]).join("\n");
    expect(text).toContain("eval");
    expect(text).toContain("Function");
  });

  it("fails when there is no bundle at all", () => {
    const root = scratch({});
    expect((checkDist(root) as string[])[0]).toContain("index.html");
  });
});
