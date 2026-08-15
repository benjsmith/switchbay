import { expect, test, type Page } from "@playwright/test";

test.use({
  baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://localhost:5173",
});

async function switchViewer(page: Page, mode: "atlas" | "classic"): Promise<void> {
  const btn = page.locator("#viewer-mode");
  await expect(btn).toBeVisible({ timeout: 30_000 });
  const modal = page.locator("#modal[aria-hidden='false']");
  if (await modal.isVisible().catch(() => false)) {
    await page.keyboard.press("Escape");
    await expect(modal).toBeHidden({ timeout: 5_000 });
  }
  const state = page.locator("#viewer-mode-state");
  for (let i = 0; i < 2; i++) {
    if (((await state.textContent()) || "").trim() === mode) return;
    await btn.click();
    await page.locator(mode === "atlas" ? ".atlas-minimap:not(.classic-minimap)" : ".classic-minimap")
      .waitFor({ timeout: 20_000 });
  }
}

async function enterZen(page: Page): Promise<void> {
  if (await page.locator(".sy-zen").isVisible().catch(() => false)) return;
  await page.getByRole("button", { name: "Toggle Power / Zen mode" }).click();
  await expect(page.locator(".sy-zen")).toBeVisible();
}

async function clickAtlasNode(page: Page): Promise<void> {
  const canvas = page.locator("#graph > canvas:not(.atlas-minimap)");
  await expect(canvas).toBeVisible();
  const box = (await canvas.boundingBox())!;
  // Focus sits at the centre; probe nearby if the first click misses.
  const spots = [
    [0, 0], [0.08, 0], [-0.08, 0], [0, 0.08], [0, -0.08],
    [0.12, 0.08], [-0.12, -0.08],
  ];
  for (const [dx, dy] of spots) {
    const x = box.x + box.width * (0.5 + dx);
    const y = box.y + box.height * (0.5 + dy);
    await page.mouse.move(x, y);
    await page.mouse.click(x, y);
    if (await page.locator(".sy-editor-path").isVisible({ timeout: 1500 }).catch(() => false)) {
      return;
    }
  }
  throw new Error("atlas click did not open a page in the Editor");
}

test("atlas node click in zen opens the Editor", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("/");
  await page.locator(".sy-graph-host, .sy-zen").first().waitFor({ timeout: 20_000 });
  await switchViewer(page, "atlas");
  await enterZen(page);
  await clickAtlasNode(page);
  await expect(page.locator(".sy-editor-path")).toBeVisible();
  await expect(page.locator(".sy-zen-surf-pickbtn")).toContainText("Editor");
});
