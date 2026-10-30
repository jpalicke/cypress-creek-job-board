// ABOUTME: End to end tests of the resume import screen against the real API and a hand written model.
// ABOUTME: Nothing is sent early, each candidate is decided alone, and hostile text stays literal.
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";

const PDFS = resolve(import.meta.dirname, "..", "..", "..", "evals", "fixtures", "pdf");

async function importText(page: Page, text: string): Promise<void> {
  await page.goto("/#/import");
  await page.getByLabel("Resume text").fill(text);
  await page.getByRole("button", { name: "Find facts in this resume" }).click();
}

async function factCount(page: Page): Promise<number> {
  await page.goto("/#/facts");
  await expect(page.getByRole("button", { name: "Add a fact" })).toBeVisible();
  return page.locator("li.fact").count();
}

test("nothing is sent until the button is pressed, then candidates show with their source", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST") requests.push(request.url());
  });
  await page.goto("/#/import");
  await page.getByLabel("Resume text").fill("Wrote the first parser for Pine Valley.");
  await page.waitForTimeout(200);
  expect(requests).toEqual([]);

  await page.getByRole("button", { name: "Find facts in this resume" }).click();

  const row = page.locator("li.candidate", { hasText: "Wrote the first parser for Pine Valley." });
  await expect(row).toContainText("From the resume: Wrote the first parser for Pine Valley.");
  await expect(page.getByTestId("dropped")).toContainText("source_not_in_resume (1)");
  await expect(page.getByRole("button", { name: /approve all/i })).toHaveCount(0);
});

test("approving one candidate adds exactly one unverified, local only fact", async ({ page }) => {
  const before = await factCount(page);
  await importText(page, "Built the nightly export for Gravy Boat.");
  const row = page.locator("li.candidate", { hasText: "Built the nightly export for Gravy Boat." });
  await row.getByRole("button", { name: "Approve this fact" }).click();
  await expect(row).toContainText("unverified and local only");

  await page.goto("/#/facts");
  const fact = page.locator("li.fact", { hasText: "Built the nightly export for Gravy Boat." });
  await expect(fact).toContainText("Unverified");
  await expect(fact).toContainText("Local only");
  await expect(page.locator("li.fact")).toHaveCount(before + 1);
});

test("rejecting adds nothing to the bank", async ({ page }) => {
  const before = await factCount(page);
  await importText(page, "Reviewed pull requests for Turbo Tortoise.");
  const row = page.locator("li.candidate", { hasText: "Reviewed pull requests for Turbo Tortoise." });
  await row.getByRole("button", { name: "Reject" }).click();
  await expect(row).toContainText("Rejected");

  expect(await factCount(page)).toBe(before);
});

test("hostile text in the resume renders as literal text and runs nothing", async ({ page }) => {
  const dialogs: string[] = [];
  page.on("dialog", (dialog) => {
    dialogs.push(dialog.message());
    void dialog.dismiss();
  });
  const payload = '<img src=x onerror="window.__xss = 1"> and <script>window.__xss = 2</script>';
  await importText(page, payload);

  await expect(page.locator("li.candidate", { hasText: payload }).first()).toBeVisible();
  expect(await page.locator("main img, main script").count()).toBe(0);
  expect(await page.evaluate(() => (window as unknown as { __xss?: number }).__xss)).toBeUndefined();
  expect(dialogs).toEqual([]);
});

test("a PDF with hidden text shows what the extractor removed", async ({ page }) => {
  await page.goto("/#/import");
  await page.getByLabel("PDF").check();
  await page.getByLabel("Resume PDF").setInputFiles(resolve(PDFS, "white_on_white.pdf"));
  await page.getByRole("button", { name: "Find facts in this resume" }).click();

  await expect(page.getByText("hidden_white_text (1)")).toBeVisible();
});

test("the import works with the keyboard alone", async ({ page }) => {
  await page.goto("/#/import");
  await page.getByLabel("Resume text").focus();
  await page.keyboard.type("Mentored two interns at Pine Valley.");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Enter");
  const row = page.locator("li.candidate", { hasText: "Mentored two interns at Pine Valley." });
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Approve this fact" }).focus();
  await page.keyboard.press("Enter");
  await expect(row).toContainText("Approved as");
});
