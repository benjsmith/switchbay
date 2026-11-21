/**
 * Real user workflows against a running Switch Bay daemon.
 *
 * The side-by-side runner (scripts/side-by-side-workflows.sh) starts
 * the pre-split daemon and this daemon on separate ports and state
 * directories, then runs this file against each. Point Playwright at
 * either one with E2E_BASE_URL. The workspace is a copy of
 * samples/ml-walkthrough with a Reviews tab and one proposed page
 * seeded before the daemon boots.
 *
 * Run: E2E_BASE_URL=http://127.0.0.1:8872 pnpm --dir frontend exec playwright test tests/e2e/workflows.spec.ts
 */
import { test, expect, type Page } from "@playwright/test";

test.use({ screenshot: "only-on-failure" });

async function boot(page: Page): Promise<void> {
  await page.goto("/");
  await page.locator(".sy-tabstrip").waitFor();
}

/** The graph probe can open the first-run card after the shell paints.
 *  Dismiss it so later clicks hit the workbench, not the card. */
async function dismissFirstRun(page: Page): Promise<void> {
  const wizard = page.getByRole("dialog", { name: /New workspace/ });
  const skipTour = page.getByRole("button", { name: "Skip tour" });
  try {
    await wizard.waitFor({ state: "visible", timeout: 2_000 });
  } catch {
    if (await skipTour.isVisible().catch(() => false)) await skipTour.click();
    return;
  }
  if (await skipTour.isVisible().catch(() => false)) await skipTour.click();
  await page.getByRole("button", { name: "Skip for now" }).click();
  await expect(wizard).toBeHidden();
}

async function ready(page: Page): Promise<void> {
  await boot(page);
  await dismissFirstRun(page);
  await expect(page.locator(".sy-tabstrip")).toBeVisible();
}

async function openTab(page: Page, name: string): Promise<void> {
  // Reviews carries a nested scope control, so its accessible name is
  // longer than the visible title.
  const tab = page.getByRole("tab", { name: new RegExp("^" + name + "\\b") });
  await tab.click();
  await expect(tab).toHaveAttribute("aria-selected", "true");
  await expect(page.getByText("threw an error")).toHaveCount(0);
}

async function openSettings(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: /Settings/ });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("Loading…")).toHaveCount(0);
}

