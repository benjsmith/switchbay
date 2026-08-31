import { expect, test, type Page } from "@playwright/test";

test.use({
  baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://localhost:5173",
});

/** Capture the mounted Atlas handle so the test can read engine state
 *  (selection = search rings) and use the engine's own hit tester to
 *  find a pixel that is provably empty. */
async function captureAtlasHandle(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const capture = () => {
      const atlas = (window as unknown as { KnowledgeAtlas?: { mount?: Function } }).KnowledgeAtlas;
      if (!atlas?.mount || (atlas.mount as { __captured?: boolean }).__captured) return false;
      const original = atlas.mount.bind(atlas);
      const wrapped = ((container: HTMLElement, opts: unknown) => {
        const handle = original(container, opts);
        (window as unknown as { __atlasHandle?: unknown }).__atlasHandle = handle;
        return handle;
      }) as typeof atlas.mount & { __captured?: boolean };
      wrapped.__captured = true;
      atlas.mount = wrapped;
      return true;
    };
    const id = window.setInterval(() => { if (capture()) window.clearInterval(id); }, 0);
  });
}

type Handle = {
  engine: {
    getState(): { selection?: string[]; pinned?: string[] };
    snapshot(): { scene?: { nodes: Array<{ role: string }>; edges: Array<{ priority?: number }> } | null };
    hitTester: { pointAt(x: number, y: number, slack?: number): { id: string; kind: string } | null };
  };
};

/** Atlas's own "current focus" decoration: an accent ring on one node
 *  plus its edges lit at priority 1. Switch Bay strips it — the wiki
 *  stays resident as one scene, so the engine never rebuilds on focus
 *  and the mark sat forever on an entry node nobody picked. */
const focusMarks = (page: Page) => page.evaluate(() => {
  const scene = (window as unknown as { __atlasHandle?: Handle })
    .__atlasHandle?.engine.snapshot().scene;
  if (!scene) return -1;
  return scene.nodes.filter((n) => n.role === "focus").length
    + scene.edges.filter((e) => e.priority === 1).length;
});

/** The dashed halo the renderer draws on search hits. */
const haloCount = (page: Page) => page.evaluate(() => (
  (window as unknown as { __atlasHandle?: Handle }).__atlasHandle
    ?.engine.getState().pinned?.length ?? -1
));

/** Solid accent rings. Search must not add these — they competed with
 *  the halo and read as a second highlight on the same nodes. */
const selectionSize = (page: Page) => page.evaluate(() => (
  (window as unknown as { __atlasHandle?: Handle }).__atlasHandle
    ?.engine.getState().selection?.length ?? -1
));

/** Scan the canvas for a point the engine reports as empty (`want:
 *  "blank"`) or as a node (`want: "node"`). */
async function probePoint(
  page: Page, want: "blank" | "node",
): Promise<{ x: number; y: number }> {
  const point = await page.evaluate((mode) => {
    const canvas = document.querySelector<HTMLCanvasElement>("#graph > canvas:not(.atlas-minimap)");
    const handle = (window as unknown as { __atlasHandle?: Handle }).__atlasHandle;
    if (!canvas || !handle) return null;
    const rect = canvas.getBoundingClientRect();
    for (let fy = 0.1; fy < 0.95; fy += 0.02) {
      for (let fx = 0.1; fx < 0.95; fx += 0.02) {
        const cx = rect.left + rect.width * fx;
        const cy = rect.top + rect.height * fy;
        const hit = handle.engine.hitTester.pointAt(
          cx - rect.left - rect.width / 2,
          cy - rect.top - rect.height / 2,
          6,
        );
        const ok = mode === "node" ? hit?.kind === "node" : hit === null;
        // A blank point must have clear air around it too, so a stray
        // pixel between two nodes can't make the test flaky.
        if (!ok) continue;
        if (mode === "blank") {
          const wide = handle.engine.hitTester.pointAt(
            cx - rect.left - rect.width / 2,
            cy - rect.top - rect.height / 2,
            24,
          );
          if (wide) continue;
        }
        return { x: cx, y: cy };
      }
    }
    return null;
  }, want);
  if (!point) throw new Error(`no ${want} point found on the atlas canvas`);
  return point;
}

