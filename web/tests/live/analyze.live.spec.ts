// ABOUTME: Model backed UI test: analyze a posting with a real Ollama and read the report on screen.
// ABOUTME: The XSS payload goes through the real extraction; it must still appear only as text.
import { expect, test } from "@playwright/test";

const SCRIPT = "<script>window.__xss = 1; alert(1)</script>";

test("a real analysis of a hostile posting ends in a report with only text on screen", async ({ page }) => {
  const dialogs: string[] = [];
  page.on("dialog", (dialog) => {
    dialogs.push(dialog.message());
    void dialog.dismiss();
  });
  const health = await page.request.get("/api/health");
  const backends = ((await health.json()) as { backends: { reachable: string }[] }).backends;
  expect(backends[0]?.reachable, "Ollama must be running (ollama serve) with the model pulled").toBe(
    "reachable",
  );

  await page.goto("/");
  await page
    .getByLabel("Posting text")
    .fill(`Requirements:\n- 3 years of Python experience.\n- Knowledge of ${SCRIPT} is required.\n`);
  await page.getByRole("button", { name: "Analyze" }).click();

  await expect(page.getByRole("heading", { name: "Gap report" })).toBeVisible({ timeout: 200_000 });
  const banner = page.getByRole("alert");
  if ((await banner.count()) === 0) {
    await expect(page.getByTestId("score")).toContainText("triage only, not a probability");
  } else {
    await expect(banner).toContainText("Incomplete");
    await expect(page.getByTestId("score")).toHaveCount(0);
  }
  await page.waitForTimeout(500);
  expect(dialogs).toEqual([]);
  expect(await page.locator("#app script").count()).toBe(0);
  expect(await page.evaluate(() => (window as unknown as { __xss?: number }).__xss)).toBeUndefined();
});
