// ABOUTME: Build check for the web UI: no {@html} in the sources, no inline script or remote origin in dist.
// ABOUTME: Run by `npm run verify` and in CI; it exits 1 and lists every problem it finds.
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parse } from "svelte/compiler";

// Strings that look like origins but are not requests: the SVG namespace and Svelte's own
// error message links. Anything else with http(s):// in the bundle is a remote origin.
const HARMLESS_ORIGINS = /^https?:\/\/(?:www\.w3\.org\/|svelte\.dev\/)/;

function filesUnder(root, suffixes) {
  const found = [];
  for (const name of readdirSync(root)) {
    const path = join(root, name);
    if (statSync(path).isDirectory()) found.push(...filesUnder(path, suffixes));
    else if (suffixes.some((suffix) => name.endsWith(suffix))) found.push(path);
  }
  return found;
}

function containsHtmlTag(node) {
  if (Array.isArray(node)) return node.some(containsHtmlTag);
  if (node === null || typeof node !== "object") return false;
  if (node.type === "HtmlTag") return true;
  return Object.values(node).some(containsHtmlTag);
}

/** Every .svelte file under root, parsed. {@html} anywhere is a problem, and so is a parse failure. */
export function checkSources(root) {
  const problems = [];
  for (const path of filesUnder(root, [".svelte"])) {
    const name = relative(root, path);
    try {
      const ast = parse(readFileSync(path, "utf-8"), { modern: true });
      if (containsHtmlTag(ast.fragment)) problems.push(`${name}: {@html} is banned`);
    } catch (error) {
      problems.push(`${name}: could not be parsed (${error.message})`);
    }
  }
  return problems;
}

function remoteOrigins(text) {
  return (text.match(/https?:\/\/[^\s"'`)\\<>]+/g) ?? []).filter((url) => !HARMLESS_ORIGINS.test(url));
}

function checkHtml(name, html) {
  const problems = [];
  if (/<script(?![^>]*\bsrc\s*=)[^>]*>/i.test(html)) problems.push(`${name}: inline script`);
  if (/\son[a-z]+\s*=/i.test(html)) problems.push(`${name}: inline event handler`);
  if (/javascript:/i.test(html)) problems.push(`${name}: javascript: URL`);
  if (/\sstyle\s*=/i.test(html)) problems.push(`${name}: inline style attribute`);
  return problems;
}

/** The built bundle: no inline script, no inline handler, no eval, no remote origin. */
export function checkDist(dist) {
  const index = join(dist, "index.html");
  if (!existsSync(index)) return [`index.html: not found in ${dist}, run npm run build first`];
  const problems = [];
  for (const path of filesUnder(dist, [".html", ".js", ".css"])) {
    const name = relative(dist, path);
    const text = readFileSync(path, "utf-8");
    if (name.endsWith(".html")) problems.push(...checkHtml(name, text));
    for (const origin of remoteOrigins(text)) problems.push(`${name}: remote origin ${origin}`);
    if (name.endsWith(".js")) {
      if (/\beval\s*\(/.test(text)) problems.push(`${name}: eval`);
      if (/\bnew\s+Function\s*\(/.test(text)) problems.push(`${name}: new Function`);
    }
  }
  return problems;
}

function main() {
  const here = dirname(fileURLToPath(import.meta.url));
  const web = resolve(here, "..");
  const problems = [...checkSources(join(web, "src")), ...checkDist(join(web, "dist"))];
  for (const problem of problems) console.error(problem);
  if (problems.length > 0) process.exit(1);
  console.log("check-dist: ok");
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
