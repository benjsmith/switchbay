/**
 * Plot tab sections, in-tab search, Library thumbnails, and figure docs.
 *
 * E2E_MOCK=1. The mock serves frontend/dist plus a real plot gallery on
 * a throwaway workspace. It does not start switchbay.daemon and does not
 * read the live vault. e2e_mock health flag is required.
 */
import { test, expect, type Page } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const shotDir = "test-results/shots";
const PORT = process.env.E2E_PLOTS_PORT || "41768";
const BASE = process.env.E2E_BASE_URL || `http://127.0.0.1:${PORT}`;

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, "../../..");
const dist = path.join(repo, "frontend/dist");

let mockProc: ChildProcess | null = null;
let startedHere = false;

async function defWait(ms: number): Promise<void> {
  await new Promise((r) => setTimeout(r, ms));
}

async function waitHealth(url: string, timeoutMs = 20_000): Promise<void> {
  const t0 = Date.now();
  let last = "";
  while (Date.now() - t0 < timeoutMs) {
    try {
      const r = await fetch(`${url}/api/health`);
      if (r.ok) {
        const body = await r.json() as { e2e_mock?: boolean; gallery?: boolean };
        if (body.e2e_mock === true && body.gallery === true) return;
        last = JSON.stringify(body);
      }
    } catch (err) {
      last = (err as Error).message;
    }
    await defWait(150);
  }
  throw new Error(`plots mock did not become healthy at ${url} (${last})`);
}

test.beforeAll(async () => {
  if (!fs.existsSync(path.join(dist, "index.html"))) {
    throw new Error("frontend/dist missing — build before Playwright");
  }
  mockProc = spawn(
    "uv",
    [
      "run", "--no-sync", "python",
      path.join(here, "mock_backend.py"),
      "--host", "127.0.0.1",
      "--port", PORT,
      "--dist", dist,
    ],
    {
      cwd: repo,
      env: {
        ...process.env,
        PATH: `${process.env.HOME}/.local/bin:${process.env.PATH ?? ""}`,
        PYTHONPATH: path.join(repo, "src"),
        E2E_MOCK: "1",
        E2E_GALLERY: "1",
      },
      stdio: "pipe",
    },
  );
  startedHere = true;
  await waitHealth(BASE);
});

test.afterAll(async () => {
  if (startedHere && mockProc && mockProc.pid) {
    mockProc.kill("SIGTERM");
  }
});

async function openPlotTab(page: Page) {
  await page.setViewportSize({ width: 1440, height: 1280 });
  await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
  await page.locator(".sy-tabstrip").waitFor();
  const zen = page.locator(".sy-zen");
  if (await zen.count()) {
    const toggle = page.getByRole("button", { name: /Toggle Power/i });
    if (await toggle.count()) await toggle.first().click();
  }
  await page.getByRole("tab", { name: "Plot" }).click();
  await expect(page.locator("[data-plot-section='extracted']")).toBeVisible();
  await expect(page.locator("[data-plot-section='plots']")).toBeVisible();
}

test("generated plots are written as figure docs", async ({ page }) => {
  const missing = await page.request.get(`${BASE}/api/plot/figure?id=cohort-retention`);
  expect(missing.status()).toBe(404);

  const revenue = await page.request.get(`${BASE}/api/plot/figure?id=revenue-by-region`);
  expect(revenue.ok()).toBeTruthy();
  const revenueDoc = await revenue.json() as { markdown: string };
  expect(revenueDoc.markdown).toContain("type: figure");
  expect(revenueDoc.markdown).toContain("source: plot:revenue-by-region");
  expect(revenueDoc.markdown).toContain("Quarter");
  expect(revenueDoc.markdown).toContain("Revenue");
  expect(revenueDoc.markdown).toContain("North");
  expect(revenueDoc.markdown).toContain("Source script: `.workbench/plots/revenue-by-region.json`.");

  await openPlotTab(page);
  await expect(page.locator(".sy-plot-card-axes", { hasText: "Weeks since signup" })).toBeVisible();

  const cohort = await page.request.get(`${BASE}/api/plot/figure?id=cohort-retention`);
  expect(cohort.ok()).toBeTruthy();
  const cohortDoc = await cohort.json() as { markdown: string; path: string };
  expect(cohortDoc.path).toContain("wiki/figures/");
  expect(cohortDoc.markdown).toContain("type: figure");
  expect(cohortDoc.markdown).toContain("source: plot:cohort-retention");
  expect(cohortDoc.markdown).toContain("Weeks since signup");
  expect(cohortDoc.markdown).toContain("Share still active");
  expect(cohortDoc.markdown).toContain("Jan");
});

