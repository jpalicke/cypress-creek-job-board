// ABOUTME: End to end tests of the Draft help review gate against the real API and a hand written model.
// ABOUTME: Copy stays disabled until its own bullet is ticked, and nothing is copied until it is clicked.
import { expect, test, type Page } from "@playwright/test";
import { loadFixtures } from "./fixtures";

test.use({ permissions: ["clipboard-read", "clipboard-write"] });

async function drafted(page: Page): Promise<void> {
  await page.goto(`/#/report/${loadFixtures().benign}`);
  await page.getByRole("button", { name: "Draft help" }).first().click();
  await expect(page.locator("li.bullet")).toHaveCount(2);
}

const CLEAN = "Backend Developer at Gravy Boat Labs, where I built and ran Python services.";

test("Copy is disabled on load, stays disabled for another bullet, and enables only after its own box", async ({ page }) => {
  await drafted(page);
  const bullets = page.locator("li.bullet");
  const copy = bullets.nth(0).getByRole("button", { name: "Copy" });
  const box = bullets.nth(0).getByRole("checkbox");

  await expect(copy).toBeDisabled();
  await expect(box).not.toBeChecked();
  await bullets.nth(1).getByRole("checkbox").check();
  await expect(copy).toBeDisabled();
  await box.check();
  await expect(copy).toBeEnabled();
  await box.uncheck();
  await expect(copy).toBeDisabled();
});

test("a bullet that failed a check shows its warning and cannot be copied even when ticked", async ({ page }) => {
  await drafted(page);
  const flagged = page.locator("li.bullet").nth(1);

  await expect(flagged).toContainText("Failed a check");
  await flagged.getByRole("checkbox").check();
  await expect(flagged.getByRole("button", { name: "Copy" })).toBeDisabled();
});

test("nothing reaches the clipboard until Copy is clicked", async ({ page }) => {
  await drafted(page);
  const bullet = page.locator("li.bullet").nth(0);

  await bullet.getByRole("checkbox").check();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("");
  await bullet.getByRole("button", { name: "Copy" }).click();
  await expect(bullet).toContainText("Copied");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(CLEAN);
});

test("a requirement with no support offers no draft", async ({ page }) => {
  await page.goto(`/#/report/${loadFixtures().benign}`);

  await expect(page.getByText("No verified fact supports this").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Draft help" })).toHaveCount(2);
});