test("power shell shows the core workbench tabs", async ({ page }) => {
  await ready(page);
  for (const name of ["Editor", "Table", "Sheet", "Plot", "Sketch", "Library", "Projects", "Agents"]) {
    await expect(page.getByRole("tab", { name, exact: true })).toBeVisible();
  }
  await expect(page.getByRole("button", { name: "Help", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Settings", exact: true })).toBeVisible();
});

test("graph viewer shows the wiki and its search box", async ({ page }) => {
  await ready(page);
  const graph = page.getByRole("tab", { name: "Graph", exact: true });
  await expect(graph).toBeVisible();
  await graph.click();
  await expect(page.getByRole("searchbox", { name: "Search the graph" })).toBeVisible();
  await expect(page.getByText(/\d+ nodes/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Replay curation history" })).toBeVisible();
});

test("graph search accepts a query", async ({ page }) => {
  await ready(page);
  await page.getByRole("tab", { name: "Graph", exact: true }).click();
  const search = page.getByRole("searchbox", { name: "Search the graph" });
  await search.fill("attention");
  await expect(search).toHaveValue("attention");
});

test("first-run card can be skipped when the wiki probe offers it", async ({ page }) => {
  await boot(page);
  const wizard = page.getByRole("dialog", { name: /New workspace/ });
  try {
    await wizard.waitFor({ state: "visible", timeout: 3_000 });
  } catch {
    // The probe found a wiki, so the card stays closed and the graph tab is up.
    await expect(page.getByRole("tab", { name: "Graph", exact: true })).toBeVisible();
    return;
  }
  await expect(wizard.getByText("Start clean")).toBeVisible();
  await wizard.getByRole("button", { name: "Skip for now" }).click();
  await expect(wizard).toBeHidden();
});

test("help modal explains how switch bay works", async ({ page }) => {
  await ready(page);
  await page.getByRole("button", { name: "Help", exact: true }).click();
  const modal = page.locator(".sy-help");
  await expect(modal).toBeVisible();
  await expect(modal.getByText("How Switch Bay works")).toBeVisible();
  await expect(modal.getByText("Power")).toBeVisible();
});

test("help modal shows the installed version", async ({ page }) => {
  await ready(page);
  await page.getByRole("button", { name: "Help", exact: true }).click();
  await expect(page.locator(".sy-help").getByText(/Switch Bay v\d/)).toBeVisible();
});

test("escape closes the help modal", async ({ page }) => {
  await ready(page);
  await page.getByRole("button", { name: "Help", exact: true }).click();
  await expect(page.locator(".sy-help")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator(".sy-help")).toBeHidden();
});

test("settings opens on the providers dialog", async ({ page }) => {
  await ready(page);
  await openSettings(page);
  await expect(page.locator("#sy-settings-title")).toHaveText(/Settings/);
});

test("settings shows task models", async ({ page }) => {
  await ready(page);
  await openSettings(page);
  await expect(page.getByRole("heading", { name: "Task models" })).toBeVisible();
});

test("settings shows mcp servers", async ({ page }) => {
  await ready(page);
  await openSettings(page);
  await expect(page.getByRole("heading", { name: "MCP servers" })).toBeVisible();
});

test("settings shows extension packs", async ({ page }) => {
  await ready(page);
  await openSettings(page);
  await expect(page.getByRole("heading", { name: "Extension packs" })).toBeVisible();
});

test("settings shows user tabs", async ({ page }) => {
  await ready(page);
  await openSettings(page);
  await expect(page.getByRole("heading", { name: "User tabs" })).toBeVisible();
});

test("settings shows the local browser control", async ({ page }) => {
  await ready(page);
  await openSettings(page);
  const heading = page.getByRole("heading", { name: "Local browser" });
  await heading.scrollIntoViewIfNeeded();
  await expect(heading).toBeVisible();
  await expect(page.getByText(/Playwright CLI/)).toBeVisible();
});

test("local browser pill toggles and restores", async ({ page }) => {
  await ready(page);
  await openSettings(page);
  const section = page.locator("section", {
    has: page.getByRole("heading", { name: "Local browser" }),
  });
  await section.scrollIntoViewIfNeeded();
  const pill = section.locator("button.sy-settings-pill");
  const label = async () => ((await pill.textContent()) ?? "").trim().toLowerCase();
  const before = await label();
  if (before === "locked") {
    await expect(pill).toBeDisabled();
    return;
  }
  await pill.click();
  await expect.poll(label).not.toBe(before);
  await pill.click();
  await expect.poll(label).toBe(before);
});

test("settings shows permissions", async ({ page }) => {
  await ready(page);
  await openSettings(page);
  const heading = page.getByRole("heading", { name: "Permissions" });
  await heading.scrollIntoViewIfNeeded();
  await expect(heading).toBeVisible();
});

test("settings shows the curator profile", async ({ page }) => {
  await ready(page);
  await openSettings(page);
  const heading = page.getByRole("heading", { name: /Curator profile/ });
  await heading.scrollIntoViewIfNeeded();
  await expect(heading).toBeVisible();
});

test("settings shows workspaces home", async ({ page }) => {
  await ready(page);
  await openSettings(page);
  const heading = page.getByRole("heading", { name: "Workspaces home" });
  await heading.scrollIntoViewIfNeeded();
  await expect(heading).toBeVisible();
});

test("settings shows storage", async ({ page }) => {
  await ready(page);
  await openSettings(page);
  const heading = page.getByRole("heading", { name: "Storage" });
  await heading.scrollIntoViewIfNeeded();
  await expect(heading).toBeVisible();
});

test("settings shows the local agent model section", async ({ page }) => {
  await ready(page);
  await openSettings(page);
  const heading = page.getByRole("heading", { name: "Local agent model" });
  await heading.scrollIntoViewIfNeeded();
  await expect(heading).toBeVisible();
});

test("settings close button dismisses the dialog", async ({ page }) => {
  await ready(page);
  await openSettings(page);
  await page.getByRole("button", { name: "Close" }).click();
  await expect(page.getByRole("dialog", { name: /Settings/ })).toBeHidden();
});

test("theme toggle keeps the workbench mounted", async ({ page }) => {
  await ready(page);
  await page.getByRole("button", { name: "Toggle theme" }).click();
  await expect(page.locator(".sy-tabstrip")).toBeVisible();
  await page.getByRole("button", { name: "Toggle theme" }).click();
  await expect(page.getByRole("tab", { name: "Library" })).toBeVisible();
});

test("web egress toggle flips on and back off", async ({ page }) => {
  await ready(page);
  const web = page.getByRole("group", { name: "Web" });
  await expect(web).toBeVisible();
  const on = web.getByRole("button", { name: "on" });
  const off = web.getByRole("button", { name: "off" });
  await on.click();
  await expect(on).toHaveAttribute("aria-pressed", "true");
  await off.click();
  await expect(off).toHaveAttribute("aria-pressed", "true");
});

test("workspace menu opens from the top bar", async ({ page }) => {
  await ready(page);
  await page.locator(".sy-ws-trigger").click();
  await expect(page.locator(".sy-ws-menu")).toBeVisible();
});

test("file search narrows the tree to evidence pages", async ({ page }) => {
  await ready(page);
  const search = page.locator(".sy-fb-search");
  await search.fill("evi-rag");
  await expect(page.locator(".sy-fb-name", { hasText: "evi-rag-reduces-hallucination.md" })).toBeVisible();
});

test("opening an evidence page shows it in the editor", async ({ page }) => {
  await ready(page);
  await page.locator(".sy-fb-search").fill("evi-rag-reduces-hallucination.md");
  await page.locator(".sy-fb-name", { hasText: "evi-rag-reduces-hallucination.md" }).click();
  await expect(page.getByRole("tab", { name: "Editor" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByText(/reduce hallucination/i).first()).toBeVisible();
});

test("opening the wiki index shows the walkthrough heading", async ({ page }) => {
  await ready(page);
  await page.locator(".sy-fb-search").fill("wiki/index.md");
  await page.locator(".sy-fb-name", { hasText: /^index\.md$/ }).click();
  await expect(page.getByText("ML walkthrough").first()).toBeVisible();
});

test("editor exposes the raw and rendered view toggle", async ({ page }) => {
  await ready(page);
  await page.locator(".sy-fb-search").fill("wiki/index.md");
  await page.locator(".sy-fb-name", { hasText: /^index\.md$/ }).click();
  await expect(page.getByRole("group", { name: "Editor view" })).toBeVisible();
});

test("plot tab shows the empty gallery", async ({ page }) => {
  await ready(page);
  await openTab(page, "Plot");
  await expect(page.getByRole("heading", { name: "No figures yet" })).toBeVisible();
  await expect(page.getByRole("button", { name: "+ New Plot…" })).toBeVisible();
});

test("plot tab explains where extracted figures land", async ({ page }) => {
  await ready(page);
  await openTab(page, "Plot");
  await expect(page.getByText(/Extracted figures from your sources/)).toBeVisible();
});

test("library lists plots reports slideshows and worksheets", async ({ page }) => {
  await ready(page);
  await openTab(page, "Library");
  for (const heading of ["Plots", "Reports", "Slideshows", "Worksheets"]) {
    await expect(page.getByRole("heading", { name: heading })).toBeVisible();
  }
});

test("library explains where generated plots are listed", async ({ page }) => {
  await ready(page);
  await openTab(page, "Library");
  await expect(page.getByText(/No generated plots yet|Charts you create are listed here/).first()).toBeVisible();
});

test("sketch tab shows its toolbar", async ({ page }) => {
  await ready(page);
  await openTab(page, "Sketch");
  await expect(page.locator(".sy-sketch-toolbar")).toBeVisible();
});

test("sheet tab shows the spreadsheet surface", async ({ page }) => {
  await ready(page);
  await openTab(page, "Sheet");
  await expect(page.locator(".sy-sheet")).toBeVisible();
});

test("table tab shows the duckdb surface", async ({ page }) => {
  await ready(page);
  await openTab(page, "Table");
  await expect(page.locator(".sy-duckdb")).toBeVisible();
});

test("projects tab shows the general card when nothing is tagged", async ({ page }) => {
  await ready(page);
  await openTab(page, "Projects");
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible();
  await expect(page.getByText(".curator/projects.json")).toBeVisible();
  await expect(page.getByRole("button", { name: /General/ })).toBeVisible();
});

test("agents dashboard shows desks and skills", async ({ page }) => {
  await ready(page);
  await openTab(page, "Agents");
  await expect(page.getByRole("heading", { name: "Agent Dashboard" })).toBeVisible();
  await expect(page.getByRole("heading", { name: /^Desks/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: /^Skills/ })).toBeVisible();
});

test("rail echoes a chat line", async ({ page }) => {
  await ready(page);
  const box = page.getByPlaceholder("chat, or use a prefix… (try /view)");
  await box.fill("parity ping from the rail");
  await box.press("Enter");
  await expect(page.locator(".sy-rail-entry", { hasText: "parity ping from the rail" })).toBeVisible();
});

test("typing slash opens the command list", async ({ page }) => {
  await ready(page);
  const box = page.getByPlaceholder("chat, or use a prefix… (try /view)");
  await box.fill("/");
  await expect(page.getByRole("listbox", { name: "slash commands" })).toBeVisible();
});

test("an unknown slash command is reported in the rail", async ({ page }) => {
  await ready(page);
  const box = page.getByPlaceholder("chat, or use a prefix… (try /view)");
  await box.fill("/not-a-real-command-parity");
  await box.press("Enter");
  await expect(page.getByText("unknown slash command: /not-a-real-command-parity")).toBeVisible();
});

test("command palette opens with ctrl+k", async ({ page }) => {
  await ready(page);
  await page.keyboard.press("Control+k");
  await expect(page.getByRole("dialog", { name: "Command palette" })).toBeVisible();
});

test("command palette lists the plot tab", async ({ page }) => {
  await ready(page);
  await page.keyboard.press("Control+k");
  const palette = page.getByRole("dialog", { name: "Command palette" });
  await expect(palette.getByRole("option", { name: /Tab: Plot/ })).toBeVisible();
});

test("choosing plot from the palette focuses that tab", async ({ page }) => {
  await ready(page);
  await page.keyboard.press("Control+k");
  const palette = page.getByRole("dialog", { name: "Command palette" });
  await palette.getByRole("option", { name: /Tab: Plot/ }).click();
  await expect(page.getByRole("tab", { name: "Plot" })).toHaveAttribute("aria-selected", "true");
});

test("pasteboard popover opens", async ({ page }) => {
  await ready(page);
  await page.getByRole("button", { name: "Pasteboard" }).click();
  await expect(page.getByRole("dialog", { name: "Pasteboard" })).toBeVisible();
});

test("upload vault dialog opens from the file browser", async ({ page }) => {
  await ready(page);
  await page.getByRole("button", { name: "Add files to the vault" }).click();
  await expect(page.getByRole("dialog", { name: "Add files to the vault" })).toBeVisible();
});

test("upload dialog says files land in vault raw", async ({ page }) => {
  await ready(page);
  await page.getByRole("button", { name: "Add files to the vault" }).click();
  await expect(page.getByText("vault/raw/")).toBeVisible();
  await expect(page.getByRole("button", { name: "Choose files…" })).toBeVisible();
});

test("reviews tab shows the seeded proposal", async ({ page }) => {
  await ready(page);
  await openTab(page, "Reviews");
  await expect(page.getByText("Parity concept").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Accept" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Reject" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Comment & keep" })).toBeVisible();
});

test("commenting on a review keeps the page", async ({ page }) => {
  await ready(page);
  await openTab(page, "Reviews");
  await page.locator(".sy-review-comment").fill("parity note");
  await page.getByRole("button", { name: "Comment & keep" }).click();
  await expect(page.locator(".sy-report-error")).toHaveCount(0);
  await expect(page.getByText("threw an error")).toHaveCount(0);
});

test("sources pane switches from the files browser", async ({ page }) => {
  await ready(page);
  const sources = page.getByRole("tablist", { name: "Bottom pane view" }).getByRole("tab", { name: "Sources" });
  await sources.click();
  await expect(sources).toHaveAttribute("aria-selected", "true");
});

test("zen mode shows the floating chat", async ({ page }) => {
  await ready(page);
  await page.getByRole("button", { name: "Toggle Power / Zen mode" }).click();
  await expect(page.locator(".sy-zen-chat, .sy-zen").first()).toBeVisible();
});

test("zen chat box accepts text", async ({ page }) => {
  await ready(page);
  await page.getByRole("button", { name: "Toggle Power / Zen mode" }).click();
  const box = page.locator("textarea").last();
  await box.fill("zen parity");
  await expect(box).toHaveValue("zen parity");
});

test("returning to power restores the tab strip", async ({ page }) => {
  await ready(page);
  const toggle = page.getByRole("button", { name: "Toggle Power / Zen mode" });
  await toggle.click();
  await toggle.click();
  await expect(page.locator(".sy-tabstrip")).toBeVisible();
  await expect(page.getByRole("tab", { name: "Agents" })).toBeVisible();
});

test("walkthrough can be started from the rail and skipped", async ({ page }) => {
  await ready(page);
  const box = page.getByPlaceholder("chat, or use a prefix… (try /view)");
  await box.fill("/walkthrough");
  // Enter accepts the slash suggestion first, then submits it.
  await box.press("Enter");
  await box.press("Enter");
  await expect(page.getByRole("button", { name: "Skip tour" })).toBeVisible();
  await page.getByRole("button", { name: "Skip tour" }).click();
  await expect(page.getByRole("button", { name: "Skip tour" })).toBeHidden();
});

test("file type filter lists markdown", async ({ page }) => {
  await ready(page);
  await page.locator(".sy-fb-filter-trigger").click();
  await expect(page.locator(".sy-fb-filter-pop")).toBeVisible();
  await expect(page.locator(".sy-fb-filter-ext", { hasText: ".md" }).first()).toBeVisible();
});

test("sort control flips the file order label", async ({ page }) => {
  await ready(page);
  const sort = page.locator(".sy-fb-ctrl", { hasText: /^A[↓↑]$/ });
  const before = await sort.getAttribute("title");
  await sort.click();
  await expect(sort).not.toHaveAttribute("title", before ?? "");
});

test("settings includes the thrusters control", async ({ page }) => {
  await ready(page);
  await openSettings(page);
  const egg = page.getByRole("switch", { name: "fire thrusters?" });
  await egg.scrollIntoViewIfNeeded();
  await expect(egg).toBeVisible();
});

test("switching across the strip does not crash a tab", async ({ page }) => {
  await ready(page);
  for (const name of ["Library", "Sketch", "Plot", "Projects", "Editor"]) {
    await openTab(page, name);
  }
});

test("rail composer advertises slash commands", async ({ page }) => {
  await ready(page);
  await expect(page.getByPlaceholder("chat, or use a prefix… (try /view)")).toBeVisible();
  await expect(page.locator(".sy-rail-composer-meta")).toContainText("commands");
});

test("help stays available after a tab change", async ({ page }) => {
  await ready(page);
  await openTab(page, "Library");
  await page.getByRole("button", { name: "Help", exact: true }).click();
  await expect(page.locator(".sy-help")).toBeVisible();
});

test("pasteboard can be closed with escape", async ({ page }) => {
  await ready(page);
  await page.getByRole("button", { name: "Pasteboard" }).click();
  await expect(page.getByRole("dialog", { name: "Pasteboard" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "Pasteboard" })).toBeHidden();
});

test("workspace menu can be dismissed with escape", async ({ page }) => {
  await ready(page);
  await page.locator(".sy-ws-trigger").click();
  await expect(page.locator(".sy-ws-menu")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator(".sy-ws-menu")).toBeHidden();
});

test("editor can move from the index back to an evidence page", async ({ page }) => {
  await ready(page);
  const search = page.locator(".sy-fb-search");
  await search.fill("wiki/index.md");
  await page.locator(".sy-fb-name", { hasText: /^index\.md$/ }).click();
  await expect(page.getByText("ML walkthrough").first()).toBeVisible();
  await search.fill("evi-attention");
  await page.locator(".sy-fb-name", { hasText: "evi-attention-replaces-recurrence.md" }).click();
  await expect(page.getByText(/attention/i).first()).toBeVisible();
});

test("agents tab survives a round trip through the library", async ({ page }) => {
  await ready(page);
  await openTab(page, "Agents");
  await openTab(page, "Library");
  await openTab(page, "Agents");
  await expect(page.getByRole("heading", { name: "Agent Dashboard" })).toBeVisible();
});
