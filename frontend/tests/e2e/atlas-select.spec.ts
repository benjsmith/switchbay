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

test("atlas requests individual hybrid nodes on its first frame", async ({ page }) => {
  await page.addInitScript(() => {
    const capture = () => {
      const atlas = (window as unknown as { KnowledgeAtlas?: { mount?: Function } }).KnowledgeAtlas;
      if (!atlas?.mount || (atlas.mount as { __captured?: boolean }).__captured) return false;
      const original = atlas.mount.bind(atlas);
      const wrapped = ((container: HTMLElement, opts: unknown) => {
        (window as unknown as { __atlasMountOptions?: unknown }).__atlasMountOptions = opts;
        return original(container, opts);
      }) as typeof atlas.mount & { __captured?: boolean };
      wrapped.__captured = true;
      atlas.mount = wrapped;
      return true;
    };
    const id = window.setInterval(() => { if (capture()) window.clearInterval(id); }, 0);
  });
  await page.goto("/?viewer=atlas");
  await expect(page.locator(".atlas-minimap:not(.classic-minimap)")).toBeVisible({ timeout: 30_000 });
  const config = await page.evaluate(() => (
    (window as unknown as { __atlasMountOptions?: { config?: Record<string, unknown> } })
      .__atlasMountOptions?.config
  ));
  expect(config?.layout).toBe("hybrid");
  expect(Number(config?.coreCapacity)).toBeGreaterThan(0);
  expect((config?.budget as { maxAggregates?: number })?.maxAggregates).toBe(0);
});

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
