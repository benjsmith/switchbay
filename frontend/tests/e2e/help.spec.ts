import { test, expect } from "@playwright/test";
import fs from "node:fs";

test("help modal opens and renders", async ({ page }) => {
  // Providers walks on-disk MLX caches on the event loop; stub so
  // Help can open without waiting on that scan.
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
  await page.goto("/");
  await page.locator(".sy-tabstrip").waitFor();
  await page.getByRole("button", { name: "Help" }).click();
  const modal = page.locator(".sy-help");
  await expect(modal).toBeVisible();
  await expect(modal.getByText("How Switch Bay works")).toBeVisible();
  await expect(modal.getByText("DuckDB", { exact: false }).first()).toBeVisible();
  await expect(modal.getByText("Power")).toBeVisible();
  await expect(modal.getByText(/Switch Bay v\d/)).toBeVisible();
  await expect(modal.getByText(/Curiosity Engine/)).toBeVisible();
  fs.mkdirSync("test-results/shots", { recursive: true });
  await modal.screenshot({ path: "test-results/shots/help.png" });
});
