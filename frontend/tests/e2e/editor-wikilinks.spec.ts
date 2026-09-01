import { expect, test, type Page } from "@playwright/test";

test.use({
  baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://localhost:5173",
});

const editorPath = (page: Page) => page.locator(".sy-editor-path");

test("preview wikilinks open the page in the Editor, and Back returns", async ({ page }) => {
  await page.goto("/");
  await page.locator(".sy-tabstrip, .sy-zen").first().waitFor({ timeout: 20_000 });
  await page.getByRole("tab", { name: "Graph" }).click();
  // Open a page with prose (and therefore wikilinks) via the wiki list.
  await page.locator(".sidebar-row").first().waitFor({ timeout: 20_000 });

  // Find a page whose preview actually has a plain [[wikilink]].
  const links = page.locator(".sy-mdview a.wikilink[href^='#page=']");
  let opened = "";
  for (const row of (await page.locator(".sidebar-row").all()).slice(0, 12)) {
    await row.click();
    await page.getByRole("tab", { name: "Editor" }).click();
    await page.locator(".sy-editor").waitFor({ timeout: 15_000 });
    await page.waitForTimeout(400);
    if (await links.count() > 0) {
      opened = (await editorPath(page).textContent()) ?? "";
      break;
    }
    await page.getByRole("tab", { name: "Graph" }).click();
  }
  test.skip(!opened, "no wiki page with a plain wikilink in this workspace");

  const back = page.locator(".sy-editor-btn--nav");
  await expect(back).toBeDisabled();       // nowhere to go back to yet

  // A wikilink used to render href="#page=<link text>", which the hash
  // router could not resolve to a page id — the click did nothing.
  await links.first().click();
  await expect.poll(async () => (await editorPath(page).textContent()) ?? "")
    .not.toBe(opened);
  const followed = (await editorPath(page).textContent()) ?? "";
  // …and it opens where the reader already is, not over on the Graph tab.
  await expect(page.locator(".sy-editor")).toBeVisible();
  await expect(back).toBeEnabled();

  await back.click();
  await expect.poll(async () => (await editorPath(page).textContent()) ?? "")
    .toBe(opened);
  expect(followed).not.toBe(opened);
});
