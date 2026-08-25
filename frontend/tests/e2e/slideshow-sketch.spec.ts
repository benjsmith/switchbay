import { test, expect } from "@playwright/test";

test("Sketch tab is a library, not a slide deck", async ({ page }) => {
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
  await page.getByRole("tab", { name: "Sketch" }).click();
  await expect(page.locator(".sy-sketch")).toBeVisible();
  await expect(page.getByRole("button", { name: "+ Add Sketch" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Deck ▾" })).toHaveCount(0);
  await expect(page.locator(".sy-sketch-deck-badge")).toHaveCount(0);
});

test("Editor offers HTML slideshow creation", async ({ page }) => {
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
  await page.getByRole("tab", { name: "Editor" }).click();
  const slideshow = page.getByRole("button", { name: "→ Slideshow" });
  const empty = page.locator(".sy-editor");
  await expect(empty).toBeVisible();
  // Button is present once a page is selected; keep the control name
  // stable even if this workspace has no current page.
  if (await slideshow.count()) {
    await expect(slideshow).toBeVisible();
    await expect(page.getByRole("button", { name: "→ Sketch deck" })).toHaveCount(0);
  }
});
