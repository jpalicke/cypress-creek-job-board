// ABOUTME: End to end tests of the fact bank screen against the real API and a throwaway bank file.
// ABOUTME: A fact is verified only by its own button, edits unverify it, and hostile text stays text.
import { expect, test, type Locator, type Page } from "@playwright/test";

async function addFact(page: Page, claim: string, extra: Record<string, string> = {}): Promise<Locator> {
  await page.goto("/#/facts");
  await page.getByRole("button", { name: "Add a fact" }).click();
  await page.getByLabel("What is true").fill(claim);
  await page.getByLabel("Where it can be checked").fill("my notes");
  for (const [label, value] of Object.entries(extra)) await page.getByLabel(label, { exact: true }).fill(value);
  await page.getByRole("button", { name: "Save fact" }).click();
  const row = page.locator("li.fact", { hasText: claim });
  await expect(row).toBeVisible();
  return row;
}

test("a new fact loads unverified and local only, and is verified only by its own button", async ({ page }) => {
  const first = await addFact(page, "First claim for the verify test.");
  const second = await addFact(page, "Second claim for the verify test.");

  await expect(first).toContainText("Unverified");
  await expect(first).toContainText("Local only");
  await first.getByRole("button", { name: "Verify this fact" }).click();
  await expect(first).toContainText("Verified on");
  await expect(second).toContainText("Unverified");
  await page.reload();
  await expect(page.locator("li.fact", { hasText: "First claim for the verify test." })).toContainText("Verified on");
});

test("editing a verified fact's claim shows it unverified again", async ({ page }) => {
  const row = await addFact(page, "A claim to edit later.");
  await row.getByRole("button", { name: "Verify this fact" }).click();
  await expect(row).toContainText("Verified on");

  await row.getByRole("button", { name: "Edit" }).click();
  await expect(page.getByText("it becomes unverified")).toBeVisible();
  await page.getByLabel("What is true").fill("An edited claim.");
  await page.getByRole("button", { name: "Save fact" }).click();

  const edited = page.locator("li.fact", { hasText: "An edited claim." });
  await expect(edited).toContainText("Unverified");
});

test("script and onerror payloads render as literal text and run nothing", async ({ page }) => {
  const dialogs: string[] = [];
  page.on("dialog", (dialog) => {
    dialogs.push(dialog.message());
    void dialog.dismiss();
  });
  const payload = '<script>window.__xss = 1; alert(1)</script><img src=x onerror="window.__xss = 2; alert(2)">';
  const row = await addFact(page, payload);

  await expect(row).toContainText(payload);
  expect(await page.locator("main script, main img").count()).toBe(0);
  expect(await page.evaluate(() => (window as unknown as { __xss?: number }).__xss)).toBeUndefined();
  expect(dialogs).toEqual([]);
});

test("a local only fact says no model sees it, and an invalid fact shows its error and saves nothing", async ({ page }) => {
  const row = await addFact(page, "A private claim.");
  await expect(row).toContainText("never shown to a model");
  const before = await page.locator("li.fact").count();

  await page.getByRole("button", { name: "Add a fact" }).click();
  await page.getByLabel("What is true").fill("A claim with a future start.");
  await page.getByLabel("Where it can be checked").fill("notes");
  await page.getByLabel("Start").fill("2999-01-01");
  await page.getByRole("button", { name: "Save fact" }).click();

  await expect(page.locator("[data-field-error=start]")).toContainText("future");
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.locator("li.fact")).toHaveCount(before);
});

test("delete needs a confirmation", async ({ page }) => {
  const row = await addFact(page, "A claim to delete.");

  await row.getByRole("button", { name: "Delete" }).click();
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Cancel" }).click();
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Delete" }).click();
  await row.getByRole("button", { name: /Confirm delete/ }).click();
  await expect(row).toHaveCount(0);
});

test("adding and verifying a fact works with the keyboard alone", async ({ page }) => {
  await page.goto("/#/facts");
  await page.getByRole("button", { name: "Add a fact" }).focus();
  await page.keyboard.press("Enter");
  await page.getByLabel("What is true").focus();
  await page.keyboard.type("A keyboard only claim.");
  for (let step = 0; step < 9; step += 1) await page.keyboard.press("Tab");
  await page.keyboard.type("keyboard notes");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Enter");

  const row = page.locator("li.fact", { hasText: "A keyboard only claim." });
  await expect(row).toContainText("Unverified");
  await row.getByRole("button", { name: "Verify this fact" }).focus();
  await page.keyboard.press("Enter");
  await expect(row).toContainText("Verified on");
});
