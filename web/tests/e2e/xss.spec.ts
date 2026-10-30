// ABOUTME: The first end to end test: hostile markup in a stored report renders as literal text only.
// ABOUTME: No dialog, no injected script or image element, no global set by a payload.
import { expect, test } from "@playwright/test";
import { IMAGE_PAYLOAD, SCRIPT_PAYLOAD, loadFixtures } from "./fixtures";

test("an XSS payload in a stored report appears as text and runs nothing", async ({ page }) => {
  const dialogs: string[] = [];
  page.on("dialog", (dialog) => {
    dialogs.push(dialog.message());
    void dialog.dismiss();
  });
  await page.goto(`/#/report/${loadFixtures().hostile}`);

  await expect(page.getByText(SCRIPT_PAYLOAD).first()).toBeVisible();
  await expect(page.getByText(IMAGE_PAYLOAD).first()).toBeVisible();
  await page.waitForTimeout(500);

  expect(dialogs).toEqual([]);
  expect(await page.evaluate(() => (window as unknown as { __xss?: number }).__xss)).toBeUndefined();
  expect(await page.locator("#app script").count()).toBe(0);
  expect(await page.locator("#app img").count()).toBe(0);
  expect(await page.locator("#app [onerror]").count()).toBe(0);
});
