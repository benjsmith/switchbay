/**
 * Geometry + web-policy control sync against an isolated mocked backend.
 *
 * E2E_MOCK=1. The mock serves frontend/dist and a fake /api + /ws. It
 * does not start switchbay.daemon.run and does not touch the live vault.
 */
import { test, expect, type Page } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const shotDir = "test-results/shots";
const MOCK_WS = "/tmp/switchbay-e2e-mock-ws";
const MOCK_WS_B = "/tmp/switchbay-e2e-mock-ws-b";
const PORT = process.env.E2E_MOCK_PORT || "41765";
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
        const body = await r.json();
        if (body.e2e_mock === true && body.workspace === MOCK_WS) return;
        throw new Error("refusing non-fixture backend");
      }
    } catch {
      /* not up yet */
    }
    await defWait(150);
  }
  throw new Error(`mock backend did not become healthy at ${url}`);
}

test.beforeAll(async () => {
  if (!fs.existsSync(path.join(dist, "index.html"))) {
    throw new Error("frontend/dist missing — build before Playwright");
  }
  try {
    const r = await fetch(`${BASE}/api/health`);
    if (r.ok) {
      const body = (await r.json()) as { workspace?: string; e2e_mock?: boolean };
      if (body.e2e_mock && body.workspace === MOCK_WS) return;
    }
  } catch {
    /* start our own */
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
      env: { ...process.env, PYTHONPATH: path.join(repo, "src") },
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

test.use({ baseURL: BASE, viewport: { width: 1400, height: 900 } });
test.setTimeout(60_000);

async function assertIsolatedHealth(page: Page): Promise<void> {
  const health = await page.evaluate(async () => {
    const r = await fetch("/api/health");
    return r.json();
  });
  expect(health.e2e_mock, "backend must be the labeled mock, not the live daemon").toBe(true);
  expect(health.workspace).toBe(MOCK_WS);
  expect(String(health.workspace)).not.toContain("Workspaces/curiosity");
}

async function pinGeometry(page: Page, rail: ReturnType<Page["locator"]>, tag: string) {
  const stream = rail.locator(".sy-rail-stream");
  const input = rail.locator(".sy-rail-input-wrap");
  await expect(stream).toBeVisible();
  await expect(input).toBeVisible();
  const rb = await rail.boundingBox();
  const sb = await stream.boundingBox();
  const ib = await input.boundingBox();
  expect(rb && sb && ib, `${tag} boxes`).toBeTruthy();
  if (!rb || !sb || !ib) return;
  const bottomGap = Math.abs(ib.y + ib.height - (rb.y + rb.height));
  expect(bottomGap, `${tag} composer bottom pin`).toBeLessThanOrEqual(8);
  expect(sb.y + sb.height, `${tag} stream above composer`).toBeLessThanOrEqual(ib.y + 4);
  expect(sb.y, `${tag} stream inside rail`).toBeGreaterThanOrEqual(rb.y - 2);
  expect(ib.y + ib.height, `${tag} no overflow`).toBeLessThanOrEqual(rb.y + rb.height + 8);
  const overflowY = await rail.evaluate((el) => {
    const s = getComputedStyle(el);
    return { overflow: s.overflow, clientH: el.clientHeight, scrollH: el.scrollHeight };
  });
  expect(overflowY.scrollH, `${tag} rail scrollHeight`).toBeLessThanOrEqual(overflowY.clientH + 12);
}

async function gotoApp(page: Page, mode: "zen" | "power") {
  await page.addInitScript((m) => {
    localStorage.setItem("sy:ui-mode", m);
    try { navigator.serviceWorker?.getRegistrations?.().then((rs) => rs.forEach((r) => r.unregister())); } catch { /* ignore */ }
  }, mode);
  const resp = await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
  if (!resp || !resp.ok()) {
    throw new Error(`GET / failed: ${resp?.status()} ${await resp?.text()}`);
  }
  await page.locator("#root").waitFor({ timeout: 10_000 });
  try {
    await page.locator(mode === "zen" ? ".sy-zen" : ".sy-shell").waitFor({ timeout: 15_000 });
  } catch (err) {
    const html = await page.content();
    throw new Error(`UI did not render (${mode}). body=${html.slice(0, 1500)}`);
  }
  await assertIsolatedHealth(page);
  // Hello WS remounts chrome; wait until the web control is attached
  // and the first paint has settled.
  await page.locator(".sy-web-policy").first().waitFor({ timeout: 10_000 });
  await page.waitForTimeout(400);
}

test("zen floating chat is two columns and shows web on/off", async ({ page }) => {
  await gotoApp(page, "zen");
  const box = page.locator(".sy-zen-chatbox").first();
  await expect(box).toBeVisible();
  await expect(box.locator(".sy-zen-chat-left")).toBeVisible();
  await expect(box.locator(".sy-zen-chat-right")).toBeVisible();
  const web = box.locator(".sy-web-policy");
  await expect(web).toBeVisible();
  await expect(web.getByText("Web", { exact: true })).toBeVisible();
  await expect(web.getByRole("button", { name: "off" })).toBeVisible();
  await expect(web.getByRole("button", { name: "on" })).toBeVisible();
  await page.locator(".sy-zen-chatbox .sy-web-policy").getByRole("button", { name: "on" }).click();
  await expect(page.locator(".sy-zen-chatbox .sy-web-policy").getByRole("button", { name: "on" })).toHaveClass(/sy-web-policy-btn--on/);
  await page.locator(".sy-zen-chatbox .sy-web-policy").getByRole("button", { name: "off" }).click();
  await expect(page.locator(".sy-zen-chatbox .sy-web-policy").getByRole("button", { name: "off" })).toHaveClass(/sy-web-policy-btn--on/);
  fs.mkdirSync(shotDir, { recursive: true });
  await page.screenshot({ path: `${shotDir}/zen-floating-web.png`, fullPage: true });
});

test("zen docked chat pins composer at narrow and wide geometry", async ({ page }) => {
  await gotoApp(page, "zen");
  await page.locator(".sy-zen-surf-pickbtn").click();
  await page.getByRole("menuitem", { name: "Chat" }).click();
  const rail = page.locator(".sy-zen-surf-body .sy-rail--embedded, .sy-zen-surf-body .sy-rail");
  await expect(rail.first()).toBeVisible();
  await expect(rail.locator(".sy-zen-chat-left")).toHaveCount(0);
  await expect(rail.locator(".sy-web-policy").getByText("Web", { exact: true })).toBeVisible();
  await pinGeometry(page, rail.first(), "short transcript");

  for (let i = 0; i < 24; i += 1) {
    await page.request.post(`${BASE}/api/e2e/push`, {
      data: {
        type: "notice",
        text: `long transcript line ${i} — ${"word ".repeat(20)}`,
        kind: "chat",
        workspace: MOCK_WS,
        thread_id: "th-e2e",
      },
    });
  }
  await expect(rail.locator(".sy-rail-entry").first()).toBeVisible({ timeout: 10_000 });

  fs.mkdirSync(shotDir, { recursive: true });
  await page.setViewportSize({ width: 1400, height: 900 });
  await pinGeometry(page, rail.first(), "wide");
  await page.screenshot({ path: `${shotDir}/zen-docked-wide.png` });
  await page.setViewportSize({ width: 900, height: 800 });
  await pinGeometry(page, rail.first(), "narrow");
  await page.screenshot({ path: `${shotDir}/zen-docked-narrow.png` });
  await page.setViewportSize({ width: 1400, height: 900 });
});

test("web policy toggles, remote updates, workspace switch, failed save", async ({ page }) => {
  await gotoApp(page, "zen");

  const railWeb = page.locator(".sy-web-policy").first();
  await expect(railWeb.getByRole("button", { name: "off" })).toBeVisible();
  await page.locator(".sy-web-policy").first().getByRole("button", { name: "on" }).click();
  await expect(page.locator(".sy-web-policy").first().getByRole("button", { name: "on" })).toHaveClass(/sy-web-policy-btn--on/);

  const chrome = page.locator(".sy-zen-chrome--top");
  await expect(chrome).toBeVisible();
  await chrome.hover();
  await chrome.getByRole("button", { name: "Settings", exact: true }).click();
  const modal = page.locator(".sy-settings").first();
  await expect(modal).toBeVisible({ timeout: 10_000 });
  const settingsWeb = modal.locator(".sy-web-policy").first();
  await expect(settingsWeb).toBeVisible({ timeout: 10_000 });
  await settingsWeb.scrollIntoViewIfNeeded();
  await expect(settingsWeb.getByRole("button", { name: "on" })).toHaveClass(/sy-web-policy-btn--on/);
  fs.mkdirSync(shotDir, { recursive: true });
  await expect(modal).toBeVisible();
  await modal.screenshot({ path: `${shotDir}/settings-web-policy.png`, animations: "disabled" });

  await page.request.post(`${BASE}/api/e2e/push`, {
    data: {
      type: "web_policy",
      workspace: MOCK_WS,
      enabled: false,
      admin_allows: true,
      requested: false,
    },
  });
  await expect(settingsWeb.getByRole("button", { name: "off" })).toHaveClass(/sy-web-policy-btn--on/);
  await expect(railWeb.getByRole("button", { name: "off" })).toHaveClass(/sy-web-policy-btn--on/);

  await page.request.post(`${BASE}/api/e2e/fail-save`, { data: { fail: true } });
  await settingsWeb.getByRole("button", { name: "on" }).click();
  await expect(modal.locator(".sy-web-policy-err")).toBeVisible();
  await expect(settingsWeb.getByRole("button", { name: "off" })).toHaveClass(/sy-web-policy-btn--on/);
  await page.request.post(`${BASE}/api/e2e/fail-save`, { data: { fail: false } });
  await page.keyboard.press("Escape");

  await page.locator(".sy-ws-trigger").click();
  await page.locator(".sy-ws-item").filter({ hasText: "switchbay-e2e-mock-ws-b" }).click();
  await expect.poll(async () => {
    const h = await page.evaluate(async () => {
      const r = await fetch("/api/workspaces");
      return r.json();
    });
    return h.active as string;
  }).toBe(MOCK_WS_B);
  await expect(page.locator(".sy-web-policy").first().getByRole("button", { name: "on" })).toHaveClass(/sy-web-policy-btn--on/);
  await page.locator(".sy-ws-trigger").click();
  await page.locator(".sy-ws-item").filter({ hasText: "switchbay-e2e-mock-ws" }).filter({ hasNotText: "switchbay-e2e-mock-ws-b" }).click();
  await expect(page.locator(".sy-web-policy").first().getByRole("button", { name: "off" })).toHaveClass(/sy-web-policy-btn--on/);
});


test("377px Rail has one header Web control and no overlapping footer controls", async ({ page }) => {
  await page.route("**/api/llm/providers", route => route.fulfill({ json: {
    providers: [{ id: "grok-build", label: "Grok Build", category: "cli", default_model: "grok-4.6", has_key: true }],
    default_provider: "grok-build", default_model: "grok-4.6",
  } }));
  await page.route("**/api/llm/reasoning-options", route => route.fulfill({ json: {
    provider: "grok-build", model: "grok-4.6", selected: "xhigh",
    options: [{ id: "low", label: "low" }, { id: "xhigh", label: "extra high" }],
  } }));
  await gotoApp(page, "power");
  await page.addStyleTag({ content: ":root { --rail-w: 377px; }" });
  const rail = page.locator(".sy-shell > .sy-rail");
  await expect(rail.locator(".sy-web-policy")).toHaveCount(1);
  await expect(rail.locator(".sy-rail-head .sy-web-policy")).toBeVisible();
  await expect(rail.locator(".sy-rail-input-wrap .sy-web-policy")).toHaveCount(0);
  await pinGeometry(page, rail, "377px Rail");
  const inspect = async () => rail.locator(".sy-rail-composer-tools").evaluate((row) => {
    const outer = row.getBoundingClientRect();
    const els = [...row.querySelectorAll(".sy-orch > *, .sy-rail-composer-end > *")]
      .map(el => ({ label: el.textContent || el.getAttribute("aria-label"), box: el.getBoundingClientRect() }))
      .filter(x => x.box.width > 0 && x.box.height > 0);
    return els.flatMap((x, i) => {
      const issues: string[] = [];
      if (x.box.left < outer.left - 1 || x.box.right > outer.right + 1) issues.push(`${x.label} overflows`);
      for (const y of els.slice(i + 1)) {
        if (Math.min(x.box.right, y.box.right) - Math.max(x.box.left, y.box.left) > 1 &&
            Math.min(x.box.bottom, y.box.bottom) - Math.max(x.box.top, y.box.top) > 1) issues.push(`${x.label} overlaps ${y.label}`);
      }
      return issues;
    });
  });
  await expect.poll(inspect).toEqual([]);
  await page.request.post(`${BASE}/api/e2e/fail-save`, { data: { fail: true } });
  await rail.locator(".sy-web-policy").getByRole("button", { name: "on", exact: true }).click();
  await expect(rail.locator(".sy-web-policy-err")).toBeVisible();
  await expect.poll(inspect).toEqual([]);
  const reset = await rail.locator(".sy-rail-head .sy-rail-reset").boundingBox();
  expect(reset?.height).toBeLessThan(28);
  const headOverflow = await rail.locator(".sy-rail-head").evaluate(el => el.scrollWidth - el.clientWidth);
  expect(headOverflow).toBeLessThanOrEqual(1);
  fs.mkdirSync(shotDir, { recursive: true });
  await rail.screenshot({ path: `${shotDir}/rail-377-failed-save.png` });
  await page.request.post(`${BASE}/api/e2e/fail-save`, { data: { fail: false } });
});
