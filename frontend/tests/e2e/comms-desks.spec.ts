/**
 * Comms tab + live-cap setting against the isolated mock backend.
 * E2E_MOCK=1. Unique port. Does not touch :8765 or real vaults.
 */
import { test, expect, type Page } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const shotDir = "test-results/shots";
const PORT = process.env.E2E_COMMS_PORT || "41766";
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
  while (Date.now() - t0 < timeoutMs) {
    try {
      const r = await fetch(`${url}/api/health`);
      if (r.ok) {
        const body = await r.json() as { e2e_mock?: boolean; workspace?: string };
        if (body.e2e_mock === true && body.workspace === "/tmp/switchbay-e2e-mock-ws") return;
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
    {
      cwd: repo,
      env: { ...process.env, PYTHONPATH: path.join(repo, "src"), E2E_MOCK: "1" },
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

async function openPower(page: Page) {
  await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(400);
  const zen = page.locator(".sy-zen");
  if (await zen.count()) {
    const toggle = page.getByRole("button", { name: /power/i }).or(page.locator("[title*='Power']"));
    if (await toggle.count()) await toggle.first().click();
  }
}

test("Comms tab approve and revoke in Power", async ({ page }) => {
  fs.mkdirSync(shotDir, { recursive: true });
  await openPower(page);
  const commsTab = page.getByRole("button", { name: /Comms/i }).or(page.locator("[data-kind='comms']")).or(page.getByText("Comms"));
  await commsTab.first().click();
  await expect(page.getByText("Fixture thread")).toBeVisible({ timeout: 8000 });
  await page.getByRole("button", { name: /Approve for workspace/i }).click();
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(shotDir, "comms-power-approve.png") });
  await page.getByRole("button", { name: /^Revoke$/i }).click();
  await page.waitForTimeout(300);
});

test("live cap control is in Settings", async ({ page }) => {
  await openPower(page);
  const settings = page.getByRole("button", { name: /settings/i }).or(page.locator("[title*='Settings']"));
  await settings.first().click();
  await expect(page.getByText(/Live workers per desk/i)).toBeVisible({ timeout: 8000 });
  const input = page.locator("#sy-desk-live-cap");
  await expect(input).toBeVisible();
  await input.fill("6");
  await page.waitForTimeout(200);
  const r = await page.request.get(BASE + "/api/settings");
  const body = await r.json() as { desk_max_live_workers?: number };
  expect(body.desk_max_live_workers).toBe(6);
});

test("Comms is in Zen surface list", async ({ page }) => {
  await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(400);
  const zenToggle = page.getByRole("button", { name: /Toggle Power \/ Zen mode/i });
  if (await zenToggle.count()) await zenToggle.click();
  await page.waitForTimeout(400);
  const picker = page.getByRole("button", { name: /Wiki/i }).or(page.locator(".sy-zen-surface-btn"));
  await picker.first().click();
  await expect(page.getByRole("button", { name: /^Comms$/i }).or(page.getByText("Comms"))).toBeVisible({ timeout: 5000 });
  await page.getByText("Comms").first().click();
  await expect(page.getByText("Fixture thread")).toBeVisible({ timeout: 8000 });
});

test("Comms shows suggestions and stays workspace-bound", async ({ page }) => {
  fs.mkdirSync(shotDir, { recursive: true });
  await openPower(page);
  const commsTab = page.getByRole("button", { name: /Comms/i }).or(page.locator("[data-kind='comms']")).or(page.getByText("Comms"));
  await commsTab.first().click();
  await expect(page.getByText("Fixture thread")).toBeVisible({ timeout: 8000 });
  await expect(page.getByText(/Suggested relevance/i)).toBeVisible();
  await expect(page.getByText("Other workspace thread")).toHaveCount(0);
  await page.screenshot({ path: path.join(shotDir, "comms-suggestions.png") });

  const switcher = page.locator(".sy-ws-trigger").or(page.locator(".sy-mode-switcher"));
  await switcher.first().click();
  const other = page.getByText("switchbay-e2e-mock-ws-b").or(page.getByText("ws-b"));
  await expect(other.first()).toBeVisible({ timeout: 5000 });
  await other.first().click();
  await page.waitForTimeout(500);
  await commsTab.first().click();
  await expect(page.getByText("Other workspace thread")).toBeVisible({ timeout: 8000 });
  await expect(page.getByText("Fixture thread")).toHaveCount(0);
  await page.screenshot({ path: path.join(shotDir, "comms-workspace-b.png") });
});
