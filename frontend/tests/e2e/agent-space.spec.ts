import { test, expect } from "@playwright/test";

const NOW = Date.now() / 1000;

const FAKE_RUNS = {
  runs: [
    {
      run_id: "run-space",
      provider: "openai",
      model: "gpt-5.4",
      input_excerpt: "[auto] research T",
      started_at: NOW - 12,
      last_chunk_at: NOW,
      tool_count: 2,
      status: "running",
      activity: "verify ×1",
      step: "verify ×1",
      workspace: "/tmp/ws",
      workspace_name: "ws",
      orchestration_id: "run-space",
      orchestration_strategy: "investigate_verify_synthesize",
      decision_reason: "research-shaped request; verify",
      fanout_n: 2,
      workers_total: 4,
      workers_running: 1,
      preference: 0.7,
      tokens: 1800,
      verification_conflicts: 0,
      blackboard_n: 3,
      candidate_findings_n: 2,
      unique_sources: 2,
      objective: "Research conflicting wiki evidence on T.",
      plan_nodes: [
        {
          node_id: "inv-0", kind: "investigate", role: "investigator",
          dependencies: [], objective: "wiki-search slice", status: "done",
          method_hint: "wiki-search: start with search_wiki",
        },
        {
          node_id: "inv-1", kind: "investigate", role: "investigator",
          dependencies: [], objective: "graph-neighborhood slice", status: "done",
          method_hint: "graph-neighborhood: walk wiki_neighbors",
        },
        {
          node_id: "verify", kind: "verify", role: "verifier",
          dependencies: ["inv-0", "inv-1"], objective: "Verify findings",
          status: "running",
        },
        {
          node_id: "synth", kind: "synthesize", role: "synthesizer",
          dependencies: ["verify"], objective: "Research T", status: "pending",
        },
      ],
      orchestration_messages: [
        { ts: NOW - 8, from: "chief", to: "inv-0", kind: "spawn", text: "investigate: wiki-search slice" },
        { ts: NOW - 7, from: "chief", to: "inv-1", kind: "spawn", text: "investigate: graph slice" },
        { ts: NOW - 3, from: "inv-0", to: "chief", kind: "findings", text: "1 finding(s) · T is supported" },
        { ts: NOW - 2, from: "inv-0", to: "verify", kind: "handoff", text: "verify: Verify findings" },
        { ts: NOW - 2, from: "inv-1", to: "verify", kind: "handoff", text: "verify: Verify findings" },
      ],
    },
    {
      run_id: "run-space-inv-0",
      parent_run_id: "run-space",
      node_id: "inv-0",
      node_kind: "investigate",
      provider: "openai",
      model: "gpt-5.4",
      input_excerpt: "wiki-search slice",
      started_at: NOW - 11,
      last_chunk_at: NOW - 4,
      tool_count: 78,
      status: "done",
      activity: "⚙ Read(path=wiki/index.md)",
      current_tool: "Read",
      worker_index: 0,
    },
    {
      run_id: "run-space-inv-1",
      parent_run_id: "run-space",
      node_id: "inv-1",
      node_kind: "investigate",
      provider: "github_copilot",
      model: "claude-sonnet-4.6",
      input_excerpt: "graph slice",
      started_at: NOW - 11,
      last_chunk_at: NOW - 3,
      tool_count: 1,
      status: "done",
      activity: "neighbors of T",
      worker_index: 1,
    },
    {
      run_id: "run-space-verify",
      parent_run_id: "run-space",
      node_id: "verify",
      node_kind: "verify",
      provider: "openai",
      model: "gpt-5.5",
      input_excerpt: "Verify findings",
      started_at: NOW - 2,
      last_chunk_at: NOW,
      tool_count: 0,
      status: "running",
      activity: "classifying claims",
    },
  ],
};

test("agent space renders chief, pulses board, and drill-in", async ({ page }) => {
  await page.route("**/api/runs/active", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(FAKE_RUNS),
    });
  });
  await page.route("**/api/orchestration/org**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ org: null }),
    });
  });
  await page.route("**/api/orchestration/interrupted", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ runs: [] }),
    });
  });
  await page.route("**/api/tools", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ tools: [] }),
    });
  });
  await page.route("**/api/agent_rules", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ rules: [] }),
    });
  });
  await page.route("**/api/command_palettes", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        rung: { id: "normal", label: "normal", prompt_budget: 8000 },
        commands: [],
        catalog: [],
      }),
    });
  });
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
  await page.route("**/api/rail/events**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ events: [] }),
    });
  });

  await page.addInitScript(() => {
    localStorage.setItem("sy:dash-panel", JSON.stringify({ state: "expanded", heightPx: 220 }));
  });

  await page.goto("/");
  await expect(page.locator(".sy-dash--expanded")).toBeVisible({ timeout: 15_000 });
  await page.evaluate(() => {
    window.dispatchEvent(new CustomEvent("sy:agents-panel", { detail: { state: "expanded" } }));
  });

  const space = page.locator(".sy-agent-space");
  await expect(space).toBeVisible({ timeout: 10_000 });
  await expect(space.getByRole("heading", { name: "Agent space" })).toBeVisible();
  await expect(space.locator("canvas.sy-agent-space-canvas")).toBeVisible();
  await expect(space.getByRole("heading", { name: "Chief of staff" })).toBeVisible();
  await expect(space.getByText("2 investigators")).toBeVisible();
  await expect(space.getByRole("heading", { name: "Message board" })).toBeVisible();
  await expect(space.getByText("blackboard").first()).toBeVisible();
  await expect(space.getByText("inv-0").first()).toBeVisible();
  await expect(space.getByText("78 tools").first()).toBeVisible();
  await expect(space.getByText("1 running").first()).toBeVisible();
  await expect(space.locator(".sy-agent-space-msg-route").filter({ hasText: "chief" }).first()).toBeVisible();
  await expect(space.getByText("1 finding(s)", { exact: false })).toBeVisible();

  await space.locator(".sy-agent-space-roster-btn").filter({ hasText: "verify" }).click();
  await expect(space.getByRole("heading", { name: "verifier" })).toBeVisible();
  await expect(space.locator(".sy-agent-space-activity")).toContainText("classifying");
  await space.getByRole("button", { name: /chief of staff/ }).click();
  await expect(space.getByRole("heading", { name: "Chief of staff" })).toBeVisible();

  await space.locator(".sy-agent-space-roster-btn").filter({ hasText: "blackboard" }).click();
  await expect(space.getByRole("heading", { name: "Blackboard" })).toBeVisible();

  await expect(page.getByRole("heading", { name: "Recently finished" })).toHaveCount(0);

  const runBoxes = await page.locator(".sy-agents-run").evaluateAll((els) =>
    els.map((el) => {
      const r = (el as HTMLElement).getBoundingClientRect();
      return { y: r.y, bottom: r.bottom, height: r.height };
    }),
  );
  for (let i = 1; i < runBoxes.length; i++) {
    expect(runBoxes[i]!.y + 0.5).toBeGreaterThanOrEqual(runBoxes[i - 1]!.bottom);
  }
});
