/**
 * Classification badge, exclusion rules, public-write dialog, and
 * Review labels. E2E_MOCK=1. The mock does not start the live daemon.
 */
import { test, expect, type Page } from "@playwright/test";
import { spawn, type ChildProcess, execFileSync } from "node:child_process";
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

test("a public-write message from the daemon opens the dialog", async ({ page }) => {
  await openApp(page);
  await page.request.post(`${BASE}/api/e2e/push`, {
    data: { type: "public_write", mount: "pub" },
  });
  const dialog = page.locator("[data-testid='public-write-dialog']");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toHaveCount(0);
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

function inspectPdf(file: string): {
  label: string; stamped: boolean; xmp: boolean; sha256: string;
  encrypted: boolean; msip: boolean; user: string; version: string; workspace: string;
} {
  const code = [
    "import hashlib, json, sys",
    "from pypdf import PdfReader",
    "path = sys.argv[1]",
    "data = open(path, 'rb').read()",
    "reader = PdfReader(path)",
    "meta = None",
    "xmp = b''",
    "if not reader.is_encrypted:",
    "    meta = reader.metadata",
    "    if reader.xmp_metadata is not None:",
    "        xmp = reader.xmp_metadata.stream.get_data()",
    "stamped = False",
    "if not reader.is_encrypted:",
    "    for page in reader.pages:",
    "        contents = page.get_contents()",
    "        if contents is not None and b'SWITCHBAY' in contents.get_data():",
    "            stamped = True",
    "print(json.dumps({",
    "  'label': str(meta.get('/SwitchbayLabel') or '') if meta else '',",
    "  'user': str(meta.get('/SwitchbayUser') or '') if meta else '',",
    "  'version': str(meta.get('/SwitchbayVersion') or '') if meta else '',",
    "  'workspace': str(meta.get('/SwitchbayWorkspace') or '') if meta else '',",
    "  'xmp': b'urn:switchbay:classification:1.0' in xmp,",
    "  'sha256': hashlib.sha256(data).hexdigest(),",
    "  'encrypted': bool(reader.is_encrypted),",
    "  'stamped': stamped,",
    "  'msip': b'MSIP_Label_' in xmp,",
    "}))",
  ].join("\n");
  const out = execFileSync("uv", ["run", "--no-sync", "python", "-c", code, file], {
    cwd: repo, encoding: "utf8",
  });
  return JSON.parse(out);
}

async function openSlideshow(page: Page, slug: string) {
  await page.getByRole("tab", { name: "Slideshow" }).click();
  await page.locator(".sy-report-host").waitFor();
  await expect.poll(async () => {
    await page.evaluate((name) => {
      window.dispatchEvent(new CustomEvent("sy:open-html-deck", {
        detail: { slug: name, title: "Demo" },
      }));
    }, slug);
    return page.getByRole("button", { name: "Save PDF" }).count();
  }).toBeGreaterThan(0);
}

test("confidential export stamps the label and writes metadata and an audit row", async ({ page }) => {
  await page.request.post(`${BASE}/api/e2e/seed`, {
    data: {
      reset_exports: true,
      session_label: "confidential",
      slideshow: { slug: "sealed", title: "Sealed", slides: [{ heading: "Bearing", source_ref: "memo:bearing" }] },
    },
  });
  await openApp(page);
  await openSlideshow(page, "sealed");
  await page.getByRole("button", { name: "Save PDF" }).click();
  await expect(page.locator("[data-testid='export-destination-dialog']")).toHaveCount(0);
  await expect(page.locator("[data-testid='pdf-export-status']")).toContainText("vault/exports/sealed.pdf");
  const file = path.join(MOCK_WS, "vault/exports/sealed.pdf");
  const info = inspectPdf(file);
  expect(info.label).toBe("confidential");
  expect(info.stamped).toBe(true);
  expect(info.xmp).toBe(true);
  expect(info.encrypted).toBe(false);
  expect(info.user.length).toBeGreaterThan(0);
  expect(info.version.length).toBeGreaterThan(0);
  expect(info.workspace).toBe(MOCK_WS);
  const audit = await page.request.get(`${BASE}/api/e2e/audit`);
  const body = await audit.json() as { rows: Array<Record<string, unknown>> };
  const row = body.rows.filter((item) => item.event === "export").at(-1);
  expect(row?.label).toBe("confidential");
  expect(row?.sources).toEqual(["memo:bearing"]);
  expect(row?.destination_class).toBe("inside");
  expect(row?.sha256).toBe(info.sha256);
  expect(row?.user).toBe(info.user);
  expect(typeof row?.ts).toBe("string");
});

test("a source above the clearance is refused", async ({ page }) => {
  await page.request.post(`${BASE}/api/e2e/seed`, {
    data: {
      reset_exports: true,
      session_label: "public",
      admin: { exports: { clearance: "internal", max_ceiling: "internal" } },
      slideshow: { slug: "high", slides: [{ heading: "Board", classification: "confidential" }] },
    },
  });
  await openApp(page);
  await openSlideshow(page, "high");
  await page.getByRole("button", { name: "Save PDF" }).click();
  await expect(page.locator("[data-testid='pdf-export-error']")).toContainText("above the clearance");
  expect(fs.existsSync(path.join(MOCK_WS, "vault/exports/high.pdf"))).toBe(false);
});

test("a denied source is refused", async ({ page }) => {
  await page.request.post(`${BASE}/api/e2e/seed`, {
    data: {
      reset_exports: true,
      session_label: "public",
      admin: { exports: { clearance: "restricted" } },
      slideshow: { slug: "denied", slides: [{ heading: "Customers", source_ref: "deny:customer" }] },
    },
  });
  await openApp(page);
  await openSlideshow(page, "denied");
  await page.getByRole("button", { name: "Save PDF" }).click();
  await expect(page.locator("[data-testid='pdf-export-error']")).toContainText("cannot be exported");
  expect(fs.existsSync(path.join(MOCK_WS, "vault/exports/denied.pdf"))).toBe(false);
});

test("outside-boundary destination asks OK or Cancel and shows the encryption toggle", async ({ page }) => {
  const outside = "/tmp/Dropbox/switchbay-e2e.pdf";
  fs.rmSync(outside, { force: true });
  await page.request.post(`${BASE}/api/e2e/seed`, {
    data: {
      reset_exports: true,
      session_label: "confidential",
      admin: {},
      slideshow: { slug: "carry", title: "Carry" },
    },
  });
  await openApp(page);
  await openSlideshow(page, "carry");
  await page.getByTestId("pdf-export-options").locator("summary").click();
  await page.getByLabel("PDF destination").fill(outside);
  await page.getByRole("button", { name: "Save PDF" }).click();
  const dialog = page.locator("[data-testid='export-destination-dialog']");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("button", { name: "OK" })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Always allow" })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Cancel" })).toBeVisible();
  await expect(dialog.getByTestId("export-encrypt-toggle")).toBeVisible();
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.locator("[data-testid='pdf-export-status']")).toContainText("cancelled");
  expect(fs.existsSync(outside)).toBe(false);
  await page.getByRole("button", { name: "Save PDF" }).click();
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "OK" }).click();
  await expect(page.locator("[data-testid='pdf-export-status']")).toContainText(outside);
  expect(fs.existsSync(outside)).toBe(true);
  expect(inspectPdf(outside).label).toBe("confidential");
});