test("plot tab sections and search filter both lists locally", async ({ page }) => {
  fs.mkdirSync(shotDir, { recursive: true });
  await openPlotTab(page);
  const extracted = page.locator("[data-plot-section='extracted']");
  const plots = page.locator("[data-plot-section='plots']");
  await expect(extracted.locator(".sy-plot-card-title", { hasText: "Glucose curve" })).toBeVisible();
  await expect(extracted.locator(".sy-plot-card-title", { hasText: "Site plan" })).toBeVisible();
  await expect(plots.locator(".sy-plot-card-title", { hasText: "Revenue by region" })).toBeVisible();
  await expect(plots.locator(".sy-plot-card-title", { hasText: "Cohort retention" })).toBeVisible();
  await expect(extracted.locator(".sy-plot-section-count")).toHaveText("2");
  await expect(plots.locator(".sy-plot-section-count")).toHaveText("2");
  await expect(page.locator(".sy-vega-counter")).toHaveText("4");
  await expect(extracted.locator("[data-figure-id='glucose']")).toContainText("Time · Concentration");
  await expect(extracted.locator("[data-figure-id='glucose']")).toContainText("Plasma glucose after the meal.");
  await expect(extracted.locator("[data-figure-id='site-plan']")).toContainText("East-west · North-south");
  await expect(extracted.locator("[data-figure-id='site-plan']")).toContainText("Camera positions on the floor.");
  await expect(extracted.locator("[data-figure-id='site-plan']")).not.toContainText("Concentration");

  const figure = extracted.locator("img").first();
  await expect.poll(
    () => figure.evaluate((el: HTMLImageElement) => el.naturalWidth),
  ).toBeGreaterThan(400);

  await page.screenshot({ path: path.join(shotDir, "plots-both-sections.png") });

  const searchCalls: string[] = [];
  page.on("request", (req) => {
    const url = req.url();
    if (url.includes("/api/library/search")) searchCalls.push(url);
    if (url.includes("/api/plots") && url.includes("q=")) searchCalls.push(url);
  });
  await page.getByRole("searchbox", { name: "Search plots" }).fill("glucose");
  await expect(extracted.locator(".sy-plot-card-title", { hasText: "Glucose curve" })).toBeVisible();
  await expect(extracted.locator(".sy-plot-card-title", { hasText: "Site plan" })).toHaveCount(0);
  await expect(plots.locator(".sy-plot-card-title", { hasText: "Revenue by region" })).toHaveCount(0);
  await expect(plots.locator(".sy-plot-card-title", { hasText: "Cohort retention" })).toHaveCount(0);
  await expect(extracted.locator(".sy-plot-section-count")).toHaveText("1 of 2");
  await expect(plots.locator(".sy-plot-section-count")).toHaveText("0 of 2");
  await expect(page.locator(".sy-vega-counter")).toHaveText("1 of 4");
  await expect(extracted.locator("mark.sy-plot-hit").first()).toBeVisible();
  expect(searchCalls).toEqual([]);

  await page.getByRole("searchbox", { name: "Search plots" }).fill("Weeks since signup");
  await expect(plots.locator(".sy-plot-card-title", { hasText: "Cohort retention" })).toBeVisible();
  await expect(extracted.locator(".sy-plot-card-title", { hasText: "Glucose curve" })).toHaveCount(0);
  await expect(plots.locator(".sy-plot-section-count")).toHaveText("1 of 2");
  await expect(extracted.locator(".sy-plot-section-count")).toHaveText("0 of 2");
  await expect(page.locator(".sy-vega-counter")).toHaveText("1 of 4");
  expect(searchCalls).toEqual([]);

  await page.screenshot({ path: path.join(shotDir, "plots-search.png") });
});

test("library lists generated plots with small thumbnails", async ({ page }) => {
  fs.mkdirSync(shotDir, { recursive: true });
  await openPlotTab(page);
  await page.getByRole("tab", { name: "Library" }).click();
  const cards = page.locator(".sy-lib-card[data-kind='plot']");
  await expect(cards).toHaveCount(2);
  await expect(page.getByText("Glucose curve")).toHaveCount(0);
  await expect(page.getByText("Site plan")).toHaveCount(0);
  await expect(page.getByText("Revenue by region")).toBeVisible();
  await expect(page.getByText("Cohort retention")).toBeVisible();

  const img = cards.first().locator("img");
  await expect(img).toHaveAttribute("src", /\/thumb$/);
  await expect.poll(
    () => img.evaluate((el: HTMLImageElement) => el.naturalWidth),
  ).toBeLessThanOrEqual(176);
  await expect.poll(
    () => img.evaluate((el: HTMLImageElement) => el.naturalWidth),
  ).toBeGreaterThan(20);

  async function assertThumbAboveTitle() {
    const count = await cards.count();
    expect(count).toBeGreaterThan(0);
    for (let i = 0; i < count; i++) {
      const card = cards.nth(i);
      const boxes = await card.evaluate((el) => {
        const image = el.querySelector("img");
        const title = el.querySelector(".sy-lib-card-title");
        if (!(image instanceof HTMLElement) || !(title instanceof HTMLElement)) return null;
        const a = image.getBoundingClientRect();
        const b = title.getBoundingClientRect();
        return {
          ax: a.x, ay: a.y, aw: a.width, ah: a.height,
          bx: b.x, by: b.y, bw: b.width, bh: b.height,
        };
      });
      expect(boxes, "plot card is missing a thumbnail or title").not.toBeNull();
      const box = boxes!;
      const intersects = box.ax < box.bx + box.bw
        && box.ax + box.aw > box.bx
        && box.ay < box.by + box.bh
        && box.ay + box.ah > box.by;
      expect(intersects, `thumbnail overlaps the title at ${page.viewportSize()?.width}px`).toBe(false);
      expect(box.ay + box.ah).toBeLessThanOrEqual(box.by + 0.5);
    }
  }

  for (const width of [1440, 900, 480]) {
    await page.setViewportSize({ width, height: 900 });
    await assertThumbAboveTitle();
  }
  await page.setViewportSize({ width: 1440, height: 1280 });
  await assertThumbAboveTitle();

  await page.screenshot({ path: path.join(shotDir, "library-plots.png") });
});
