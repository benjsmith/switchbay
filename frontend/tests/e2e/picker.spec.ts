import { test, expect } from "@playwright/test";

test("rail model picker opens a visible menu", async ({ page }) => {
  await page.route("**/api/llm/providers", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        providers: [{
          id: "github_copilot",
          label: "GitHub Copilot",
          category: "subscription",
          default_model: "gpt-4.1",
          models: ["gpt-4.1", "gpt-5"],
          has_key: true,
          capabilities: { chat: true, streaming: true, tools: true },
        }],
        keychain_available: true,
        keychain_backend: "keyring",
        default_provider: "github_copilot",
        default_model: "gpt-4.1",
        routing: null,
      }),
    });
  });
  await page.goto("/");
  await page.locator(".sy-tabstrip").waitFor();
  const btn = page.getByRole("button", { name: "Model picker" });
  await expect(btn).toBeVisible();
  await btn.click();
  const menu = page.locator(".sy-rail-pickmenu");
  await expect(menu).toBeVisible();
  await expect(menu.getByText("GitHub Copilot")).toBeVisible();
  const box = await menu.boundingBox();
  expect(box).toBeTruthy();
  expect(box!.height).toBeGreaterThan(40);
  // Must paint below the 34px rail head, not clip to it.
  const head = await page.locator(".sy-rail-head").boundingBox();
  expect(head).toBeTruthy();
  expect(box!.y).toBeGreaterThan(head!.y + 8);
});
