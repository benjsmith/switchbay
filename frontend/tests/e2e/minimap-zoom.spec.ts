import { expect, test, type Locator, type Page } from "@playwright/test";

test.use({
  baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://localhost:5173",
});

async function graphReady(page: Page): Promise<Locator> {
  await page.locator(".sy-graph-host, .sy-zen").first().waitFor({ timeout: 20_000 });
  const map = page.locator(".atlas-minimap, .classic-minimap").first();
  await expect(map).toBeVisible({ timeout: 30_000 });
  return map;
}

async function cameraScale(map: Locator): Promise<number> {
  return map.evaluate((el) => Number((el as HTMLElement).dataset.cameraScale || "1"));
}

async function wheelOnMap(page: Page, map: Locator): Promise<void> {
  const box = (await map.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.wheel(0, -400);
  await page.waitForTimeout(80);
}

async function switchViewer(page: Page, mode: "atlas" | "classic"): Promise<void> {
  const btn = page.locator("#viewer-mode");
  await expect(btn).toBeVisible();
  const state = page.locator("#viewer-mode-state");
  for (let i = 0; i < 2; i++) {
    if (((await state.textContent()) || "").trim() === mode) return;
    await btn.click();
    await page.locator(mode === "atlas" ? ".atlas-minimap:not(.classic-minimap)" : ".classic-minimap")
      .waitFor({ timeout: 20_000 });
  }
}

test("atlas minimap wheel zooms the main view", async ({ page }) => {
  await page.goto("/");
  await graphReady(page);
  await switchViewer(page, "atlas");
  const map = page.locator(".atlas-minimap:not(.classic-minimap)");
  await expect(map).toBeVisible();
  const before = await cameraScale(map);
  await wheelOnMap(page, map);
  await expect.poll(async () => cameraScale(map)).not.toBeCloseTo(before, 4);
});

test("classic minimap wheel still zooms", async ({ page }) => {
  await page.goto("/");
  await graphReady(page);
  await switchViewer(page, "classic");
  const map = page.locator(".classic-minimap");
  await expect(map).toBeVisible();
  const before = await cameraScale(map);
  await wheelOnMap(page, map);
  await expect.poll(async () => cameraScale(map)).not.toBeCloseTo(before, 4);
});

test("zen lift follows float vs tab; atlas wheel still works", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("/");
  await graphReady(page);
  await switchViewer(page, "atlas");
  await page.getByRole("button", { name: "Toggle Power / Zen mode" }).click();
  await expect(page.locator(".sy-zen")).toBeVisible();
  const map = page.locator(".atlas-minimap:not(.classic-minimap)");
  await expect(map).toBeVisible();

  const floating = page.locator(".sy-zen-chatbox").first();
  await expect(floating).toBeVisible();
  const zen = page.locator(".sy-zen");
  const lifted = await zen.evaluate((el) => getComputedStyle(el).getPropertyValue("--sy-minimap-bottom").trim());
  expect(parseFloat(lifted || "12")).toBeGreaterThan(12);

  const mapBottom = await map.evaluate((el) => parseFloat(getComputedStyle(el).bottom));
  expect(mapBottom).toBeGreaterThan(12);

  const before = await cameraScale(map);
  await wheelOnMap(page, map);
  await expect.poll(async () => cameraScale(map)).not.toBeCloseTo(before, 4);

  await page.getByRole("button", { name: "⇲ tab" }).click();
  await expect(page.locator(".sy-zen-chatbox--docked")).toBeVisible();
  const docked = await zen.evaluate((el) => getComputedStyle(el).getPropertyValue("--sy-minimap-bottom").trim());
  expect(parseFloat(docked || "12")).toBeLessThanOrEqual(12);

  const afterDock = await cameraScale(map);
  await wheelOnMap(page, map);
  await expect.poll(async () => cameraScale(map)).not.toBeCloseTo(afterDock, 4);
});
