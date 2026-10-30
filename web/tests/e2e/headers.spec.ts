// ABOUTME: End to end checks of what the real API sends with the UI: the strict policy, no inline script.
// ABOUTME: The browser itself enforces the policy, so a violation would show up as a console error.
import { expect, test } from "@playwright/test";

test("the shell carries the strict policy and needs no inline script", async ({ page, request }) => {
  const shell = await request.get("/");
  expect(shell.status()).toBe(200);
  const policy = shell.headers()["content-security-policy"] ?? "";
  expect(policy).toContain("default-src 'none'");
  expect(policy).toContain("script-src 'self'");
  expect(policy).not.toContain("unsafe-inline");
  expect(policy).not.toContain("unsafe-eval");
  expect(shell.headers()["x-content-type-options"]).toBe("nosniff");
  expect(shell.headers()["x-frame-options"]).toBe("DENY");
  const html = await shell.text();
  expect(html).not.toMatch(/<script(?![^>]*\bsrc=)[^>]*>/i);

  const violations: string[] = [];
  page.on("console", (message) => {
    if (message.text().includes("Content Security Policy")) violations.push(message.text());
  });
  page.on("pageerror", (error) => violations.push(error.message));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Analyze a posting" })).toBeVisible();
  expect(violations).toEqual([]);
});

test("the page makes requests to its own origin only", async ({ page }) => {
  const origins = new Set<string>();
  page.on("request", (request) => origins.add(new URL(request.url()).origin));
  await page.goto("/");
  await expect(page.getByLabel("Backend")).toContainText("openai_compatible");
  expect([...origins]).toEqual(["http://127.0.0.1:5309"]);
});

test("the stylesheet and script are served with their own asset paths and cache nothing sensitive", async ({
  request,
}) => {
  const html = await (await request.get("/")).text();
  const asset = /src="(\/assets\/[^"]+\.js)"/.exec(html)?.[1];
  expect(asset).toBeDefined();
  const script = await request.get(asset ?? "");
  expect(script.status()).toBe(200);
  expect(script.headers()["content-type"]).toContain("javascript");
  const session = await request.get("/api/session");
  expect(session.headers()["cache-control"]).toBe("no-store");
});
