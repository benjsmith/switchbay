/**
 * Graph = Curiosity Engine's viewer only, against the isolated mocked
 * backend (E2E_MOCK=1; serves frontend/dist + fake /api, /ws and a stub
 * /embed/ce). Never touches the live daemon or vault.
 *
 *  - no CE install → Graph tab hidden; the Files uploader still works.
 *  - CE present → Graph tab shown, the CE sidebar header shows the
 *    workspace name (never the raw {{WORKSPACE}} placeholder), and the
 *    sidebar `+` opens Switch Bay's upload dialog.
 */
import { test, expect, type Page } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const MOCK_WS = "/tmp/switchbay-e2e-mock-ws";
const PORT = process.env.E2E_CE_PORT || "41767";
const BASE = `http://127.0.0.1:${PORT}`;

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, "../../..");
const dist = path.join(repo, "frontend/dist");

let mockProc: ChildProcess | null = null;

async function waitHealth(url: string, timeoutMs = 20_000): Promise<void> {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try {
      const r = await fetch(`${url}/api/health`);
      if (r.ok) {
        const body = await r.json();
        if (body.e2e_mock === true && body.workspace === MOCK_WS) return;
        throw new Error("refusing non-fixture backend");
      }
    } catch (e) {
      if (String(e).includes("refusing")) throw e;
    }
    await new Promise((r) => setTimeout(r, 150));
  }
  throw new Error(`mock backend did not become healthy at ${url}`);
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
    { cwd: repo, env: { ...process.env, PYTHONPATH: path.join(repo, "src") }, stdio: "pipe" },
  );
  await waitHealth(BASE);
});

test.afterAll(async () => {
  if (mockProc && mockProc.pid) mockProc.kill("SIGTERM");
});

test.use({ baseURL: BASE, viewport: { width: 1400, height: 900 } });
test.setTimeout(60_000);

async function setCe(mode: "absent" | "stub"): Promise<void> {
  const r = await fetch(`${BASE}/api/e2e/ce`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode, graph_tab: true }),
  });
  expect(r.ok).toBe(true);
}

async function gotoPower(page: Page): Promise<void> {
  await page.addInitScript(() => {
    localStorage.setItem("sy:ui-mode", "power");
    try { navigator.serviceWorker?.getRegistrations?.().then((rs) => rs.forEach((r) => r.unregister())); } catch { /* ignore */ }
  });
  const resp = await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
  expect(resp?.ok()).toBe(true);
  await page.locator(".sy-shell").waitFor({ timeout: 15_000 });
  const health = await page.evaluate(async () => (await fetch("/api/health")).json());
  expect(health.e2e_mock).toBe(true);
  expect(health.workspace).toBe(MOCK_WS);
  await page.locator(".sy-tabstrip").first().waitFor({ timeout: 15_000 });
}

test("without Curiosity Engine the Graph tab is hidden and Files upload still works", async ({ page }) => {
  await setCe("absent");
  await gotoPower(page);
  // The mode lists a Graph tab; the shell hides it because CE is absent.
  await expect(page.getByRole("tab", { name: "Agents" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Graph" })).toHaveCount(0);
  await expect(page.locator(".sy-ce-sidebar-slot")).toHaveCount(0);

  const upload = page.getByTestId("fb-upload-vault");
  await expect(upload).toBeVisible();
  await upload.click();
  await expect(page.locator(".sy-upload-vault")).toBeVisible();
});

test("CE sidebar header shows the workspace name, never {{WORKSPACE}}", async ({ page }) => {
  await setCe("stub");
  await gotoPower(page);
  await expect(page.getByRole("tab", { name: "Graph" })).toBeVisible();

  const name = page.locator(".sy-ce-sidebar-root .workspace-name");
  await expect(name).toHaveText("switchbay-e2e-mock-ws");
  const sidebarHtml = await page.locator(".sy-ce-sidebar-root").innerHTML();
  expect(sidebarHtml).not.toContain("{{WORKSPACE}}");
  expect(await page.locator("body").innerText()).not.toContain("{{WORKSPACE}}");
  await expect(page.locator(".sy-ce-sidebar-root .sidebar-row")).toHaveCount(1);
  // Files tree stays under the CE page list.
  await expect(page.getByTestId("fb-upload-vault")).toBeVisible();
});

test("CE sidebar + opens Switch Bay's upload dialog; Graph mounts the CE canvas", async ({ page }) => {
  await setCe("stub");
  await gotoPower(page);
  await page.locator(".sy-ce-sidebar-root #sidebar-upload").click();
  await expect(page.locator(".sy-upload-vault")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator(".sy-upload-vault")).toHaveCount(0);

  await page.getByRole("tab", { name: "Graph" }).click();
  await expect(page.locator(".sy-ce-atlas-embed-root #graph")).toBeAttached();
  await expect(page.locator(".sy-graph-count")).toHaveText("1 nodes · 0 edges");
  // Procedure / execution are offered in the label-type filter.
  await expect(page.locator('.label-types-row[data-type="procedure"]')).toHaveCount(1);
  await expect(page.locator('.label-types-row[data-type="execution"]')).toHaveCount(1);
});
