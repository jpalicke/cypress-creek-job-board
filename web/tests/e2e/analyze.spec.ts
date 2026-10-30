// ABOUTME: End to end tests of the Analyze flow with the backend down, and of keyboard only use.
// ABOUTME: A down backend gives an incomplete report with the banner and no score, never a crash.
import { expect, test } from "@playwright/test";
import { IMAGE_PAYLOAD, SCRIPT_PAYLOAD } from "./fixtures";

test("with the backend down the report is incomplete: banner, no score", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Posting text").fill("Needs Python.\nNeeds SQL.");
  await page.getByRole("button", { name: "Analyze" }).click();

  const banner = page.getByRole("alert");
  await expect(banner).toContainText("Incomplete");
  await expect(banner).toContainText("provider_unavailable");
  await expect(page.getByTestId("score")).toHaveCount(0);
  await expect(page.getByText("out of 100")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Link to this report" })).toBeVisible();
});

test("a pasted XSS payload shows as text in the posting preview and runs nothing", async ({ page }) => {
  const dialogs: string[] = [];
  page.on("dialog", (dialog) => {
    dialogs.push(dialog.message());
    void dialog.dismiss();
  });
  await page.goto("/");
  await page.getByLabel("Posting text").fill(`Needs ${SCRIPT_PAYLOAD} and ${IMAGE_PAYLOAD}`);
  await page.getByRole("button", { name: "Analyze" }).click();
  await page.getByText("The posting as the tool read it").click();

  const preview = page.getByTestId("posting-preview");
  await expect(preview).toContainText(SCRIPT_PAYLOAD);
  await expect(preview).toContainText(IMAGE_PAYLOAD);
  await page.waitForTimeout(500);
  expect(dialogs).toEqual([]);
  expect(await page.locator("#app script").count()).toBe(0);
  expect(await page.locator("#app img").count()).toBe(0);
});

test("the Analyze flow works with the keyboard alone", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByLabel("Backend")).toContainText("openai_compatible");

  // Tab order: the three nav links, the mode radios (one stop), the text box, the backend, the button.
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Analyze" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Fact bank" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Start from a resume" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("Paste text")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("Posting text")).toBeFocused();
  await page.keyboard.type("Needs Python.");
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("Backend")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Analyze" })).toBeFocused();
  await page.keyboard.press("Enter");

  await expect(page.getByRole("alert")).toContainText("Incomplete");
});

test("nothing is sent until the button is pressed", async ({ page }) => {
  const writes: string[] = [];
  page.on("request", (request) => {
    if (request.method() !== "GET") writes.push(`${request.method()} ${request.url()}`);
  });
  await page.goto("/");
  await page.getByLabel("Posting text").fill("Needs Python.");
  await page.waitForTimeout(300);
  expect(writes).toEqual([]);
});

test("a blank posting shows the API's typed error and keeps the form usable", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Posting text").fill("   ");
  await page.getByRole("button", { name: "Analyze" }).click();
  await expect(page.getByRole("alert")).toContainText("empty_posting");
  await expect(page.getByRole("button", { name: "Analyze" })).toBeEnabled();
});
