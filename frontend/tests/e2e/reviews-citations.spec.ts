import { test, expect } from "@playwright/test";

async function stubProviders(page: import("@playwright/test").Page) {
  await page.route("**/api/llm/providers", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        providers: [],
        keychain_available: false,
        keychain_backend: "none",
        default_provider: "",
      }),
    });
  });
}

test("page proposals never appear as rail cards", async ({ page }) => {
  await stubProviders(page);
  await page.goto("/");
  await page.locator(".sy-tabstrip").waitFor();
  await expect(page.locator(".sy-rail-entry", { hasText: "Proposed" })).toHaveCount(0);
  await expect(page.getByText("Accept — file page")).toHaveCount(0);
});

test("revealing a workspace path selects the Files row", async ({ page, request }) => {
  await stubProviders(page);
  const tree = await request.get("/api/tree");
  const body = await tree.json() as { files?: string[] };
  const files = body.files ?? [];
  const target =
    files.find((p) => p.startsWith("wiki/") && p.endsWith(".md") && !p.includes("/figures/"))
    || files.find((p) => p.startsWith("wiki/") && !p.includes("/_assets/"))
    || files.find((p) => !p.startsWith("reports/") && !p.startsWith("slideshows/") && !p.startsWith("worksheets/") && p.includes("/"));
  test.skip(!target, "workspace has no files to reveal");
  await page.goto("/");
  await page.locator(".sy-tabstrip").waitFor();
  await page.locator(".sy-fb").waitFor();
  await page.evaluate((path) => {
    window.dispatchEvent(new CustomEvent("sy:reveal-file", { detail: { path } }));
  }, target);
  const row = page.locator(`[data-fb-path="${target}"]`);
  await expect(row).toBeVisible({ timeout: 10_000 });
  await expect(row).toHaveClass(/sy-fb-row--active/);
});