test("atlas search rings clear when the search is cancelled", async ({ page }) => {
  await captureAtlasHandle(page);
  await page.goto("/?viewer=atlas");
  await expect(page.locator(".atlas-minimap:not(.classic-minimap)")).toBeVisible({ timeout: 30_000 });

  await page.locator("#graph-search-input").fill("attention");
  await expect(page.locator("#graph-search-count")).not.toHaveText("0");
  await expect.poll(() => haloCount(page)).toBeGreaterThan(0);
  await expect.poll(() => selectionSize(page)).toBe(0);
  await expect(page.locator("#graph")).not.toHaveAttribute("data-search-hits", "0");

  await page.locator("#graph-search-clear").click();
  // pin()/unpin() would ask for a scene rebuild each; a rebuild landing
  // after the clear repainted the stale halos and left them stuck on.
  await expect.poll(() => haloCount(page)).toBe(0);
  await expect(page.locator("#graph")).toHaveAttribute("data-search-hits", "0");
});

test("atlas carries no focus ring — before, during or after a search", async ({ page }) => {
  await captureAtlasHandle(page);
  await page.goto("/?viewer=atlas");
  await expect(page.locator(".atlas-minimap:not(.classic-minimap)")).toBeVisible({ timeout: 30_000 });

  await expect.poll(() => focusMarks(page)).toBe(0);

  await page.locator("#graph-search-input").fill("attention");
  await expect.poll(() => haloCount(page)).toBeGreaterThan(0);
  await expect.poll(() => focusMarks(page)).toBe(0);
  await page.locator("#graph-search-clear").click();

  // Opening a page focuses the engine; the mark must not reappear when
  // a scene rebuild lands afterwards.
  await page.locator(".sidebar-row").nth(4).click();
  await page.waitForTimeout(1_000);
  await page.keyboard.press("Escape");
  await expect.poll(() => focusMarks(page)).toBe(0);
});

test("atlas: clicking empty canvas opens nothing, even with a stale hover", async ({ page }) => {
  await captureAtlasHandle(page);
  await page.goto("/?viewer=atlas");
  await expect(page.locator(".atlas-minimap:not(.classic-minimap)")).toBeVisible({ timeout: 30_000 });

  const modal = page.locator("#modal[aria-hidden='false']");
  const canvas = page.locator("#graph > canvas:not(.atlas-minimap)");

  // A restored selection opens the doc modal over the canvas on load.
  if (await modal.isVisible().catch(() => false)) {
    await page.keyboard.press("Escape");
    await expect(modal).toBeHidden();
  }

  // Park the pointer on a node so the engine records a hover id.
  const node = await probePoint(page, "node");
  await page.mouse.move(node.x, node.y);
  await expect.poll(async () => canvas.getAttribute("data-hover-id")).not.toBe("");

  // Click empty canvas WITHOUT an intervening pointermove — hover only
  // updates on move, so the recorded id is still the node above. The
  // click handler used to open whatever that id was, which is how a
  // click on nothing summoned a document.
  const blank = await probePoint(page, "blank");
  await page.evaluate(({ x, y }) => {
    const el = document.querySelector<HTMLCanvasElement>("#graph > canvas:not(.atlas-minimap)");
    if (!el) throw new Error("no atlas canvas");
    for (const type of ["pointerdown", "pointerup"]) {
      el.dispatchEvent(new PointerEvent(type, {
        clientX: x, clientY: y, bubbles: true, cancelable: true, pointerId: 1,
      }));
    }
  }, blank);
  await page.waitForTimeout(500);
  await expect(modal).toBeHidden();

  // A real click on a node still opens it.
  await page.mouse.click(node.x, node.y);
  await expect(modal).toBeVisible();
});
