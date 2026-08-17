import { expect, test, type Page } from "@playwright/test";

test.use({
  baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://localhost:5173",
});

const MARK = "half-written zen prompt for the model picker";

async function dismissChrome(page: Page): Promise<void> {
  const modal = page.locator("#modal[aria-hidden='false']");
  if (await modal.isVisible().catch(() => false)) {
    await page.keyboard.press("Escape");
    await expect(modal).toBeHidden({ timeout: 5_000 });
  }
  const wizard = page.locator(".sy-wizard");
  if (await wizard.isVisible().catch(() => false)) {
    await page.keyboard.press("Escape");
  }
  const walk = page.locator(".sy-walkthrough, [data-tour-overlay]");
  if (await walk.first().isVisible().catch(() => false)) {
    const skip = page.getByRole("button", { name: /skip|dismiss|close/i });
    if (await skip.first().isVisible().catch(() => false)) {
      await skip.first().click();
    } else {
      await page.keyboard.press("Escape");
    }
  }
}

async function enterMode(page: Page, mode: "zen" | "power"): Promise<void> {
  const inZen = await page.locator(".sy-zen").isVisible().catch(() => false);
  if ((mode === "zen") === inZen) return;
  await page.getByRole("button", { name: "Toggle Power / Zen mode" }).click();
  if (mode === "zen") await expect(page.locator(".sy-zen")).toBeVisible();
  else await expect(page.locator(".sy-rail-input")).toBeVisible({ timeout: 10_000 });
}

async function ensureChatComposer(page: Page, which: "zen" | "power"): Promise<void> {
  const input = page.locator(which === "zen" ? ".sy-zen-input" : ".sy-rail-input");
  if (which === "zen") {
    const pill = page.locator(".sy-zen-pill");
    if (await pill.isVisible().catch(() => false)) await pill.click();
  }
  if (await input.isVisible().catch(() => false)) return;
  await page.getByRole("button", { name: "Start a new chat thread" }).click();
  await expect(input).toBeVisible({ timeout: 10_000 });
}

test("unsent composer text survives zen ↔ power", async ({ page }) => {
  await page.addInitScript(() => {
    try {
      localStorage.removeItem("sy:composer-draft");
      localStorage.setItem("sy:ui-mode", "zen");
    } catch { /* */ }
  });
  await page.goto("/");
  await page.locator(".sy-zen, .sy-tabstrip").first().waitFor({ timeout: 20_000 });
  await dismissChrome(page);
  await enterMode(page, "zen");
  await ensureChatComposer(page, "zen");

  const zen = page.locator(".sy-zen-input");
  await zen.fill(MARK);
  await expect(zen).toHaveValue(MARK);
  await expect.poll(async () =>
    page.evaluate(() => localStorage.getItem("sy:composer-draft")),
  ).toBe(MARK);

  await enterMode(page, "power");
  await ensureChatComposer(page, "power");
  const rail = page.locator(".sy-rail-input");
  await expect(rail).toHaveValue(MARK);

  await rail.fill(`${MARK} — plus a clause`);
  await enterMode(page, "zen");
  await ensureChatComposer(page, "zen");
  await expect(page.locator(".sy-zen-input")).toHaveValue(`${MARK} — plus a clause`);
});