test("encryption toggle applies optional AES-256", async ({ page }) => {
  await page.request.post(`${BASE}/api/e2e/seed`, {
    data: {
      reset_exports: true,
      session_label: "internal",
      admin: {},
      slideshow: { slug: "locked", title: "Locked" },
    },
  });
  await openApp(page);
  await openSlideshow(page, "locked");
  await page.getByTestId("pdf-export-options").locator("summary").click();
  await page.getByTestId("export-encrypt-toggle").check();
  const mode = page.getByLabel("Encryption mode");
  await expect(mode.locator("option")).toHaveText(["Password", "Recipient certificate"]);
  await mode.selectOption("password");
  await page.getByLabel("PDF password").fill("correct horse");
  await page.getByRole("button", { name: "Save PDF" }).click();
  await expect(page.locator("[data-testid='pdf-export-status']")).toContainText("vault/exports/locked.pdf");
  const file = path.join(MOCK_WS, "vault/exports/locked.pdf");
  const info = inspectPdf(file);
  expect(info.encrypted).toBe(true);
  expect(info.label).toBe("");
  const opened = execFileSync("uv", ["run", "--no-sync", "python", "-c", [
    "import sys",
    "from pypdf import PdfReader",
    "reader = PdfReader(sys.argv[1])",
    "reader.decrypt('correct horse')",
    "encrypt = reader.trailer['/Encrypt'].get_object()",
    "assert str(encrypt['/CF']['/StdCF']['/CFM']) == '/AESV3'",
    "assert int(encrypt['/Length']) == 256",
    "blob = b''",
    "for page in reader.pages:",
    "    contents = page.get_contents()",
    "    if contents is not None: blob += contents.get_data()",
    "assert b'SWITCHBAY INTERNAL' in blob",
    "print(reader.metadata.get('/SwitchbayLabel'))",
  ].join("\n"), file], { cwd: repo, encoding: "utf8" });
  expect(opened.trim()).toBe("internal");
});

test("purview mapping calls the configured labeling endpoint", async ({ page }) => {
  const guid = "2096f6a2-d2f7-48be-b329-b73aaa526e5d";
  await page.request.post(`${BASE}/api/e2e/seed`, {
    data: {
      reset_exports: true,
      session_label: "confidential",
      admin: { exports: { purview: {
        endpoint: `${BASE}/api/e2e/label`,
        site_id: "cb46c030-1825-4e81-a295-151c039dbf02",
        labels: { confidential: guid },
      } } },
      slideshow: { slug: "labelled", title: "Labelled" },
    },
  });
  await openApp(page);
  await openSlideshow(page, "labelled");
  await page.getByTestId("pdf-export-options").locator("summary").click();
  await expect(page.getByTestId("export-encrypt-toggle")).toHaveCount(0);
  await page.getByRole("button", { name: "Save PDF" }).click();
  await expect(page.locator("[data-testid='pdf-export-status']")).toContainText("vault/exports/labelled.pdf");
  const status = await (await page.request.get(`${BASE}/api/e2e/label-status`)).json() as {
    calls: number; label: string; label_id: string;
  };
  expect(status.calls).toBeGreaterThan(0);
  expect(status.label).toBe("confidential");
  expect(status.label_id).toBe(guid);
  const info = inspectPdf(path.join(MOCK_WS, "vault/exports/labelled.pdf"));
  expect(info.msip).toBe(true);
  expect(info.stamped).toBe(true);
  expect(info.label).toBe("confidential");
});
