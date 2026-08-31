import { expect, test, type Page } from "@playwright/test";

test.use({
  baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://localhost:5173",
});

async function graphReady(page: Page): Promise<void> {
  await page.locator(".sy-graph-host, .sy-zen").first().waitFor({ timeout: 20_000 });
  await page.locator("#graph-search-input").waitFor({ timeout: 20_000 });
}

test("graph search highlights nodes, pages and files; X clears", async ({ page }) => {
  await page.goto("/");
  await page.locator(".sy-tabstrip, .sy-zen").first().waitFor({ timeout: 20_000 });
  await page.getByRole("tab", { name: "Graph" }).click();
  await graphReady(page);

  const input = page.locator("#graph-search-input");
  await expect(input).toBeVisible();
  await expect(page.locator(".graph-controls")).toBeVisible();

  const controls = page.locator(".graph-controls");
  const searchBox = page.locator(".graph-search");
  const cBox = (await controls.boundingBox())!;
  const sBox = (await searchBox.boundingBox())!;
  expect(sBox.y).toBeLessThan(cBox.y);

  // The camera must not jump on search — the auto-fit-to-hits zoom was
  // removed; hits are found by their ring, not by being flown to. The
  // layout keeps nudging the view while the simulation settles, so
  // compare against that drift, not for an exact match.
  const viewportTransform = async () => {
    const raw = await page.locator("#graph svg g.viewport")
      .evaluate((el) => el.getAttribute("transform") ?? "");
    const m = /translate\(([-\d.]+),\s*([-\d.]+)\)\s*scale\(([-\d.]+)\)/.exec(raw);
    return m
      ? { x: Number(m[1]), y: Number(m[2]), k: Number(m[3]) }
      : { x: 0, y: 0, k: 1 };
  };
  // Labels are the user's setting (auto/on/off + type filter), not the
  // search's to override: naming every hit at once buried the canvas in
  // overlapping text. A search may dim labels, never add them.
  const litLabels = () => page.locator(".node-label").evaluateAll((els) =>
    els.filter((el) => parseFloat(getComputedStyle(el).opacity) > 0.9).length);

  await page.waitForTimeout(1500);   // let the force layout settle
  const beforeZoom = await viewportTransform();
  const idleLabels = await litLabels();

  await input.fill("attention");
  await expect(page.locator("#graph-search-clear")).toBeVisible();
  await expect(page.locator("#graph-search-count")).not.toHaveText("0");
  await expect.poll(async () =>
    page.locator(".node.search-hit").count(),
  ).toBeGreaterThan(0);
  // Atlas-parity halo, drawn only on hits.
  await expect.poll(async () =>
    page.locator(".node.search-hit circle.search-ring").count(),
  ).toBeGreaterThan(0);
  // …and the halo is the ONLY mark: accent-striping every edge that
  // touches a hit buried the graph in green lines on a broad query.
  await expect(page.locator('.edge[data-vis="focus"], .edge[data-vis="neighbour"]'))
    .toHaveCount(0);
  expect(await litLabels()).toBeLessThanOrEqual(idleLabels);
  // Hovering a hit is how you read its name.
  const hit = (await page.locator(".node.search-hit").first().boundingBox())!;
  await page.mouse.move(hit.x + hit.width / 2, hit.y + hit.height / 2);
  await expect.poll(litLabels).toBeGreaterThan(0);
  await page.mouse.move(hit.x, hit.y + 260);

  await page.waitForTimeout(600);   // an auto-fit transition would have landed
  const afterZoom = await viewportTransform();
  expect(Math.abs(afterZoom.k - beforeZoom.k)).toBeLessThan(0.05);
  expect(Math.hypot(afterZoom.x - beforeZoom.x, afterZoom.y - beforeZoom.y)).toBeLessThan(60);

  // Both browsers mark the same hits: wiki page list and file tree.
  await expect.poll(async () =>
    page.locator('.sidebar-row[data-search-hit="true"]').count(),
  ).toBeGreaterThan(0);
  // Matched pages are revealed in the file tree (their dirs auto-expand).
  const fileHit = page.locator('.sy-fb-row--search-hit[data-fb-path^="wiki/"]').first();
  await expect(fileHit).toBeVisible();

  await fileHit.click();
  await page.getByRole("tab", { name: "Graph" }).click();
  await graphReady(page);
  await expect(page.locator("#graph-search-input")).toHaveValue("attention");
  await expect(page.locator("#graph-search-clear")).toBeVisible();
  await expect(page.locator("#graph-search-count")).not.toHaveText("0");
  await expect.poll(async () =>
    page.locator(".sy-fb-row--search-hit").count(),
  ).toBeGreaterThan(0);

  await page.locator("#graph-search-clear").click();
  await expect(page.locator("#graph-search-clear")).toBeHidden();
  await expect(page.locator(".sy-fb-row--search-hit")).toHaveCount(0);
  await expect(page.locator('.sidebar-row[data-search-hit="true"]')).toHaveCount(0);
  await expect(page.locator(".node.search-hit")).toHaveCount(0);
  await expect(input).toHaveValue("");
});
