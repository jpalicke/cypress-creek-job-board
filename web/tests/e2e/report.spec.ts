// ABOUTME: End to end tests of the Gap report screen against stored reports served by the real API.
// ABOUTME: The score always has its disclaimer, an incomplete report has a banner and no score.
import { expect, test } from "@playwright/test";
import { loadFixtures } from "./fixtures";

test("a complete report shows its requirements by support and the score with the disclaimer", async ({ page }) => {
  await page.goto(`/#/report/${loadFixtures().benign}`);

  const score = page.getByTestId("score");
  await expect(score).toContainText("58.3 out of 100");
  await expect(score).toContainText("triage only, not a probability");
  await expect(page.getByRole("heading", { name: "Strong support (1)" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Partial support (1)" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "No support (1)" })).toBeVisible();
  await expect(page.getByText("F-0001 shows Python work.")).toBeVisible();
  await expect(page.getByText("Facts: F-0001").first()).toBeVisible();
  await expect(page.getByText("no verified fact cited")).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("an incomplete report shows the banner and no score", async ({ page }) => {
  await page.goto(`/#/report/${loadFixtures().incomplete}`);

  const banner = page.getByRole("alert");
  await expect(banner).toContainText("Incomplete");
  await expect(banner).toContainText("extraction failed: provider_unavailable");
  await expect(page.getByTestId("score")).toHaveCount(0);
  await expect(page.getByText("out of 100")).toHaveCount(0);
});

test("a report that does not exist shows a typed error", async ({ page }) => {
  await page.goto("/#/report/rep-does-not-exist");
  await expect(page.getByRole("alert")).toContainText("not_found");
});
