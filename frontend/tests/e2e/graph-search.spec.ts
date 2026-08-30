import { expect, test, type Page } from "@playwright/test";

test.use({
  baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://localhost:5173",
});

async function graphReady(page: Page): Promise<void> {
  await page.locator(".sy-graph-host, .sy-zen").first().waitFor({ timeout: 20_000 });
  await page.locator("#graph-search-input").waitFor({ timeout: 20_000 });
}

test("graph search highlights nodes and files; X clears", async ({ page }) => {
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

  await input.fill("attention");
  await expect(page.locator("#graph-search-clear")).toBeVisible();
  await expect(page.locator("#graph-search-count")).not.toHaveText("0");
  await expect.poll(async () =>
    page.locator(".node.search-hit").count(),
  ).toBeGreaterThan(0);
  await expect(page.locator('.sy-fb-row--search-hit[data-fb-path="wiki/concepts/attention.md"]')).toBeVisible();
  await expect(page.locator(".sy-fb-row--search-hit")).toHaveCount(4);

  await page.locator('.sy-fb-row--search-hit[data-fb-path="wiki/concepts/attention.md"]').click();
  await page.getByRole("tab", { name: "Graph" }).click();
  await graphReady(page);
  await expect(page.locator("#graph-search-input")).toHaveValue("attention");
  await expect(page.locator("#graph-search-clear")).toBeVisible();
  await expect(page.locator("#graph-search-count")).not.toHaveText("0");
  await expect(page.locator(".sy-fb-row--search-hit")).toHaveCount(4);

  await page.locator("#graph-search-clear").click();
  await expect(page.locator("#graph-search-clear")).toBeHidden();
  await expect(page.locator(".sy-fb-row--search-hit")).toHaveCount(0);
  await expect(page.locator(".node.search-hit")).toHaveCount(0);
  await expect(input).toHaveValue("");
});
