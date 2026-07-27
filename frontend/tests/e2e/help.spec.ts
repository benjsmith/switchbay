import { test, expect } from "@playwright/test";
import fs from "node:fs";

test("help modal opens and renders", async ({ page }) => {
  await page.goto("/");
  await page.locator(".sy-tabstrip").waitFor();
  await page.getByRole("button", { name: "Help" }).click();
  const modal = page.locator(".sy-help");
  await expect(modal).toBeVisible();
  await expect(modal.getByText("How switchbay works")).toBeVisible();
  await expect(modal.getByText("DuckDB", { exact: false }).first()).toBeVisible();
  fs.mkdirSync("test-results/shots", { recursive: true });
  await modal.screenshot({ path: "test-results/shots/help.png" });
});
