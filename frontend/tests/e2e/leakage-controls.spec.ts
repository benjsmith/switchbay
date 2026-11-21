/**
 * Classification badge, exclusion rules, public-write dialog, and
 * Review labels. E2E_MOCK=1. The mock does not start the live daemon.
 */
import { test, expect, type Page } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const shotDir = "test-results/shots";
const MOCK_WS = "/tmp/switchbay-e2e-mock-ws";
const PORT = process.env.E2E_LEAK_PORT || "41768";
const BASE = process.env.E2E_BASE_URL || `http://127.0.0.1:${PORT}`;
const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, "../../..");
const dist = path.join(repo, "frontend/dist");

let mockProc: ChildProcess | null = null;
let startedHere = false;

async function defWait(ms: number): Promise<void> {
  await new Promise((r) => setTimeout(r, ms));
}

async function waitHealth(url: string): Promise<void> {
  const t0 = Date.now();
  while (Date.now() - t0 < 20_000) {
    try {
      const r = await fetch(`${url}/api/health`);
      if (r.ok) {
        const body = await r.json();
        if (body.e2e_mock === true && body.workspace === MOCK_WS) return;
      }
    } catch { /* not up */ }
    await defWait(150);
  }
  throw new Error(`mock backend did not become healthy at ${url}`);
}

test.beforeAll(async () => {
  if (!fs.existsSync(path.join(dist, "index.html"))) {
    throw new Error("frontend/dist missing — build before Playwright");
  }
  mockProc = spawn(
    "uv",
    ["run", "--no-sync", "python", path.join(here, "mock_backend.py"),
      "--host", "127.0.0.1", "--port", PORT, "--dist", dist],
    { cwd: repo, env: { ...process.env, PYTHONPATH: path.join(repo, "src") }, stdio: "pipe" },
  );
  startedHere = true;
  await waitHealth(BASE);
});

test.afterAll(async () => {
  if (startedHere && mockProc && mockProc.pid) mockProc.kill("SIGTERM");
});

test.use({ baseURL: BASE, viewport: { width: 1400, height: 900 } });
test.setTimeout(60_000);

async function openApp(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("sy:ui-mode", "power");
  });
  const resp = await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
  if (!resp || !resp.ok()) throw new Error(`GET / failed: ${resp?.status()}`);
  await page.locator(".sy-shell").waitFor({ timeout: 15_000 });
  await page.locator(".sy-rail-head").waitFor({ timeout: 10_000 });
}

test("chat badge shows the session label", async ({ page }) => {
  await page.request.post(`${BASE}/api/e2e/seed`, { data: { session_label: "confidential" } });
  await openApp(page);
  const badge = page.locator(".sy-class-badge[data-label='confidential']");
  await expect(badge).toBeVisible();
  await expect(badge).toHaveText("confidential");
  fs.mkdirSync(shotDir, { recursive: true });
  await page.locator(".sy-rail-head").screenshot({ path: `${shotDir}/session-badge.png` });
});

test("settings stores an exclusion rule", async ({ page }) => {
  await openApp(page);
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("sy:open-settings")));
  const modal = page.locator(".sy-settings").first();
  await expect(modal).toBeVisible();
  const panel = modal.locator("[data-testid='exclusion-rules']");
  await panel.scrollIntoViewIfNeeded();
  await panel.getByLabel("Exclusion rule").fill("export the customer list");
  await panel.getByLabel("Rule decision").selectOption("deny");
  await panel.getByRole("button", { name: "Add" }).click();
  await expect(panel.getByText("export the customer list")).toBeVisible();
  await expect(panel.locator(".sy-class-badge[data-label='deny']")).toBeVisible();
  await panel.screenshot({ path: `${shotDir}/exclusion-rules.png` });
});

test("public write dialog remembers a global allow", async ({ page }) => {
  await openApp(page);
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("sy:public-write", { detail: { mount: "pub" } })));
  const dialog = page.locator("[data-testid='public-write-dialog']");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("button", { name: "OK" })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Cancel" })).toBeVisible();
  await dialog.screenshot({ path: `${shotDir}/public-write-dialog.png` });
  await dialog.getByRole("button", { name: "Always allow" }).click();
  await expect(dialog).toHaveCount(0);
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("sy:open-settings")));
  const setting = page.locator("[data-testid='presidio-setting']");
  await setting.scrollIntoViewIfNeeded();
  await expect(setting.locator(".sy-class-badge[data-label='global']")).toBeVisible();
  await setting.getByRole("button", { name: "This workspace only" }).click();
  await expect(setting.locator(".sy-class-badge[data-label='workspace']")).toBeVisible();
  await setting.screenshot({ path: `${shotDir}/presidio-scope.png` });
});

test("review tab sets a classification", async ({ page }) => {
  await page.request.post(`${BASE}/api/e2e/seed`, {
    data: {
      show_reviews: true,
      class_items: [{ id: "cap-1", title: "Quick entity", kind: "capture", source: "aws-quick:quick" }],
    },
  });
  await openApp(page);
  await page.getByRole("tab", { name: "Reviews" }).click();
  const review = page.locator("[data-testid='classification-review']");
  await expect(review).toBeVisible();
  await expect(review.getByText("Quick entity")).toBeVisible();
  await review.screenshot({ path: `${shotDir}/review-classification.png` });
  await review.getByLabel("Label for Quick entity").selectOption("internal");
  await review.getByRole("button", { name: "Set label" }).click();
  await expect(review).toHaveCount(0);
});
